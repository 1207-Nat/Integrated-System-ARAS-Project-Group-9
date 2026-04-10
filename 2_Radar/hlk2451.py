import serial
import serial.tools.list_ports
import time

from LED2 import led_controller  # Shared NeoPixel arbiter

# ==========================================
# Connection Settings
# ==========================================
RADAR_PORT = '/dev/ttyAMA1'
BAUD_RATE = 115200

# ==========================================
# LD2451 CONFIGURATION VARIABLES
# Easily change these coefficients to update the radar at runtime.
# ==========================================
# Target Detection Parameters 
DETECTION_RANGE_M = 20       # Maximum detection distance (0x0A-0xFF meters)
DETECTION_DIRECTION = 1      # 00: Only detect away, 01: Only detect approach, 02: All detected
DETECTION_SPEED_KMH = 3      # Minimum motion speed (00-0x78 km/h)
DELAY_DETECTION_S = 1        # No target delay time (00-0xFF seconds)

# Sensitivity Parameters 
TRIGGER_COUNT = 3            # Cumulative effective trigger times (1-0A)
SNR_THRESHOLD = 4            # Signal-to-noise ratio threshold (Default is 4, 3-8 limits sensitivity)

# ==========================================
# Protocol & Math Coefficients
# ==========================================
REPORT_HEADER = b'\xf4\xf3\xf2\xf1' # Starting byte sequence for reporting frames 
REPORT_TAIL = b'\xf8\xf7\xf6\xf5'   # Ending byte sequence for reporting frames 
CMD_HEADER = b'\xfd\xfc\xfb\xfa'    # Starting byte sequence for config commands 
CMD_TAIL = b'\x04\x03\x02\x01'      # Ending byte sequence for config commands 
ANGLE_OFFSET = 128                  # Subtracted from the raw payload byte to calculate true angle 

# ==========================================
# Buffer & Performance Thresholds
# ==========================================
MAX_BUFFER_SIZE = 1024             
TRIMMED_BUFFER_SIZE = 500          
READ_DELAY_SEC = 0.01              


def display_radar_settings():
    """Prints the hardcoded configuration settings for the LD2451."""
    print("=" * 50)
    print("LD2451 Radar Configuration Settings")
    print("=" * 50)
    print(f"{'Detection Range':<25}: {DETECTION_RANGE_M} m")
    
    # Map direction int to a readable string for the terminal
    dir_str = "All detected"
    if DETECTION_DIRECTION == 0: dir_str = "Only detect away"
    elif DETECTION_DIRECTION == 1: dir_str = "Only detect approach"
    
    print(f"{'Detection Direction':<25}: {dir_str} ({DETECTION_DIRECTION})")
    print(f"{'Detection Speed':<25}: {DETECTION_SPEED_KMH} km/h")
    print(f"{'Delay Detection':<25}: {DELAY_DETECTION_S} s")
    print(f"{'Trigger Count':<25}: {TRIGGER_COUNT}")
    print(f"{'SNR Threshold':<25}: {SNR_THRESHOLD}")
    print("=" * 50)


def list_available_ports():
    """List all available serial ports"""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("❌ No serial ports found!")
        return []
    
    print("✓ Available serial ports:")
    port_list = []
    for port in ports:
        print(f"  - {port.device}: {port.description}")
        port_list.append(port.device)
    return port_list


def send_config_command(ser, cmd_word, cmd_value=b''):
    """
    Constructs and sends a configuration frame to the LD2451.
    Format: Header (4) + Length (2) + Command Word (2) + Command Value (N) + Tail (4)
    """
    data_len = len(cmd_word) + len(cmd_value)
    len_bytes = data_len.to_bytes(2, byteorder='little')
    
    frame = CMD_HEADER + len_bytes + cmd_word + cmd_value + CMD_TAIL
    ser.write(frame)
    time.sleep(0.1) # Wait for radar to process and ACK
    
    if ser.in_waiting > 0:
        ack = ser.read(ser.in_waiting)
        return ack
    return None


def configure_radar(ser):
    """Executes the radar command configuration process (Enable -> Send -> End)"""
    print("\n⚙️  Applying Radar Configuration...")
    
    # 1. Enable Configuration Command (0x00FF, 0x0001) 
    print("  -> Enabling configuration mode...")
    send_config_command(ser, b'\xff\x00', b'\x01\x00')

    # 2. Set Target Detection Parameters (0x0002) 
    print(f"  -> Setting Range:{DETECTION_RANGE_M}m, Dir:{DETECTION_DIRECTION}, Speed:{DETECTION_SPEED_KMH}km/h, Delay:{DELAY_DETECTION_S}s")
    target_params = bytes([
        DETECTION_RANGE_M, 
        DETECTION_DIRECTION, 
        DETECTION_SPEED_KMH, 
        DELAY_DETECTION_S
    ])
    send_config_command(ser, b'\x02\x00', target_params)

    # 3. Set Sensitivity Parameters (0x0003) 
    print(f"  -> Setting Trigger Count:{TRIGGER_COUNT}, SNR:{SNR_THRESHOLD}")
    sensitivity_params = bytes([
        TRIGGER_COUNT, 
        SNR_THRESHOLD, 
        0x00, # Extended Parameter 1 
        0x00  # Extended Parameter 2 
    ])
    send_config_command(ser, b'\x03\x00', sensitivity_params)

    # 4. End Configuration Command (0x00FE) 
    print("  -> Ending configuration mode and returning to detection state...")
    send_config_command(ser, b'\xfe\x00')
    print("✅ Configuration applied successfully!\n")


def parse_radar_data(buffer):
    """
    Parses the buffer for the reporting data frame (F4 F3 F2 F1)
    and extracts target information.
    """
    if REPORT_HEADER in buffer:
        idx = buffer.find(REPORT_HEADER)
        
        if len(buffer) >= idx + 6:
            data_length = int.from_bytes(buffer[idx+4:idx+6], byteorder='little')
            total_frame_size = 4 + 2 + data_length + 4
            
            if len(buffer) >= idx + total_frame_size:
                payload = buffer[idx+6 : idx+6+data_length]
                tail_idx = idx + 6 + data_length
                
                if buffer[tail_idx : tail_idx+4] == REPORT_TAIL:
                    target_count = payload[0] if len(payload) > 0 else 0
                    alarm_info = "Approaching Target" if len(payload) > 1 and payload[1] == 0x01 else "No Approaching Target"
                    
                    if target_count > 0:
                        print(f"\n📡 Frame Detected! Targets: {target_count} | Status: {alarm_info}")
                        print("-" * 50)
                    
                    for i in range(target_count):
                        offset = 2 + (i * 5)
                        if offset + 5 <= len(payload):
                            angle_raw = payload[offset]
                            angle = angle_raw - ANGLE_OFFSET 
                            distance_m = payload[offset+1] 
                            speed_dir = "Approaching" if payload[offset+2] == 0x00 else "Moving Away" 
                            speed_kmh = payload[offset+3] 
                            snr = payload[offset+4] 

                            print(f"  🎯 Target {i+1}: Distance={distance_m} m | Speed={speed_kmh} km/h  | Angle={angle}°")

                            led_controller.update_ld2451(float(distance_m), float(speed_kmh), source='ld2451')

                    if target_count == 0:
                        led_controller.off(source='ld2451')
                
                return buffer[idx + total_frame_size:]
                
    if len(buffer) > MAX_BUFFER_SIZE:
        return buffer[-TRIMMED_BUFFER_SIZE:]
        
    return buffer


def read_radar_stream(port, baud_rate=115200, duration=None):
    """Connect to the port, apply configuration, and continuously parse data"""
    
    # --- Always display settings when the stream starts ---
    display_radar_settings()
    
    print(f"\n📡 Connecting to {port} at {baud_rate} baud...")
    try:
        ser = serial.Serial(port, baud_rate, timeout=0.1)
        print(f"  ✓ Connected to {port}.")
        
        # Apply parameters before reading the stream
        configure_radar(ser)
        
        print("Listening for data...\n")
        
        buffer = b''
        start_time = time.time()

        while True:
            if duration is not None and (time.time() - start_time) >= duration:
                break
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                buffer += data
                buffer = parse_radar_data(buffer)
                
            time.sleep(READ_DELAY_SEC)
            
    except serial.SerialException as e:
        print(f"  ❌ Error: {e}")
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    finally:
        print("\nReleasing hardware resources...")
        led_controller.off(source='ld2451')
            
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Port closed.")

def main():
    print("=" * 50)
    print("HLK-LD2451 Data Parser & Configurator")
    print("=" * 50)
    
    list_available_ports()
    print(f"\nUsing fixed radar port: {RADAR_PORT} @ {BAUD_RATE} baud")
    print("Press Ctrl+C to stop.\n")

    read_radar_stream(RADAR_PORT, baud_rate=BAUD_RATE, duration=None)


if __name__ == "__main__":
    main()