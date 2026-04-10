import time
import json
import sys
import threading
import requests
import subprocess
import os
from datetime import datetime
import reverse_geocoder as rg

# Headless plotting setup
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import L76Xmodified as L76X

class HeadlessGPS:
    def __init__(self):
        self.last_lat, self.last_lon = 0.0, 0.0
        self.last_time = time.time()
        self.total_distance = 0.0
        self.current_area = "Unknown Area"
        self.running = True
        
        # IP Fallback
        self.network_lat = 0.0
        self.network_lon = 0.0
        self.has_network_fix = False
        self.last_network_check = 0

        # --- NEW: Path Tracking Variables ---
        self.is_tracking = False
        self.path_history = []
        self.session_start_time = None
        self.session_end_time = None
        self.session_start_odo = 0.0
        self.session_speeds = []
        
        self.TRACK_DIR = "/home/group9/3_LC76G_GPS_Module/tracks"
        self.TRACKING_FLAG = "/dev/shm/aras_tracking.flag"
        os.makedirs(self.TRACK_DIR, exist_ok=True)

    def log(self, message):
        print(f"[{time.strftime('%H:%M:%S')}] {message}")
        sys.stdout.flush()

    def reverse_geocode(self, lat, lon):
        try:
            results = rg.search((lat, lon))
            if results:
                area = results[0].get('name', 'Unknown Area')
                self.current_area = area
                self.log(f"Area updated: {self.current_area}")
        except Exception as e:
            self.log(f"Geocode error: {e}")

    def get_network_location(self):
        try:
            data = requests.get("https://ipinfo.io/json", timeout=5).json()
            if 'loc' in data:
                lat_str, lon_str = data['loc'].split(',')
                self.network_lat = float(lat_str)
                self.network_lon = float(lon_str)
                self.has_network_fix = True
        except:
            self.has_network_fix = False

    def generate_path_figure(self, end_odo):
        """Generates a high-res plot of the ridden path perfectly zoomed with stats."""
        if len(self.path_history) < 2:
            self.log("Not enough movement data to generate a track plot.")
            return

        self.log("Generating tracking figure with statistics...")
        
        lats = [pt[0] for pt in self.path_history]
        lons = [pt[1] for pt in self.path_history]

        plt.figure(figsize=(9, 8))
        
        # Plot the path line
        plt.plot(lons, lats, color='#007acc', linewidth=3, marker='o', markersize=2, label='Ridden Path')
        
        # Mark Start (Green Triangle) and End (Red Square)
        plt.plot(lons[0], lats[0], color='green', marker='^', markersize=12, label='Start')
        plt.plot(lons[-1], lats[-1], color='red', marker='s', markersize=10, label='End')

        plt.title(f"ARAS GPS Track - {self.current_area}", fontsize=14, fontweight='bold', pad=15)
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        
        # Add grid and legend
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.legend(loc="best")
        
        # --- CALCULATE STATISTICS ---
        date_str = self.session_start_time.strftime("%Y-%m-%d")
        start_time_str = self.session_start_time.strftime("%H:%M:%S")
        end_time_str = self.session_end_time.strftime("%H:%M:%S")
        
        distance_m = end_odo - self.session_start_odo
        dist_str = f"{distance_m:.1f} m" if distance_m < 1000 else f"{distance_m/1000.0:.3f} km"
        
        if self.session_speeds:
            max_spd = max(self.session_speeds)
            min_spd = min(self.session_speeds)
            avg_spd = sum(self.session_speeds) / len(self.session_speeds)
        else:
            max_spd = min_spd = avg_spd = 0.0

        # Format the text box
        stats_text = (
            f"TRIP STATISTICS\n"
            f"{'-'*20}\n"
            f"Date: {date_str}\n"
            f"Start: {start_time_str}\n"
            f"End: {end_time_str}\n\n"
            f"Location: {self.current_area}\n"
            f"Distance: {dist_str}\n\n"
            f"Max Speed: {max_spd:.1f} km/h\n"
            f"Avg Speed: {avg_spd:.1f} km/h\n"
            f"Min Speed: {min_spd:.1f} km/h"
        )

        # Draw the box outside the plot area on the right
        props = dict(boxstyle='round,pad=0.8', facecolor='#f8f9fa', edgecolor='#ced4da', alpha=0.95)
        plt.gca().text(1.03, 0.95, stats_text, transform=plt.gca().transAxes, fontsize=11,
                verticalalignment='top', bbox=props, linespacing=1.6, family='monospace')

        # Save to the dedicated folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.TRACK_DIR, f"track_{timestamp}.png")
        
        # bbox_inches='tight' forces Matplotlib to expand the saved image to include our text box
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        plt.close()
        
        self.log(f"Tracking figure saved to: {filename}")

    def run(self):
        subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'], stderr=subprocess.DEVNULL)
        
        self.x = L76X.L76X()
        self.x.L76X_Set_Baudrate(115200)
        for cmd in ['$PAIR038,1', '$PAIR002,100', '$PAIR062,0,1', '$PAIR062,4,1', '$PAIR062,5,1', '$PAIR406,1', '$PAIR066,1,1,0,0,0,0']:
            self.x.L76X_Send_Command(cmd)
            time.sleep(0.1)

        last_geocode_time = 0

        while self.running:
            self.x.L76X_Gat_GNRMC()
            now = time.time()
            display_mod_speed = 0.0

            # --- TRACKING FLAG LOGIC ---
            gui_wants_tracking = os.path.exists(self.TRACKING_FLAG)

            if gui_wants_tracking and not self.is_tracking:
                self.is_tracking = True
                self.path_history = []
                self.session_speeds = []
                self.session_start_time = datetime.now()
                self.session_start_odo = self.total_distance
                self.log("Tracking session started.")

            elif not gui_wants_tracking and self.is_tracking:
                self.is_tracking = False
                self.session_end_time = datetime.now()
                self.log("Tracking session ended.")
                
                # Pass the exact odometer value at the moment tracking stopped
                session_end_odo = self.total_distance
                threading.Thread(target=self.generate_path_figure, args=(session_end_odo,), daemon=True).start()

            # 1. STRICT PRIORITY: Hardware GPS
            if self.x.Status == 1:
                status_str = "FIXED (Satellites)"
                active_lat = self.x.Lat
                active_lon = self.x.Lon
                
                time_delta = now - self.last_time
                if self.x.Speed_kmh > 3.0:
                    display_mod_speed = self.x.Speed_kmh
                    self.total_distance += (display_mod_speed / 3.6) * time_delta
                    
                    # Log coordinate for the plot ONLY if moving
                    if self.is_tracking:
                        if not self.path_history or self.path_history[-1] != (active_lat, active_lon):
                            self.path_history.append((active_lat, active_lon))
                            
                # Log speed for stats whether moving or stopped (to get true averages/minimums)
                if self.is_tracking:
                    self.session_speeds.append(display_mod_speed)
                    
                self.last_lat, self.last_lon = active_lat, active_lon

            # 2. FALLBACK: Network IP
            else:
                if (now - self.last_network_check) > 30:
                    self.last_network_check = now
                    threading.Thread(target=self.get_network_location, daemon=True).start()
                
                if self.has_network_fix:
                    status_str = "INDOORS (IP Network)"
                    active_lat = self.network_lat
                    active_lon = self.network_lon
                else:
                    status_str = "SEARCHING"
                    active_lat = 0.0
                    active_lon = 0.0

            if active_lat != 0 and (now - last_geocode_time) > 60:
                last_geocode_time = now
                threading.Thread(target=self.reverse_geocode, args=(active_lat, active_lon), daemon=True).start()

            data = {
                "status": status_str,
                "sats": self.x.Satellites if self.x.Status == 1 else 0,
                "speed": display_mod_speed,
                "odo": self.total_distance,
                "lat": active_lat,
                "lon": active_lon,
                "area": self.current_area
            }
            print(f"__GPS__:{json.dumps(data)}")
            sys.stdout.flush()

            self.last_time = now
            time.sleep(0.1)

if __name__ == "__main__":
    app = HeadlessGPS()
    try: app.run()
    except KeyboardInterrupt: pass