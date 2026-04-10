import L76Xmodified as L76X
import time
import json
import sys
import threading
import requests
import subprocess
import reverse_geocoder as rg

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

    def log(self, message):
        print(f"[{time.strftime('%H:%M:%S')}] {message}")
        sys.stdout.flush()
        
    def reverse_geocode(self, lat, lon):
        """Asks the local offline database for the town/suburb name."""
        try:
            # rg.search expects a tuple of (latitude, longitude)
            results = rg.search((lat, lon))
            
            if results:
                # The result is a list of dictionaries. 
                # Example: [{'name': 'Semenyih', 'admin1': 'Selangor', 'cc': 'MY', ...}]
                area = results[0].get('name', 'Unknown Area')
                
                self.current_area = area
                self.log(f"Area updated: {self.current_area}")
                
        except Exception as e:
            self.log(f"Geocode error: {e}")

#     def reverse_geocode(self, lat, lon):
#         """Asks OpenStreetMap for the local town/suburb name of the coordinates."""
#         # Removed zoom parameter to get full address detail (defaults to zoom=18)
#         url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
#         try:
#             # Nominatim strictly requires a custom User-Agent
#             headers = {'User-Agent': 'ARAS_ADAS_Project/1.0 (Student_Project)'}
#             resp = requests.get(url, headers=headers, timeout=5).json()
#             if 'address' in resp:
#                 addr = resp['address']
#                 # Prioritize local town/suburb over the larger city/municipality
#                 area = addr.get('suburb', 
#                        addr.get('village', 
#                        addr.get('town', 
#                        addr.get('city_district', 
#                        addr.get('city', 
#                        addr.get('county', 
#                        addr.get('state', 'Unknown Area')))))))
#                 
#                 self.current_area = area
#                 self.log(f"Area updated: {self.current_area}")
#         except Exception as e:
#             self.log(f"Geocode error: {e}")

    def get_network_location(self):
        """Free IP Fallback - Usually city-level accuracy."""
        try:
            data = requests.get("https://ipinfo.io/json", timeout=5).json()
            if 'loc' in data:
                lat_str, lon_str = data['loc'].split(',')
                self.network_lat = float(lat_str)
                self.network_lon = float(lon_str)
                self.has_network_fix = True
        except:
            self.has_network_fix = False

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

            # 1. STRICT PRIORITY: Hardware GPS
            if self.x.Status == 1:
                status_str = "FIXED (Satellites)"
                active_lat = self.x.Lat
                active_lon = self.x.Lon
                
                time_delta = now - self.last_time
                if self.x.Speed_kmh > 3.0:
                    display_mod_speed = self.x.Speed_kmh
                    self.total_distance += (display_mod_speed / 3.6) * time_delta
                    
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

            # Update Area Name every 60 seconds if we have a location
            if active_lat != 0 and (now - last_geocode_time) > 60:
                last_geocode_time = now
                threading.Thread(target=self.reverse_geocode, args=(active_lat, active_lon), daemon=True).start()

            # Package Data
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