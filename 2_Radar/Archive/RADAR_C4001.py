# -*- coding: utf-8 -*
'''!
  @file BLIND_SPOT_HYBRID.py
  @brief Hybrid blind spot detection - detects stationary AND moving objects
  @copyright  Copyright (c) 2010 DFRobot Co.Ltd (http://www.dfrobot.com)
  @license    The MIT License (MIT)
'''
from __future__ import print_function
import sys
import os
sys.path.append("../")
import time
import RPi.GPIO as GPIO
from RADAR_Library2 import *
import statistics
from LED import led_controller

'''
  Select to use i2c or UART
  I2C_MODE
  UART_MODE
'''
ctype = UART_MODE

if ctype == I2C_MODE:
  I2C_1 = 0x01
  I2C_ADDR = 0X2A
  radar = DFRobot_C4001_I2C (I2C_1, I2C_ADDR)
elif ctype == UART_MODE:
  radar = DFRobot_C4001_UART(9600)

class RadarFilter:
    def __init__(self, size=5, alpha=0.2):
        self.buffer = []
        self.size = size
        self.alpha = alpha
        self.filtered_val = None

    def update(self, new_val):
        self.buffer.append(new_val)
        if len(self.buffer) > self.size:
            self.buffer.pop(0)
        
        median_val = statistics.median(self.buffer)
        
        if self.filtered_val is None:
            self.filtered_val = median_val
        else:
            self.filtered_val = (self.alpha * median_val) + ((1 - self.alpha) * self.filtered_val)
            
        return self.filtered_val

# Blind spot detection configuration
BLIND_SPOT_MIN_DISTANCE = 60      # Minimum detection distance (cm)
BLIND_SPOT_MAX_DISTANCE = 2000     # Maximum blind spot range (10 meters)
STATIONARY_THRESHOLD = 20         # Speed threshold for stationary object (cm/s)
FAST_SPEED_THRESHOLD = 2        # Speed threshold for fast-moving object (cm/s)
ALERT_THRESHOLD = 3               # Consecutive detections before alert

# Create filters for smoothing
distance_filter = RadarFilter(size=5, alpha=0.30)
speed_filter = RadarFilter(size=5, alpha=0.30)
energy_filter = RadarFilter(size=5, alpha=0.30)

# Track detection state
detection_counter = 0
object_detected_time = None
object_in_blind_spot = False
last_alert_type = None

def setup():
  while (radar.begin() == False):
    print("Sensor initialize failed!!")
    time.sleep(1)
  
  print("Sensor initialized!")
  time.sleep(1)
  
  '''
    Use SPEED_MODE for hybrid detection
    SPEED_MODE detects moving objects and returns distance/speed data
    But we also check for stationary objects by looking at distance
  '''
  print("Setting sensor mode to SPEED_MODE (Hybrid Detection)...")
  radar.set_sensor_mode(SPEED_MODE)
  time.sleep(1)
  
  # Set detection range for blind spot area
  print("Setting blind spot detection range...")
  print(f"  Detecting objects from {BLIND_SPOT_MIN_DISTANCE}cm to {BLIND_SPOT_MAX_DISTANCE}cm")
  radar.set_detection_range(BLIND_SPOT_MIN_DISTANCE, BLIND_SPOT_MAX_DISTANCE, BLIND_SPOT_MAX_DISTANCE)
  time.sleep(0.5)
  
  # Set detect threshold - lower values detect stationary objects better
  print("Setting detection threshold...")
  radar.set_detect_thres(BLIND_SPOT_MIN_DISTANCE, BLIND_SPOT_MAX_DISTANCE, 30)
  time.sleep(0.5)
  
  # Set trigger sensitivity for blind spot detection
  print("Setting trigger sensitivity...")
  radar.set_trig_sensitivity(4)  # Maximum sensitivity
  time.sleep(0.5)
  
  # Set keep sensitivity
  print("Setting keep sensitivity...")
  radar.set_keep_sensitivity(5)  # Very sensitive
  time.sleep(0.5)
  
  # Trigger delay and keep timeout
  print("Setting delay parameters...")
  radar.set_delay(0, 3)  # Minimal trigger delay for immediate alert
  time.sleep(0.5)
  
  # Set IO polarity
  print("Setting IO polarity...")
  radar.set_io_polaity(1)  # High when object detected
  time.sleep(1)
  
  # Read and display configuration
  print("\n=== BLIND SPOT HYBRID DETECTION CONFIGURATION ===")
  print(f"Mode: SPEED_MODE (Hybrid Detection)")
  print(f"Detection Range: {radar.get_min_range()}cm - {radar.get_max_range()}cm")
  print(f"Stationary Threshold: {STATIONARY_THRESHOLD} cm/s")
  print(f"Fast Speed Threshold: {FAST_SPEED_THRESHOLD} cm/s")
  print(f"Trig Sensitivity: {radar.get_trig_sensitivity()}")
  print(f"Keep Sensitivity: {radar.get_keep_sensitivity()}")
  print("=== Starting hybrid blind spot monitoring ===\n")

def get_object_type(speed):
  """Determine object type based on speed"""
  if speed < STATIONARY_THRESHOLD:
    return "STATIONARY"
  elif speed < FAST_SPEED_THRESHOLD:
    return "SLOW_MOVING"
  else:
    return "FAST_MOVING"

def get_alert_color(speed):
  """Return LED color based on threat level"""
  if speed < STATIONARY_THRESHOLD:
    # Stationary object - YELLOW (medium threat)
    return (255, 255, 0)
  elif speed < FAST_SPEED_THRESHOLD:
    # Slow moving - ORANGE (higher threat)
    return (255, 165, 0)
  else:
    # Fast moving - RED (critical threat)
    return (255, 0, 0)

def loop():
  global detection_counter, object_detected_time, object_in_blind_spot, last_alert_type
  
  # In SPEED_MODE, get_target_number() returns number of targets detected
  num_targets = radar.get_target_number()
  
  if num_targets > 0:
    detection_counter += 1
    
    # Get raw data
    raw_distance = radar.get_target_range()
    raw_speed = radar.get_target_speed()
    raw_energy = radar.get_target_energy()
    
    # Apply filters
    distance = distance_filter.update(raw_distance)
    speed = speed_filter.update(raw_speed)
    energy = energy_filter.update(raw_energy)
    
    # Determine object type
    obj_type = get_object_type(speed)
    
    if detection_counter >= ALERT_THRESHOLD and not object_in_blind_spot:
      print(f"\n🚨 ALERT: OBJECT IN BLIND SPOT! 🚨")
      print(f"   Type: {obj_type}")
      print(f"   Distance: {distance:.1f}cm")
      print(f"   Speed: {speed:.1f}cm/s")
      
      object_detected_time = time.time()
      object_in_blind_spot = True
      last_alert_type = obj_type
      detection_counter = 0
      
      # Set LED color based on threat level
      color = get_alert_color(speed)
      try:
        # Try neopixel method first
        if hasattr(led_controller, 'set_neopixel_color'):
          led_controller.set_neopixel_color(color[0], color[1], color[2])
        else:
          # Fallback to solid color (BGR format for neopixel)
          led_controller.set_color_solid((color[2], color[1], color[0]))
      except:
        pass
    
    if object_in_blind_spot:
      elapsed = time.time() - object_detected_time
      status_icon = "🔴" if obj_type == "FAST_MOVING" else "🟠" if obj_type == "SLOW_MOVING" else "🟡"
      print(f"{status_icon} {obj_type}: {distance:.1f}cm @ {speed:.1f}cm/s (Time: {elapsed:.1f}s)")
  else:  # No object detected
    if object_in_blind_spot:
      elapsed = time.time() - object_detected_time
      print(f"\n✓ Object left blind spot (was in blind spot for {elapsed:.1f}s)\n")
      object_in_blind_spot = False
      detection_counter = 0
      last_alert_type = None
      
      # Turn off LED
      led_controller.off()
    elif detection_counter > 0:
      # Reset counter if no sustained detection
      detection_counter = 0
  
  time.sleep(0.05)  # 20Hz update rate for responsiveness

def calibrate():
  """
  Calibration mode - test the radar at different distances and speeds
  """
  print("\n=== BLIND SPOT CALIBRATION MODE ===")
  print(f"Detection range: {BLIND_SPOT_MIN_DISTANCE}cm - {BLIND_SPOT_MAX_DISTANCE}cm")
  print("Move your hand/object through the blind spot area")
  print("  - Stationary: speed < 20 cm/s (Yellow LED)")
  print("  - Slow Moving: 20-100 cm/s (Orange LED)")
  print("  - Fast Moving: > 100 cm/s (Red LED)")
  print("Press Ctrl+C to exit\n")
  
  try:
    while True:
      num_targets = radar.get_target_number()
      
      if num_targets > 0:
        raw_distance = radar.get_target_range()
        raw_speed = radar.get_target_speed()
        raw_energy = radar.get_target_energy()
        
        distance = distance_filter.update(raw_distance)
        speed = speed_filter.update(raw_speed)
        energy = energy_filter.update(raw_energy)
        
        obj_type = get_object_type(speed)
        color = get_alert_color(speed)
        
        print(f"[{obj_type}] Distance: {distance:.1f}cm | Speed: {speed:.1f}cm/s | Energy: {energy:.0f}")
        
        # Update LED
        try:
          if hasattr(led_controller, 'set_neopixel_color'):
            led_controller.set_neopixel_color(color[0], color[1], color[2])
          else:
            led_controller.set_color_solid((color[2], color[1], color[0]))
        except:
          pass
      else:
        print("✗ No object")
        led_controller.off()
      
      time.sleep(0.1)
  except KeyboardInterrupt:
    print("\nCalibration complete")
    led_controller.off()

if __name__ == "__main__":
  setup()
  
  try:
    # Uncomment one of these to run:
    # calibrate()  # For calibration testing
    
    # Normal operation:
    while True:
      loop()
  except KeyboardInterrupt:
    print("\n\nShutting down...")
    led_controller.off()
    print("Cleanup complete")
