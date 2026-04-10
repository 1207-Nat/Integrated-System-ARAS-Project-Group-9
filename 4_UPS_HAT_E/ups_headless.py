import smbus
import time
import os
import json
import csv
import sys
from datetime import datetime

try:
    import matplotlib.pyplot as plt
    CAN_PLOT = True
except ImportError:
    CAN_PLOT = False

ADDR = 0x2d
LOW_VOL = 3150 # mV

# --- FOLDER STRUCTURE ---
BASE_DIR = "/home/group9/4_UPS_HAT_E"
RECORDS_DIR = os.path.join(BASE_DIR, "UPS_Records")
RECORD_FLAG = os.path.join(BASE_DIR, ".ups_record_flag")
os.makedirs(RECORDS_DIR, exist_ok=True)

bus = smbus.SMBus(1)
low = 0

# Recording State Variables
is_recording = False
session_dir = ""
csv_path = ""
plot_path = ""
csv_file = None
csv_writer = None
start_time_dt = None

time_history = []
power_history = []
start_time_sec = 0

# Energy Tracking
session_used_wh = 0.0
last_eval_time = time.time()

print("UPS Headless Interface Started.")

try:
    while True:
        now = time.time()
        time_delta_hours = (now - last_eval_time) / 3600.0
        last_eval_time = now

        try:
            # Status
            data_status = bus.read_i2c_block_data(ADDR, 0x02, 0x01)
            if (data_status[0] & 0x40): state = "Fast Charging"
            elif (data_status[0] & 0x80): state = "Charging"
            elif (data_status[0] & 0x20): state = "Discharging"
            else: state = "Idle"
            
            # VBUS
            data_vbus = bus.read_i2c_block_data(ADDR, 0x10, 0x06)
            vbus_v = (data_vbus[0] | data_vbus[1] << 8)
            vbus_c = (data_vbus[2] | data_vbus[3] << 8)
            vbus_p = (data_vbus[4] | data_vbus[5] << 8)
            
            # Battery
            data_bat = bus.read_i2c_block_data(ADDR, 0x20, 0x0C)
            bat_v = (data_bat[0] | data_bat[1] << 8)
            current = (data_bat[2] | data_bat[3] << 8)
            if current > 0x7FFF: current -= 0xFFFF
            bat_pct = int(data_bat[4] | data_bat[5] << 8)
            bat_cap = (data_bat[6] | data_bat[7] << 8)
            
            # Power Calculation (Negative = Discharging, Positive = Charging)
            bat_power_w = (current * bat_v) / 1_000_000.0
            
            if current < 0:
                time_rem = f"Empty in {data_bat[8] | data_bat[9] << 8} min"
            else:
                time_rem = f"Full in {data_bat[10] | data_bat[11] << 8} min"
                
            # Cells
            data_cell = bus.read_i2c_block_data(ADDR, 0x30, 0x08)
            V1 = (data_cell[0] | data_cell[1] << 8)
            V2 = (data_cell[2] | data_cell[3] << 8)
            V3 = (data_cell[4] | data_cell[5] << 8)
            V4 = (data_cell[6] | data_cell[7] << 8)
            
            # --- Low Voltage Protection ---
            if ((V1 < LOW_VOL) or (V2 < LOW_VOL) or (V3 < LOW_VOL) or (V4 < LOW_VOL)) and (current < 50):
                low += 1
                if low >= 30:
                    print("__LOG__:System shutdown due to low battery!")
                    address = os.popen("i2cdetect -y -r 1 0x2d 0x2d | egrep '2d' | awk '{print $2}'").read()
                    if address == '2d\n':
                        os.popen("i2cset -y 1 0x2d 0x01 0x55")
                    os.system("sudo poweroff")
            else:
                low = 0
                
            # --- Handle Recording & Wh Accumulation ---
            gui_wants_record = os.path.exists(RECORD_FLAG)
            
            if gui_wants_record:
                if not is_recording:
                    # Initialize new session subfolder
                    start_time_dt = datetime.now()
                    timestamp = start_time_dt.strftime("%Y%m%d_%H%M%S")
                    session_dir = os.path.join(RECORDS_DIR, f"Session_{timestamp}")
                    os.makedirs(session_dir, exist_ok=True)
                    
                    csv_path = os.path.join(session_dir, "power_log.csv")
                    plot_path = os.path.join(session_dir, "power_graph.png")
                    
                    csv_file = open(csv_path, mode='w', newline='')
                    csv_writer = csv.writer(csv_file)
                    csv_writer.writerow(["Elapsed Time (s)", "State", "Voltage (mV)", "Current (mA)", "Power (W)", "Used Energy (Wh)"])
                    
                    time_history = []
                    power_history = []
                    session_used_wh = 0.0 # Reset session energy tracker
                    start_time_sec = now
                    is_recording = True
                    print(f"__LOG__:Started logging UPS session to {session_dir}/")
                
                # Accumulate Used Wh (Only count discharging power)
                if bat_power_w < 0:
                    session_used_wh += abs(bat_power_w) * time_delta_hours
                
                elapsed = now - start_time_sec
                csv_writer.writerow([f"{elapsed:.1f}", state, bat_v, current, f"{bat_power_w:.3f}", f"{session_used_wh:.5f}"])
                csv_file.flush()
                time_history.append(elapsed)
                power_history.append(bat_power_w)
                
            elif not gui_wants_record and is_recording:
                # Stop Recording & Generate Dual-Polarity Plot
                if csv_file: csv_file.close()
                is_recording = False
                end_time_dt = datetime.now()
                print("__LOG__:Stopped logging. Generating plot...")
                
                if CAN_PLOT and len(time_history) > 0:
                    plt.figure(figsize=(10, 6))
                    
                    # Fill Positive (Charging) with Green, Negative (Discharging) with Red
                    pos_mask = [p >= 0 for p in power_history]
                    neg_mask = [p < 0 for p in power_history]
                    
                    plt.fill_between(time_history, power_history, 0, where=pos_mask, color='#2ecc71', alpha=0.4, label='Charging (+)')
                    plt.fill_between(time_history, power_history, 0, where=neg_mask, color='#e74c3c', alpha=0.4, label='Discharging (-)')
                    
                    # Draw the main line and the Zero axis
                    plt.plot(time_history, power_history, color='#2c3e50', linewidth=1.5)
                    plt.axhline(0, color='black', linewidth=1, linestyle='--')
                    
                    time_fmt = f"{start_time_dt.strftime('%Y-%m-%d %H:%M:%S')} to {end_time_dt.strftime('%H:%M:%S')}"
                    plt.title(f"UPS System Power Envelope\n({time_fmt}) | Total Used: {session_used_wh:.4f} Wh", fontsize=14, fontweight='bold')
                    plt.xlabel("Elapsed Time (Seconds)", fontsize=11)
                    plt.ylabel("Power (Watts)", fontsize=11)
                    plt.grid(True, linestyle=':', alpha=0.7)
                    plt.legend(loc="upper right")
                    plt.tight_layout()
                    plt.savefig(plot_path, dpi=300)
                    print(f"__LOG__:Plot saved to {plot_path}")

            # --- Package & Send Data to Master GUI ---
            payload = {
                "state": state,
                "bat_power_w": bat_power_w,
                "session_used_wh": session_used_wh,
                "vbus_v": vbus_v, "vbus_p": vbus_p,
                "bat_v": bat_v, "bat_c": current, "bat_pct": bat_pct, "bat_cap": bat_cap,
                "time_rem": time_rem,
                "V1": V1, "V2": V2, "V3": V3, "V4": V4
            }
            print(f"__UPS__:{json.dumps(payload)}")
            
        except Exception as e:
            print(f"__LOG__:I2C Read Error: {e}")
            
        sys.stdout.flush()
        time.sleep(2)
        
finally:
    if is_recording and csv_file:
        csv_file.close()