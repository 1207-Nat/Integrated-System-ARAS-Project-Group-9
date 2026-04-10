import tkinter as tk
from tkinter import ttk
import L76Xmodified as L76X
import time
import threading

# --- GUI Setup ---
root = tk.Tk()
root.title("GPS Dashboard - ARAS Project")
root.geometry("600x450")

# Variables for GUI Labels
var_status = tk.StringVar(value="Initializing...")
var_time = tk.StringVar(value="--:--:--")
var_sats = tk.StringVar(value="0")
var_speed = tk.StringVar(value="0.0 km/h")
var_google = tk.StringVar(value="Waiting for fix...")
var_baidu = tk.StringVar(value="Waiting for fix...")

# --- GPS Logic ---
gps = L76X.L76X()

def init_gps():
    gps.L76X_Set_Baudrate(115200)
    gps.L76X_Send_Command(gps.SET_POS_FIX_400MS)
    gps.L76X_Send_Command(gps.SET_NMEA_OUTPUT)
    gps.L76X_Exit_BackupMode()

def update_loop():
    while True:
        gps.L76X_Gat_GNRMC()
        
        # Calculate Coordinates
        gps.L76X_Google_Coordinates()
        
        # Formatted Data
        time_str = f"{gps.Time_H:02}:{gps.Time_M:02}:{int(gps.Time_S):02}"
        google_link = f"https://www.google.com/maps?q=2.952750,101.882833{gps.Lat_Google:.7f},{gps.Lon_Google:.7f}"
        baidu_link = f"http://api.map.baidu.com/marker?location={gps.Lat_Baidu},{gps.Lon_Baidu}&output=html"
        
        # --- 1. Terminal Output ---
        if gps.Status == 1:
            print("\n" + "="*50)
            print(f" [STATUS] Connected | Sats: {gps.Satellites}")
            print(f" [SPEED]  {gps.Speed_kmh:.2f} km/h")
            print(f" [GOOGLE] {gps.Lat_Google:.7f}, {gps.Lon_Google:.7f}")
            print(f"          {google_link}")
            print(f" [BAIDU]  {gps.Lat_Baidu:.7f}, {gps.Lon_Baidu:.7f}")
            print(f"          {baidu_link}")
            print("="*50)
            
            # --- 2. Update GUI ---
            var_status.set("CONNECTED")
            var_time.set(time_str)
            var_sats.set(str(gps.Satellites))
            var_speed.set(f"{gps.Speed_kmh:.2f} km/h")
            var_google.set(f"{gps.Lat_Google:.7f}, {gps.Lon_Google:.7f}\n{google_link}")
            var_baidu.set(f"{gps.Lat_Baidu:.7f}, {gps.Lon_Baidu:.7f}\n{baidu_link}")
        else:
            print(f"Searching... Sats: {gps.Satellites}")
            var_status.set("SEARCHING...")
            var_sats.set(str(gps.Satellites))

        # Don't overload the CPU
        time.sleep(0.5)

# --- Start GPS Thread ---
# We run GPS in a separate thread so the GUI doesn't freeze
t = threading.Thread(target=init_gps)
t.start()
t2 = threading.Thread(target=update_loop)
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