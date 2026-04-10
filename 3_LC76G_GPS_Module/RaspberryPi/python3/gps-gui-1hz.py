import L76Xmodified as L76X
import time
import subprocess
import sys
import tkinter as tk
from tkinter import scrolledtext, filedialog
import threading
import webbrowser
import tkintermapview
import requests

class GPSGui:
    def __init__(self, root):
        self.root = root
        self.root.title("LC76G Live Map Dashboard - Pi 5")
        self.root.geometry("1100x850")
        self.root.configure(bg="#2c3e50")

        # --- STATE VARIABLES ---
        self.is_frozen = False
        self.running = True  # Control flag for background threads
        self.maps_url = ""
        self.last_lat, self.last_lon = 0.0, 0.0
        self.last_time = time.time()
        self.total_distance = 0.0
        self.path_coords = []
        
        # Speed Limit Variables
        self.current_speed_limit = "Not Available"
        self.last_api_check = 0

        # --- LAYOUT FRAMES ---
        self.left_frame = tk.Frame(root, bg="#2c3e50", width=450)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)
        
        self.right_frame = tk.Frame(root, bg="#2c3e50")
        self.right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # --- UI STYLES ---
        lbl_style = {"bg": "#2c3e50", "fg": "#ecf0f1", "font": ("Arial", 12)}
        val_style = {"bg": "#2c3e50", "fg": "#f1c40f", "font": ("Arial", 14, "bold")}
        limit_style = {"bg": "#c0392b", "fg": "white", "font": ("Arial", 18, "bold")}
        odo_style = {"bg": "#2c3e50", "fg": "#3498db", "font": ("Arial", 16, "bold")}

        # --- LEFT FRAME: DISPLAY STATS ---
        self.status_label = tk.Label(self.left_frame, text="STATUS: INITIALIZING", **val_style)
        self.status_label.pack(pady=10)

        self.limit_val = tk.Label(self.left_frame, text="LIMIT: Not Available", **limit_style)
        self.limit_val.pack(pady=10, ipadx=10, ipady=5)

        self.mod_speed_val = tk.Label(self.left_frame, text="Module: 0.00 km/h", **val_style)
        self.mod_speed_val.pack()
        
        self.calc_speed_val = tk.Label(self.left_frame, text="Calc: 0.00 km/h", **lbl_style)
        self.calc_speed_val.pack()

        tk.Label(self.left_frame, text="TOTAL DISTANCE (ODOMETER):", **lbl_style).pack(pady=(10,0))
        self.odo_val = tk.Label(self.left_frame, text="0.00 meters", **odo_style)
        self.odo_val.pack()

        self.coord_label = tk.Label(self.left_frame, text="Waiting for fix...", **lbl_style)
        self.coord_label.pack(pady=10)

        # Buttons
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

        # ADDED: Stop / Quit Button
        self.btn_quit = tk.Button(btn_frame, text="Quit / Stop Program", command=self.quit_app, 
                                  bg="#c0392b", fg="white", font=("Arial", 10, "bold"))
        self.btn_quit.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky="we")

        # Console
        self.console = scrolledtext.ScrolledText(self.left_frame, width=50, height=18, bg="#1e1e1e", fg="#00ff00", font=("Courier", 10))
        self.console.pack(padx=10, pady=10)

        # --- RIGHT FRAME: LIVE INTERACTIVE MAP ---
        self.map_widget = tkintermapview.TkinterMapView(self.right_frame, corner_radius=10)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.map_widget.set_position(2.945, 101.876) 
        self.map_widget.set_zoom(15)
        self.marker = None
        self.path = None

        # Start GPS Thread
        self.thread = threading.Thread(target=self.gps_loop, daemon=True)
        self.thread.start()

    def log(self, message):
        print(message)
        if not self.is_frozen and self.running:
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
                
    def quit_app(self):
        """Cleanly shuts down the threads, closes the serial port, and exits."""
        self.log("Initiating shutdown sequence...")
        self.running = False  # Stops the while loop in gps_loop
        
        # Stop the GUI event loop
        self.root.quit()
        self.root.destroy()
        
        # Force terminate the Python process
        sys.exit(0)

    def open_maps(self):
        if self.maps_url: webbrowser.open(self.maps_url)

    def fetch_speed_limit(self, lat, lon):
        query = f"""
        [out:json];
        way(around:30, {lat}, {lon})["maxspeed"];
        out tags;
        """
        url = "http://overpass-api.de/api/interpreter"
        try:
            response = requests.get(url, params={'data': query}, timeout=5)
            data = response.json()
            if data.get('elements'):
                limit = data['elements'][0]['tags'].get('maxspeed', 'Not Available')
                if limit.isdigit():
                    self.current_speed_limit = f"{limit} km/h"
                else:
                    self.current_speed_limit = limit
                self.log(f"API Update: Road speed limit is {self.current_speed_limit}")
            else:
                self.current_speed_limit = "Not Available"
        except Exception as e:
            self.current_speed_limit = "Not Available"
            self.log(f"API Error: Failed to fetch speed limit.")

    def check_wifi_time_sync(self):
        self.log("Syncing Network Time...")
        try:
            subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'])
            time.sleep(2) 
        except:
            pass

    def gps_loop(self):
        try:
            self.check_wifi_time_sync()

            self.log("Initializing LC76G Hardware...")
            self.x = L76X.L76X()
            self.x.L76X_Set_Baudrate(115200)
            
            commands = [
                '$PAIR038,1',            
                '$PAIR002,100',          
                '$PAIR062,0,1',          
                '$PAIR062,4,1',          
                '$PAIR062,5,1',          
                '$PAIR406,1',            
                '$PAIR066,1,1,0,0,0,0'   
            ]
            
            for cmd in commands:
                self.x.L76X_Send_Command(cmd)
                time.sleep(0.1) 
            
            self.x.L76X_Exit_BackupMode()
            self.log("--- Ready. Waiting for RMC sentences ---")

            # CHANGED: Now checks self.running instead of a permanent True loop
            while self.running:
                self.x.L76X_Gat_GNRMC()
                now = time.time()
                
                calc_speed = 0.0
                display_mod_speed = 0.0

                if self.x.Status == 1:
                    time_delta = now - self.last_time
                    
                    if self.x.Speed_kmh > 3.0:
                        display_mod_speed = self.x.Speed_kmh
                    
                    if display_mod_speed > 0 and time_delta > 0:
                        step_dist = (display_mod_speed / 3.6) * time_delta
                        self.total_distance += step_dist

                    if self.last_lat != 0 and time_delta > 0:
                        haversine_dist = self.x.get_distance(self.last_lat, self.last_lon, self.x.Lat, self.x.Lon)
                        calc_speed = (haversine_dist / time_delta) * 3.6
                        if calc_speed < 3.0:
                            calc_speed = 0.0

                if self.x.Status == 1 and (display_mod_speed > 5.0) and (now - self.last_api_check) > 15:
                    self.last_api_check = now
                    threading.Thread(target=self.fetch_speed_limit, args=(self.x.Lat, self.x.Lon), daemon=True).start()

                status_str = "FIXED" if self.x.Status == 1 else "SEARCHING"
                
                def update_ui():
                    # Only update UI if we haven't initiated a shutdown
                    if not self.running: return 
                    
                    self.status_label.config(text=f"STATUS: {status_str} | Sats: {self.x.Satellites}")
                    self.mod_speed_val.config(text=f"Module: {display_mod_speed:.1f} km/h")
                    self.calc_speed_val.config(text=f"Calc: {calc_speed:.1f} km/h")
                    self.limit_val.config(text=f"LIMIT: {self.current_speed_limit}")
                    
                    if self.total_distance < 1000:
                        self.odo_val.config(text=f"{self.total_distance:.1f} meters")
                    else:
                        self.odo_val.config(text=f"{self.total_distance/1000.0:.3f} km")

                    if self.x.Lat != 0:
                        self.coord_label.config(text=f"Lat: {self.x.Lat:.6f} | Lon: {self.x.Lon:.6f}")
                        self.maps_url = f"http://maps.google.com/?q={self.x.Lat:.8f},{self.x.Lon:.8f}"
                        self.btn_maps.config(state="normal")
                        
                        if self.marker is None:
                            self.marker = self.map_widget.set_marker(self.x.Lat, self.x.Lon, text="You")
                            self.map_widget.set_position(self.x.Lat, self.x.Lon)
                        else:
                            self.marker.set_position(self.x.Lat, self.x.Lon)
                            
                        if display_mod_speed > 0:
                            self.path_coords.append((self.x.Lat, self.x.Lon))
                            if self.path is None and len(self.path_coords) > 1:
                                self.path = self.map_widget.set_path(self.path_coords, color="red", width=3)
                            elif self.path is not None:
                                self.path.set_position_list(self.path_coords)
                            
                        self.map_widget.set_position(self.x.Lat, self.x.Lon)
                
                self.root.after(0, update_ui)

                self.last_lat, self.last_lon, self.last_time = self.x.Lat, self.x.Lon, now
                time.sleep(0.1)

        except Exception as e:
            if self.running:  # Don't print errors if we are intentionally shutting down
                self.log(f"Error: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    
    # Handle the 'X' button on the window natively
    app = GPSGui(root)
    root.protocol("WM_DELETE_WINDOW", app.quit_app)
    
    root.mainloop()