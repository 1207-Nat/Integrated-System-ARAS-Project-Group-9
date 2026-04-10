import L76Xmodified as L76X
import time
import subprocess
import sys
import tkinter as tk
from tkinter import scrolledtext, filedialog
import threading
import webbrowser
import tkintermapview

class GPSGui:
    def __init__(self, root):
        self.root = root
        self.root.title("LC76G Live Map Dashboard - Pi 5")
        self.root.geometry("1100x850") # Expanded width for the map
        self.root.configure(bg="#2c3e50")

        # --- STATE VARIABLES ---
        self.is_frozen = False
        self.maps_url = ""
        self.last_lat, self.last_lon = 0.0, 0.0
        self.last_time = time.time()
        self.total_distance = 0.0  # Odometer in meters
        self.path_coords = []      # Stores coordinates for the map trail

        # --- LAYOUT FRAMES ---
        self.left_frame = tk.Frame(root, bg="#2c3e50", width=450)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)
        
        self.right_frame = tk.Frame(root, bg="#2c3e50")
        self.right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # --- UI STYLES ---
        lbl_style = {"bg": "#2c3e50", "fg": "#ecf0f1", "font": ("Arial", 12)}
        val_style = {"bg": "#2c3e50", "fg": "#f1c40f", "font": ("Arial", 14, "bold")}
        odo_style = {"bg": "#2c3e50", "fg": "#3498db", "font": ("Arial", 16, "bold")}

        # --- LEFT FRAME: HEADER DISPLAY ---
        self.status_label = tk.Label(self.left_frame, text="STATUS: INITIALIZING", **val_style)
        self.status_label.pack(pady=10)

        # Speed/Odometer Displays
        self.mod_speed_val = tk.Label(self.left_frame, text="Module: 0.00 km/h", **val_style)
        self.mod_speed_val.pack()
        
        self.calc_speed_val = tk.Label(self.left_frame, text="Calc: 0.00 km/h", **lbl_style)
        self.calc_speed_val.pack()

        # Odometer Label
        tk.Label(self.left_frame, text="TOTAL DISTANCE (ODOMETER):", **lbl_style).pack(pady=(10,0))
        self.odo_val = tk.Label(self.left_frame, text="0.00 meters", **odo_style)
        self.odo_val.pack()

        self.coord_label = tk.Label(self.left_frame, text="Waiting for fix...", **lbl_style)
        self.coord_label.pack(pady=10)

        # --- LEFT FRAME: ACTION BUTTONS ---
        btn_frame = tk.Frame(self.left_frame, bg="#2c3e50")
        btn_frame.pack(pady=10)

        self.btn_maps = tk.Button(btn_frame, text="Google Maps", command=self.open_maps, 
                                  bg="#27ae60", fg="white", width=12, state="disabled")
        self.btn_maps.grid(row=0, column=0, padx=5)

        self.btn_freeze = tk.Button(btn_frame, text="Freeze Log", command=self.toggle_freeze, 
                                    bg="#2980b9", fg="white", width=12)
        self.btn_freeze.grid(row=0, column=1, padx=5)

        self.btn_save = tk.Button(btn_frame, text="Save Log", command=self.save_log, 
                                  bg="#8e44ad", fg="white", width=12)
        self.btn_save.grid(row=0, column=2, padx=5)

        # --- LEFT FRAME: DEBUG CONSOLE ---
        self.console = scrolledtext.ScrolledText(self.left_frame, width=50, height=20, bg="#1e1e1e", fg="#00ff00", font=("Courier", 10))
        self.console.pack(padx=10, pady=10)

        # --- RIGHT FRAME: LIVE INTERACTIVE MAP ---
        self.map_widget = tkintermapview.TkinterMapView(self.right_frame, corner_radius=10)
        self.map_widget.pack(fill="both", expand=True)
        # Use Google Maps standard tile server
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        # Set a default position (e.g., Malaysia) before fix
        self.map_widget.set_position(2.945, 101.876) 
        self.map_widget.set_zoom(15)
        self.marker = None
        self.path = None

        # Start GPS Thread
        self.thread = threading.Thread(target=self.gps_loop, daemon=True)
        self.thread.start()

    def log(self, message):
        print(message)
        if not self.is_frozen:
            # Safely insert text to GUI from the background thread
            self.root.after(0, self._insert_log, f"[{time.strftime('%H:%M:%S')}] {message}\n")

    def _insert_log(self, text):
        self.console.insert(tk.END, text)
        self.console.see(tk.END)

    def toggle_freeze(self):
        self.is_frozen = not self.is_frozen
        self.btn_freeze.config(text="Unfreeze Log" if self.is_frozen else "Freeze Log", 
                               bg="#e67e22" if self.is_frozen else "#2980b9")

    def save_log(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".txt")
        if file_path:
            with open(file_path, "w") as f:
                f.write(self.console.get("1.0", tk.END))

    def open_maps(self):
        if self.maps_url: webbrowser.open(self.maps_url)

    def check_wifi_time_sync(self):
        """Checks and forces NTP sync for accurate Pi timestamps and faster logging."""
        self.log("Checking WiFi/Network time synchronization...")
        try:
            result = subprocess.run(['timedatectl', 'show', '--property=NTPSynchronized'], 
                                   capture_output=True, text=True)
            if "NTPSynchronized=yes" in result.stdout:
                self.log("Time is synchronized via Network.")
            else:
                self.log("Time NOT synced. Forcing NTP update...")
                subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'])
                time.sleep(3) # Give network time to latch
        except Exception as e:
            self.log(f"Could not verify network time: {e}")

    def gps_loop(self):
        try:
            # 1. Sync Time First (Runs in background thread so GUI doesn't freeze!)
            self.check_wifi_time_sync()

            self.log("Initializing LC76G Hardware...")
            self.x = L76X.L76X()
            self.x.L76X_Set_Baudrate(115200)
            
            # 2. Configuration Commands (No '*' checksums here, L76X_Send_Command handles it)
            commands = [
                '$PAIR038,0',            # Disable static threshold
                '$PAIR002,1000',         # 1Hz Output Rate
                '$PAIR062,0,1',          # Enable GGA (Coordinates & Sats)
                '$PAIR062,4,1',          # Enable RMC (Status & Speed)
                '$PAIR062,5,1',          # Enable VTG (Vector Speed)
                '$PAIR406,1',            # Enable EASY (A-GNSS Internal Prediction)
                '$PAIR066,1,1,1,1,1,0'   # Enable all constellations
            ]
            
            self.log("Applying PAIR configuration and A-GNSS...")
            for cmd in commands:
                self.x.L76X_Send_Command(cmd)
                time.sleep(0.1) 
            
            self.x.L76X_Exit_BackupMode()
            self.log("--- Ready. Waiting for RMC sentences ---")

            while True:
                self.x.L76X_Gat_GNRMC()
                now = time.time()
                
                calc_speed = 0.0
                if self.x.Status == 1 and self.last_lat != 0:
                    # Calculate step distance in meters
                    step_dist = self.x.get_distance(self.last_lat, self.last_lon, self.x.Lat, self.x.Lon)
                    self.total_distance += step_dist
                    
                    time_delta = now - self.last_time
                    if time_delta > 0:
                        calc_speed = (step_dist / time_delta) * 3.6

                # --- UPDATE GUI (Thread Safe using .after) ---
                status_str = "FIXED" if self.x.Status == 1 else "SEARCHING"
                
                def update_ui():
                    self.status_label.config(text=f"STATUS: {status_str} | Sats: {self.x.Satellites}")
                    self.mod_speed_val.config(text=f"Module: {self.x.Speed_kmh:.2f} km/h")
                    self.calc_speed_val.config(text=f"Calc: {calc_speed:.2f} km/h")
                    
                    if self.total_distance < 1000:
                        self.odo_val.config(text=f"{self.total_distance:.2f} meters")
                    else:
                        self.odo_val.config(text=f"{self.total_distance/1000.0:.3f} km")

                    if self.x.Lat != 0:
                        # Update text labels
                        self.coord_label.config(text=f"Lat: {self.x.Lat:.7f} | Lon: {self.x.Lon:.7f}")
                        self.maps_url = f"http://maps.google.com/?q={self.x.Lat:.8f},{self.x.Lon:.8f}"
                        self.btn_maps.config(state="normal")
                        
                        # --- MAP WIDGET UPDATES ---
                        # 1. Update the marker
                        if self.marker is None:
                            self.marker = self.map_widget.set_marker(self.x.Lat, self.x.Lon, text="You")
                            self.map_widget.set_position(self.x.Lat, self.x.Lon) # Center map on first fix
                        else:
                            self.marker.set_position(self.x.Lat, self.x.Lon)
                            
                        # 2. Draw the path
                        self.path_coords.append((self.x.Lat, self.x.Lon))
                        if self.path is None and len(self.path_coords) > 1:
                            self.path = self.map_widget.set_path(self.path_coords, color="red", width=3)
                        elif self.path is not None:
                            self.path.set_position_list(self.path_coords)
                            
                        # 3. Auto-center the map as you drive
                        self.map_widget.set_position(self.x.Lat, self.x.Lon)
                
                self.root.after(0, update_ui)

                if self.x.Lat != 0:
                    self.log(f"Fix: {self.x.Lat:.5f}, {self.x.Lon:.5f} | ModSpd: {self.x.Speed_kmh:.1f}")

                self.last_lat, self.last_lon, self.last_time = self.x.Lat, self.x.Lon, now
                time.sleep(1)

        except Exception as e:
            self.log(f"Error: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = GPSGui(root)
    root.mainloop()