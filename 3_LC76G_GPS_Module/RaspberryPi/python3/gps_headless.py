import L76Xmodified as L76X
import time
import json
import sys
import threading
import requests
import subprocess

class HeadlessGPS:
    def __init__(self):
        self.last_lat, self.last_lon = 0.0, 0.0
        self.last_time = time.time()
        self.total_distance = 0.0
        self.current_speed_limit = "Not Available"
        self.last_api_check = 0
        self.running = True

    def log(self, message):
        # Prints normal text so the Launcher puts it in the GPS Console
        print(f"[{time.strftime('%H:%M:%S')}] {message}")
        sys.stdout.flush()

    def fetch_speed_limit(self, lat, lon):
        query = f"[out:json]; way(around:30, {lat}, {lon})['maxspeed']; out tags;"
        url = "http://overpass-api.de/api/interpreter"
        try:
            response = requests.get(url, params={'data': query}, timeout=5)
            data = response.json()
            if data.get('elements'):
                limit = data['elements'][0]['tags'].get('maxspeed', 'Not Available')
                self.current_speed_limit = f"{limit} km/h" if limit.isdigit() else limit
                self.log(f"API Update: Road speed limit is {self.current_speed_limit}")
            else:
                self.current_speed_limit = "Not Available"
        except:
            self.current_speed_limit = "Not Available"

    def run(self):
        self.log("Syncing Network Time...")
        subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'], stderr=subprocess.DEVNULL)
        
        self.log("Initializing LC76G Hardware...")
        x = L76X.L76X()
        x.L76X_Set_Baudrate(115200)

        for cmd in ['$PAIR038,1', '$PAIR002,100', '$PAIR062,0,1', '$PAIR062,4,1', '$PAIR062,5,1', '$PAIR406,1', '$PAIR066,1,1,0,0,0,0']:
            x.L76X_Send_Command(cmd)
            time.sleep(0.1)

        x.L76X_Exit_BackupMode()
        self.log("--- Ready. Waiting for RMC sentences ---")

        while self.running:
            x.L76X_Gat_GNRMC()
            now = time.time()
            calc_speed = 0.0
            display_mod_speed = 0.0

            if x.Status == 1:
                time_delta = now - self.last_time
                if x.Speed_kmh > 3.0:
                    display_mod_speed = x.Speed_kmh
                
                if display_mod_speed > 0 and time_delta > 0:
                    self.total_distance += (display_mod_speed / 3.6) * time_delta

                if self.last_lat != 0 and time_delta > 0:
                    haversine_dist = x.get_distance(self.last_lat, self.last_lon, x.Lat, x.Lon)
                    calc_speed = (haversine_dist / time_delta) * 3.6
                    if calc_speed < 3.0: calc_speed = 0.0

                # API Call
                if (display_mod_speed > 5.0) and (now - self.last_api_check) > 15:
                    self.last_api_check = now
                    threading.Thread(target=self.fetch_speed_limit, args=(x.Lat, x.Lon), daemon=True).start()

            # Package data for the Launcher GUI
            data = {
                "status": "FIXED" if x.Status == 1 else "SEARCHING",
                "sats": x.Satellites,
                "speed": display_mod_speed,
                "calc_speed": calc_speed,
                "odo": self.total_distance,
                "limit": self.current_speed_limit,
                "lat": x.Lat,
                "lon": x.Lon
            }
            
            # Send Data Payload
            print(f"__GPS__:{json.dumps(data)}")
            sys.stdout.flush()

            self.last_lat, self.last_lon, self.last_time = x.Lat, x.Lon, now
            time.sleep(0.1)

if __name__ == "__main__":
    app = HeadlessGPS()
    try:
        app.run()
    except KeyboardInterrupt:
        pass