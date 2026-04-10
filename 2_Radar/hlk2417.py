import serial
import serial.tools.list_ports
import time
import struct # Added for parsing binary data

from LED2 import led_controller  # Shared NeoPixel arbiter

# ==========================================
# Connection Settings
# ==========================================
RADAR_PORT = '/dev/ttyAMA3'
BAUD_RATE = 115200

# ==========================================
# LD2417 CONFIGURATION VARIABLES
# Values multiplied by 100 automatically during payload construction.
# ==========================================
MAX_WARNING_DISTANCE_M = 70      # Range: 2 to 100 m 
MIN_WARNING_SPEED_KMH = 3        # Range: 1 to 175 km/h
COEFF_0_10M = 60                 # 0~10m Detection coefficient 
COEFF_10_26M = 22                # 10~26m Detection coefficient 
COEFF_26_40M = 10                 # 26~40m Detection coefficient 
COEFF_40_100M = 8                # 40~100m Detection coefficient 

# ==========================================
# Radar Filtering & Performance Thresholds
# ==========================================
SCOOTER_MAX_SPEED_KMH = 20.0       # (Reserved for future logic)
MIN_VALID_SPEED_KMH = 1.5          # Minimum speed required to process a target (ignores stationary clutter)
CLUTTER_DIST_THRESH_M = 15.0       # Distance beyond which slow targets are actively ignored
CONFIRM_FRAMES = 2                 # Number of consecutive frames required to confirm a target (anti-ghosting)
SIDE_HOLD_SEC = 0.35               # Seconds to hold the LED state to prevent flickering during track merge/swap
READ_DELAY_SEC = 0.01              # Sleep duration (seconds) between serial reads

# ==========================================
# Protocol Commands & Frame Headers
# ==========================================
REPORT_HEADER = b'\xAA\xAA' 
REPORT_TAIL = b'\x55\x55'
CMD_HEAD = b'\xFD\xFC\xFB\xFA' 
CMD_TAIL = b'\x04\x03\x02\x01' 

# 1) Enable configuration mode (required first)
ENABLE_CONF = CMD_HEAD + b'\x04\x00' + b'\xFF\x00\x03\x00' + CMD_TAIL 

# 3) End configuration mode (resume reporting)
END_CONF = CMD_HEAD + b'\x02\x00' + b'\xFE\x00' + CMD_TAIL 

# ==========================================
# Global State Tracking
# ==========================================
left_streak = 0
right_streak = 0
confirmed_left_target = None
confirmed_right_target = None
last_confirmed_left_ts = 0.0
last_confirmed_right_ts = 0.0


def display_radar_settings():
    """Prints the hardcoded configuration settings for the LD2417."""
    print("=" * 50)
    print("LD2417 Radar Configuration Settings")
    print("=" * 50)
    print(f"{'Max Warning Distance':<25}: {MAX_WARNING_DISTANCE_M} m")
    print(f"{'Min Warning Speed':<25}: {MIN_WARNING_SPEED_KMH} km/h")
    print(f"{'0~10m Coefficient':<25}: {COEFF_0_10M}")
    print(f"{'10~26m Coefficient':<25}: {COEFF_10_26M}")
    print(f"{'26~40m Coefficient':<25}: {COEFF_26_40M}")
    print(f"{'40~100m Coefficient':<25}: {COEFF_40_100M}")
    print("=" * 50)


def list_available_ports():
    """List all available serial ports."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found!")
        return []

    print("Available serial ports:")
    port_list = []
    for port in ports:
        print(f"  - {port.device}: {port.description}")
        port_list.append(port.device)
    return port_list


def build_config_payload():
    """Dynamically construct the parameter configuration payload based on variables."""
    # Command word: 0x0070
    payload = b'\x70\x00' 
    
    # Pack parameters (Command Word + 4-byte uint32 little-endian value * 100)
    payload += b'\x00\x00' + struct.pack('<I', int(MAX_WARNING_DISTANCE_M * 100)) 
    payload += b'\x01\x00' + struct.pack('<I', int(MIN_WARNING_SPEED_KMH * 100))
    payload += b'\x02\x00' + struct.pack('<I', int(COEFF_0_10M * 100)) 
    payload += b'\x03\x00' + struct.pack('<I', int(COEFF_10_26M * 100)) 
    payload += b'\x04\x00' + struct.pack('<I', int(COEFF_26_40M * 100)) 
    payload += b'\x05\x00' + struct.pack('<I', int(COEFF_40_100M * 100)) 
    
    data_len = len(payload)
    len_bytes = data_len.to_bytes(2, byteorder='little')
    
    return CMD_HEAD + len_bytes + payload + CMD_TAIL 


def apply_ld2417_blind_spot_config(ser):
    """Send enable -> config -> end sequence for LD2417."""
    def _send_and_log(cmd_name, cmd_bytes):
        ser.write(cmd_bytes)
        ser.flush()
        print(f"Sent {cmd_name}: {cmd_bytes.hex(' ')}")
        time.sleep(0.15)

        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting)
            print(f"{cmd_name} response: {response.hex(' ')}")

    try:
        ser.reset_input_buffer()

        print("\n⚙️  Applying LD2417 Radar Configuration...")
        _send_and_log("ENABLE_CONF", ENABLE_CONF)
        _send_and_log("PARAM_CONFIG", build_config_payload())
        _send_and_log("END_CONF", END_CONF)
        print("✅ Configuration sequence complete.\n")

        if ser.in_waiting == 0:
            print("No immediate response after config sequence (this can be normal).")
    except Exception as e:
        print(f"Failed to send LD2417 config frame: {e}")


def parse_radar_data(buffer):
    """
    Parse 8-byte reporting data frames (AA AA ... 55 55) and extract target information.
    """
    header_idx = buffer.find(REPORT_HEADER)
    
    if header_idx == -1:
        return buffer  # No header found, wait for more data

    # Discard anything before the header
    buffer = buffer[header_idx:]

    # Minimum frame size with 0 targets: Header(2) + Count(1) + Tail(2) = 5 bytes
    if len(buffer) < 5:
        return buffer

    target_count = buffer[2]
    # Expected length: Header(2) + Count(1) + Targets(N*8) + Tail(2)
    expected_length = 3 + (target_count * 8) + 2 

    if len(buffer) < expected_length:
        return buffer  # Incomplete frame, wait for more data

    tail_idx = expected_length - 2
    if buffer[tail_idx:tail_idx+2] != REPORT_TAIL:
        # Corrupted frame: resync to next possible header if available.
        next_header = buffer.find(REPORT_HEADER, 2)
        if next_header != -1:
            return buffer[next_header:]
        return b''

    # Extract the payload containing the 8-byte target blocks
    payload = buffer[3:tail_idx]
    
    global left_streak, right_streak
    global confirmed_left_target, confirmed_right_target
    global last_confirmed_left_ts, last_confirmed_right_ts

    closest_left = None
    closest_right = None

    if target_count > 0:
        print(f"\nFrame Detected! Targets: {target_count}")
        print(f"Received Bytes: {buffer[:expected_length].hex(' ')}")
        print("-" * 50)

    for i in range(target_count):
        target_data = payload[i*8 : (i+1)*8]
        if len(target_data) < 8:
            continue

        t_id = target_data[0]
        t_dir = target_data[1]
        
        # Distance is unsigned. Speed field may be signed on some firmware,
        # so decode speed as signed int16 and use magnitude.
        raw_dist = struct.unpack('<H', target_data[2:4])[0]
        raw_speed_signed = struct.unpack('<h', target_data[4:6])[0]
        
        distance_m = raw_dist / 100.0
        speed_kmh = abs(raw_speed_signed) / 100.0

        # Suppress far, very-slow clutter reflections.
        if distance_m >= CLUTTER_DIST_THRESH_M and speed_kmh < MIN_VALID_SPEED_KMH:
            print(f"  Target {t_id}: Ignored (far/slow clutter)")
            continue

        is_left = (t_dir & 0x01) != 0
        is_right = (t_dir & 0x02) != 0

        if is_left and is_right:
            dir_str = "BOTH (LEFT+RIGHT)"
        elif is_left:
            dir_str = "LEFT"
        elif is_right:
            dir_str = "RIGHT"
        else:
            dir_str = f"Unknown({t_dir})"

        print(f"  Target {t_id}: {dir_str:17} | Dist={distance_m:6.2f} m | Speed={speed_kmh:6.2f} km/h")

        # Track closest target per side; supports combined left+right flags.
        if is_left:
            if closest_left is None or distance_m < closest_left[0]:
                closest_left = (distance_m, speed_kmh)

        if is_right:
            if closest_right is None or distance_m < closest_right[0]:
                closest_right = (distance_m, speed_kmh)
                
    now_ts = time.time()

    # Require short confirmation to suppress one-frame ghost detections.
    if closest_left is not None:
        left_streak += 1
        if left_streak >= CONFIRM_FRAMES:
            confirmed_left_target = closest_left
            last_confirmed_left_ts = now_ts
    else:
        left_streak = 0

    if closest_right is not None:
        right_streak += 1
        if right_streak >= CONFIRM_FRAMES:
            confirmed_right_target = closest_right
            last_confirmed_right_ts = now_ts
    else:
        right_streak = 0

    # Hold last confirmed side briefly to avoid flicker during track merge/swap.
    left_output = None
    right_output = None
    if confirmed_left_target is not None and (now_ts - last_confirmed_left_ts) <= SIDE_HOLD_SEC:
        left_output = confirmed_left_target
    if confirmed_right_target is not None and (now_ts - last_confirmed_right_ts) <= SIDE_HOLD_SEC:
        right_output = confirmed_right_target

    # Publish only LD2417-owned segment (LEDs 4-7) via shared arbiter.
    led_controller.update_ld2417(left_output, right_output, source='ld2417')
    
    # Log active sides for debugging
    if target_count > 0 and (left_output is not None or right_output is not None):
        active_sides = []
        if left_output is not None:
            active_sides.append("LEFT")
        if right_output is not None:
            active_sides.append("RIGHT")
        print(f"  >>> LED Activation: {' & '.join(active_sides)}")

    # Return the remaining buffer for the next cycle
    return buffer[expected_length:]


def read_radar_stream(port, baud_rate=115200, duration=None):
    """Connect to the port and continuously parse data."""
    
    # --- MOVED HERE: Always display settings when the stream starts ---
    display_radar_settings()
    
    print(f"\nConnecting to {port} at {baud_rate} baud...")
    try:
        ser = serial.Serial(port, baud_rate, timeout=0.1)
        print(f"Connected to {port}. Listening for data...\n")

        apply_ld2417_blind_spot_config(ser)

        buffer = b''
        start_time = time.time()

        while True:
            if duration is not None and (time.time() - start_time) >= duration:
                break

            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                buffer += data
                
                # Keep parsing as long as the buffer contains complete frames
                while REPORT_HEADER in buffer:
                    old_len = len(buffer)
                    buffer = parse_radar_data(buffer)
                    if len(buffer) == old_len:
                        break  # Prevent infinite loop if waiting for partial frame

            time.sleep(READ_DELAY_SEC)

    except serial.SerialException as e:
        print(f"Error: {e}")
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        print("\nReleasing hardware resources...")
        # ONLY turn off this specific radar's LEDs, do not kill the mixer
        led_controller.off(source='ld2417')
            
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Port closed.")


def main():
    print("=" * 50)
    print("ARAS Blind Spot Monitoring Module")
    print("=" * 50)

    list_available_ports()
    print(f"\nUsing fixed radar port: {RADAR_PORT} @ {BAUD_RATE} baud")
    print("Press Ctrl+C to stop.\n")

    read_radar_stream(RADAR_PORT, baud_rate=BAUD_RATE, duration=None)


if __name__ == "__main__":
    main()