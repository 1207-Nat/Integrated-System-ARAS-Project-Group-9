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
# Protocol & Math Coefficients
# ==========================================
FRAME_HEADER = b'\xf4\xf3\xf2\xf1' # Standard starting byte sequence for LD2451
FRAME_TAIL = b'\xf8\xf7\xf6\xf5'   # Standard ending byte sequence for LD2451
ANGLE_OFFSET = 128                 # Subtracted from the raw payload byte to calculate true angle

# ==========================================
# Buffer & Performance Thresholds
# ==========================================
MAX_BUFFER_SIZE = 1024             # Maximum bytes allowed in the queue before forced clearing
TRIMMED_BUFFER_SIZE = 500          # The number of recent bytes to keep when the buffer overfills
READ_DELAY_SEC = 0.01              # Sleep duration (seconds) between serial reads to prevent CPU hogging


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


def parse_radar_data(buffer):
    """
    Parses the buffer for the reporting data frame (F4 F3 F2 F1)
    and extracts target information.
    """
    # Check if header exists
    if FRAME_HEADER in buffer:
        idx = buffer.find(FRAME_HEADER)
        
        # Ensure we have at least enough bytes for header (4) + length (2)
        if len(buffer) >= idx + 6:
            # Read frame length (Little Endian)
            data_length = int.from_bytes(buffer[idx+4:idx+6], byteorder='little')
            
            # Ensure the full frame (header + length + data + tail) is in the buffer
            total_frame_size = 4 + 2 + data_length + 4
            if len(buffer) >= idx + total_frame_size:
                
                # Extract the intra-frame data
                payload = buffer[idx+6 : idx+6+data_length]
                
                # Verify the tail matches
                tail_idx = idx + 6 + data_length
                if buffer[tail_idx : tail_idx+4] == FRAME_TAIL:
                    
                    target_count = payload[0] if len(payload) > 0 else 0
                    alarm_info = "Approaching Target" if len(payload) > 1 and payload[1] == 0x01 else "No Approaching Target"
                    if target_count > 0:
                        print(f"\n📡 Frame Detected! Targets: {target_count} | Status: {alarm_info}")
                        print("-" * 50)
                    
                    # Parse each target (5 bytes per target)
                    for i in range(target_count):
                        offset = 2 + (i * 5)
                        if offset + 5 <= len(payload):
                            # Angle: Actual angle = Report value - Offset
                            angle_raw = payload[offset]
                            angle = angle_raw - ANGLE_OFFSET
                            
                            # Distance: 0~100m
                            distance_m = payload[offset+1]
                            
                            # Speed Direction: 00 = Close, 01 = Stay away
                            speed_dir = "Approaching" if payload[offset+2] == 0x00 else "Moving Away"
                            
                            # Speed Value: 0~120 km/h
                            speed_kmh = payload[offset+3]
                            
                            # Signal-to-Noise Ratio (SNR)
                            snr = payload[offset+4]

                            print(f"  🎯 Target {i+1}: Distance={distance_m} m | Speed={speed_kmh} km/h  | Angle={angle}°")

                            # Publish only LD2451-owned segment (LEDs 0-1) via shared arbiter.
                            led_controller.update_ld2451(float(distance_m), float(speed_kmh), source='ld2451')

                    # If no targets in this frame, turn LEDs off
                    if target_count == 0:
                        led_controller.off(source='ld2451')
                
                # Return the remaining buffer after removing the processed frame
                return buffer[idx + total_frame_size:]
                
    # If no complete frame is found, keep the buffer size manageable to prevent memory leaks
    if len(buffer) > MAX_BUFFER_SIZE:
        return buffer[-TRIMMED_BUFFER_SIZE:]
        
    return buffer


def read_radar_stream(port, baud_rate=115200, duration=None):
    """Connect to the port and continuously parse data"""
    print(f"\n📡 Connecting to {port} at {baud_rate} baud...")
    try:
        ser = serial.Serial(port, baud_rate, timeout=0.1)
        print(f"  ✓ Connected to {port}. Listening for data...\n")
        
        buffer = b''
        start_time = time.time()

        while True:
            if duration is not None and (time.time() - start_time) >= duration:
                break
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                buffer += data
                
                # Try to parse the buffer
                buffer = parse_radar_data(buffer)
                
            time.sleep(READ_DELAY_SEC)
            
    except serial.SerialException as e:
        print(f"  ❌ Error: {e}")
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    finally:
        print("\nReleasing hardware resources...")
        # Use the new cleanup method to kill the zombie audio threads
        if hasattr(led_controller, 'cleanup'):
            led_controller.cleanup()
        else:
            led_controller.off(source='ld2451')
            
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Port closed.")

def main():
    print("=" * 50)
    print("HLK-LD2451 Data Parser")
    print("=" * 50)
    
    list_available_ports()
    print(f"\nUsing fixed radar port: {RADAR_PORT} @ {BAUD_RATE} baud")
    print("Press Ctrl+C to stop.\n")

    read_radar_stream(RADAR_PORT, baud_rate=BAUD_RATE, duration=None)


if __name__ == "__main__":
    main()