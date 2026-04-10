# -*- coding: utf-8 -*-
'''!
  @file DEMO_DUAL_RADAR.py
  @brief Dual Radar demonstration using two C4001 radars simultaneously
  @details Radar 1: Connected to /dev/ttyAMA0 (default TX/RX pins)
           Radar 2: Connected to /dev/ttyS0 (GPIO 16: TX, GPIO 20: RX)
  @version V1.0
  @date 2024-2-20
'''
from __future__ import print_function
import sys
import os
sys.path.append("../")
import time
import threading
from RADAR_Library2 import *

# Create two radar instances with different serial ports
# Radar 1: Default UART (/dev/ttyAMA0)
radar1 = DFRobot_C4001_UART(9600, port="/dev/ttyAMA0")

# Radar 2: Secondary UART (/dev/ttyS0) - used for GPIO 16 (TX) and GPIO 20 (RX)
# Note: Ensure /dev/ttyS0 is configured in /boot/config.txt
radar2 = DFRobot_C4001_UART(9600, port="/dev/ttyS0")

# Thread synchronization
lock = threading.Lock()
radar1_data = {'number': 0, 'speed': 0, 'range': 0, 'ready': False}
radar2_data = {'number': 0, 'speed': 0, 'range': 0, 'ready': False}

def setup_radar(radar, radar_id):
    '''Setup and configure a radar'''
    max_retries = 5
    retries = 0
    
    while retries < max_retries:
        if radar.begin():
            break
        retries += 1
        if retries < max_retries:
            print(f"Radar {radar_id} initialize failed, retrying... ({retries}/{max_retries})")
            time.sleep(1)
        else:
            print(f"Radar {radar_id} failed to initialize after {max_retries} attempts!")
            return False
    
    # Set to SPEED_MODE
    radar.set_sensor_mode(SPEED_MODE)
    
    # Configure detection range and sensitivity
    radar.set_detect_thres(30, 2000, 20)
    radar.set_fretting_detection(FRETTING_ON)
    radar.set_trig_sensitivity(8)
    
    # Print configuration
    print(f"\n=== Radar {radar_id} Configuration ===")
    try:
        print(f"Min range: {radar.get_tmin_range()} cm")
        print(f"Max range: {radar.get_tmax_range()} cm")
        print(f"Threshold: {radar.get_thres_range()}")
        print(f"Fretting detection: {radar.get_fretting_detection()}")
        print(f"Trigger sensitivity: {radar.get_trig_sensitivity()}")
    except Exception as e:
        print(f"Error getting Radar {radar_id} configuration: {e}")
    
    return True

def read_radar_continuously(radar, radar_id, data_dict):
    '''Continuously read from a radar in a separate thread'''
    while True:
        try:
            number = radar.get_target_number()
            speed = radar.get_target_speed()
            range_val = radar.get_target_range()
            
            with lock:
                data_dict['number'] = number
                data_dict['speed'] = speed
                data_dict['range'] = range_val
                data_dict['ready'] = True
            
            time.sleep(0.1)
        except Exception as e:
            print(f"Error reading Radar {radar_id}: {e}")
            time.sleep(0.5)

def main():
    '''Main function to setup and display data from both radars'''
    print("=====================================")
    print("   Dual Radar System Initialization  ")
    print("=====================================\n")
    
    # Setup both radars
    print("Setting up Radar 1 (/dev/ttyAMA0)...")
    if not setup_radar(radar1, 1):
        print("Failed to setup Radar 1!")
        return
    
    time.sleep(1)
    
    print("\nSetting up Radar 2 (/dev/ttyS0)...")
    if not setup_radar(radar2, 2):
        print("Failed to setup Radar 2!")
        # Continue anyway - at least Radar 1 works
    
    time.sleep(1)
    
    # Start threads to continuously read from both radars
    print("\nStarting data acquisition threads...\n")
    thread1 = threading.Thread(target=read_radar_continuously, args=(radar1, 1, radar1_data), daemon=True)
    thread2 = threading.Thread(target=read_radar_continuously, args=(radar2, 2, radar2_data), daemon=True)
    
    thread1.start()
    thread2.start()
    
    # Give threads time to start
    time.sleep(0.5)
    
    # Display data in main thread
    print("=====================================")
    print("   Live Data from Both Radars        ")
    print("=====================================\n")
    
    try:
        while True:
            with lock:
                print(f"{'RADAR 1':^20} | {'RADAR 2':^20}")
                print("-" * 43)
                
                if radar1_data['ready']:
                    r1_status = "Target" if radar1_data['number'] > 0 else "No Target"
                    r1_info = f"{r1_status}\n"
                    r1_info += f"Speed: {radar1_data['speed']:.2f} m/s\n"
                    r1_info += f"Range: {radar1_data['range']:.2f} m"
                else:
                    r1_info = "Initializing..."
                
                if radar2_data['ready']:
                    r2_status = "Target" if radar2_data['number'] > 0 else "No Target"
                    r2_info = f"{r2_status}\n"
                    r2_info += f"Speed: {radar2_data['speed']:.2f} m/s\n"
                    r2_info += f"Range: {radar2_data['range']:.2f} m"
                else:
                    r2_info = "Initializing..."
                
                # Format and print side by side
                r1_lines = r1_info.split('\n')
                r2_lines = r2_info.split('\n')
                max_lines = max(len(r1_lines), len(r2_lines))
                
                for i in range(max_lines):
                    r1_line = r1_lines[i] if i < len(r1_lines) else ""
                    r2_line = r2_lines[i] if i < len(r2_lines) else ""
                    print(f"{r1_line:^20} | {r2_line:^20}")
                
                print("")
            
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\n\nShutdown requested...")
        print("Closing radars...")
        # Graceful shutdown
        time.sleep(0.5)

if __name__ == "__main__":
    main()
