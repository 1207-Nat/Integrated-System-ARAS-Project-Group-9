import tkinter as tk
from tkinter import ttk
import L76X  # Ensure your library file is named L76X.py
import time
import threading

# --- GUI Setup ---
root = tk.Tk()
root.title("GPS Dashboard - ARAS Project")
root.geometry("600x480")

# Variables for GUI Labels
var_status = tk.StringVar(value="Initializing...")
var_time = tk.StringVar(value="--:--:--")
var_sats = tk.StringVar(value="0")
var_speed = tk.StringVar(value="0.00 km/h")
var_google = tk.StringVar(value="Waiting for fix...")
var_baidu = tk.StringVar(value="Waiting for fix...")

# --- GPS Logic ---
gps = L76X.L76X()

def init_gps():
    """
    Initialisation sequence specifically for your L76X module.
    """
    print("[GPS] Starting Initialization Sequence...")
    gps.L76X_Set_Baudrate(115200)
    gps.L76X_Send_Command(gps.SET_POS_FIX_400MS)
    gps.L76X_Send_Command(gps.SET_NMEA_OUTPUT)
    gps.L76X_Exit_BackupMode()
    print("[GPS] Initialization Complete. Waiting for Satellites...")

def update_loop():
    while True:
        # Read data from the module
        gps.L76X_Gat_GNRMC()
        
        # --- 1. Coordinate Calculation ---
        # We pass the current Lat/Lon to the library function as required
        gps.L76X_Google_Coordinates(gps.Lat, gps.Lon)
        gps.L76X_Baidu_Coordinates(gps.Lat, gps.Lon)
        
        # --- 2. Drift Filter (Ghost Speed Fix) ---
        # If speed is less than 2 km/h, display 0.0
        if gps.Speed_kmh < 2.0:
            display_speed = 0.0
        else:
            display_speed = gps.Speed_kmh

        # --- 3. Format Data for Display ---
        time_str = f"{gps.Time_H:02}:{gps.Time_M:02}:{int(gps.Time_S):02}"
        
        # Use the coordinates calculated by the library
        # Note: These will use the China-offset (GCJ-02) as requested.
        google_link = f"http://maps.google.com/?q={gps.Lat_Google:.7f},{gps.Lon_Google:.7f}"
        baidu_link = f"http://api.map.baidu.com/marker?location={gps.Lat_Baidu},{gps.Lon_Baidu}&output=html"
        
        # --- 4. Update GUI & Terminal ---
        if gps.Status == 1:
            # Console Output
            print("\n" + "="*50)
            print(f" [STATUS] Connected | Sats: {gps.Satellites}")
            print(f" [SPEED]  {display_speed:.2f} km/h")
            print(f" [GOOGLE] {gps.Lat_Google:.7f}, {gps.Lon_Google:.7f}")
            print(f" [BAIDU]  {gps.Lat_Baidu:.7f}, {gps.Lon_Baidu:.7f}")
            print("="*50)
            
            # GUI Output
            var_status.set("CONNECTED")
            var_time.set(time_str)
            var_sats.set(str(gps.Satellites))
            var_speed.set(f"{display_speed:.2f} km/h") # Using filtered speed
            var_google.set(f"{gps.Lat_Google:.7f}, {gps.Lon_Google:.7f}\n{google_link}")
            var_baidu.set(f"{gps.Lat_Baidu:.7f}, {gps.Lon_Baidu:.7f}\n{baidu_link}")
        else:
            # If no satellite fix yet
            print(f"Searching... Sats: {gps.Satellites}")
            var_status.set("SEARCHING...")
            var_sats.set(str(gps.Satellites))

        # Don't overload the CPU
        time.sleep(0.5)

# --- Start GPS Threads ---
# Thread 1: Initialize the GPS hardware
t1 = threading.Thread(target=init_gps)
t1.daemon = True 
t1.start()

# Thread 2: Start the update loop slightly later to allow init to finish
def start_update_loop():
    time.sleep(1) # Wait 1 sec for init to send commands
    update_loop()

t2 = threading.Thread(target=start_update_loop)
t2.daemon = True
t2.start()

# --- GUI Layout ---
style = ttk.Style()
style.configure("Bold.TLabel", font=("Arial", 12, "bold"))

frame = ttk.Frame(root, padding="20")
frame.pack(fill=tk.BOTH, expand=True)

# Status & Time
ttk.Label(frame, text="Status:", style="Bold.TLabel").grid(row=0, column=0, sticky=tk.W)
ttk.Label(frame, textvariable=var_status).grid(row=0, column=1, sticky=tk.W)

ttk.Label(frame, text="Time:", style="Bold.TLabel").grid(row=1, column=0, sticky=tk.W)
ttk.Label(frame, textvariable=var_time).grid(row=1, column=1, sticky=tk.W)

ttk.Separator(frame, orient='horizontal').grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

# Satellites & Speed
ttk.Label(frame, text="Satellites:", style="Bold.TLabel").grid(row=3, column=0, sticky=tk.W)
ttk.Label(frame, textvariable=var_sats, font=("Arial", 14)).grid(row=3, column=1, sticky=tk.W)

ttk.Label(frame, text="Speed:", style="Bold.TLabel").grid(row=4, column=0, sticky=tk.W)
ttk.Label(frame, textvariable=var_speed, foreground="blue", font=("Arial", 14, "bold")).grid(row=4, column=1, sticky=tk.W)

ttk.Separator(frame, orient='horizontal').grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)

# Coordinates
ttk.Label(frame, text="Google Maps:", style="Bold.TLabel").grid(row=6, column=0, sticky=tk.NW)
ttk.Label(frame, textvariable=var_google, wraplength=400, justify="left").grid(row=6, column=1, sticky=tk.W)

ttk.Label(frame, text="Baidu Maps:", style="Bold.TLabel").grid(row=7, column=0, sticky=tk.NW, pady=(10,0))
ttk.Label(frame, textvariable=var_baidu, wraplength=400, justify="left").grid(row=7, column=1, sticky=tk.W, pady=(10,0))

# Start GUI
root.mainloop()