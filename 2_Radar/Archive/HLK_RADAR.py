import serial
import serial.tools.list_ports
import time

RADAR_PORT = '/dev/ttyAMA1'
BAUD_RATE = 115200

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
    frame_header = b'\xf4\xf3\xf2\xf1'
    frame_tail = b'\xf8\xf7\xf6\xf5'
    
    # Check if header exists
    if frame_header in buffer:
        idx = buffer.find(frame_header)
        
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
                if buffer[tail_idx : tail_idx+4] == frame_tail:
                    
                    target_count = payload[0] if len(payload) > 0 else 0
                    alarm_info = "Approaching Target" if len(payload) > 1 and payload[1] == 0x01 else "No Approaching Target"
                    if target_count > 0:
                        print(f"\n📡 Frame Detected! Targets: {target_count} | Status: {alarm_info}")
                        print("-" * 50)
                    
                    # Parse each target (5 bytes per target)
                    for i in range(target_count):
                        offset = 2 + (i * 5)
                        if offset + 5 <= len(payload):
                            # Angle: Actual angle = Report value - 0x80
                            angle_raw = payload[offset]
                            angle = angle_raw - 128
                            
                            # Distance: 0~100m (already relative distance from radar)
                            distance = payload[offset+1]
                            
                            # Speed Direction: 00 = Close, 01 = Stay away
                            raw_dir = payload[offset+2]
                            is_approaching = (raw_dir == 0x00)
                            speed_dir = "Approaching" if is_approaching else "Moving Away"
                            
                            # Speed Value: 0~120 km/h (magnitude)
                            speed = payload[offset+3]

                            # Represent relative speed: positive when closing, negative when opening
                            rel_speed_kmh = speed if is_approaching else -speed

                            # Time To Collision (TTC) in seconds, only meaningful when object is closing
                            ttc_display = "--"
                            if rel_speed_kmh > 0 and distance > 0:
                                # Convert km/h to m/s
                                rel_speed_ms = rel_speed_kmh * (1000.0 / 3600.0)
                                if rel_speed_ms > 0:
                                    ttc_s = distance / rel_speed_ms
                                    ttc_display = f"{ttc_s:.1f} s"

                            # Signal-to-Noise Ratio (SNR)
                            snr = payload[offset+4]
                            
                            rel_speed_desc = f"{abs(rel_speed_kmh)} km/h {'closing' if rel_speed_kmh > 0 else 'opening'}" if rel_speed_kmh != 0 else "0 km/h"

                            print(
                                f"  🎯 Target {i+1}: "
                                f"Distance={distance} m | "
                                f"RelSpeed={rel_speed_desc} ({speed_dir}) | "
                                f"Angle={angle}° | "
                                f"TTC={ttc_display}"
                            )
                
                # Return the remaining buffer after removing the processed frame
                return buffer[idx + total_frame_size:]
                
    # If no complete frame is found, keep the buffer size manageable
    if len(buffer) > 1024:
        return buffer[-500:]
        
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
                
            time.sleep(0.01)
            
    except serial.SerialException as e:
        print(f"  ❌ Error: {e}")
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("\n🔌 Port closed.")

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