import L76Xmodified as L76X
import time
import subprocess
import sys

def check_wifi_time_sync():
    print("Checking WiFi/Network time synchronization...")
    try:
        # Check if NTP is active and time is synced
        result = subprocess.run(['timedatectl', 'show', '--property=NTPSynchronized'], 
                               capture_output=True, text=True)
        
        if "NTPSynchronized=yes" in result.stdout:
            print("Time is synchronized via Network.")
        else:
            print("Time NOT synced yet. Waiting 5 seconds...")
            # Optional: force NTP on if it's not
            subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'])
            time.sleep(5)
    except Exception as e:
        print(f"Could not verify network time: {e}")

try:
    # 1. Sync Time first
    check_wifi_time_sync()

    print("Initializing GPS Module...")
    x = L76X.L76X()
    
    # 2. Setup GPS
    x.L76X_Set_Baudrate(115200)
    
    # Send commands
    # Set Static Navigation Threshold to 0 (Disable)
    # This allows the module to report even the tiniest movements
    x.L76X_Send_Command('$PAIR038,0')
    x.L76X_Send_Command('$PAIR002,1000') 
    x.L76X_Send_Command('$PAIR062,0,1')  
    x.L76X_Send_Command('$PAIR003*39') 
    x.L76X_Send_Command('$PAIR066,1,1,1,1,1,0*3B')
    
    x.L76X_Exit_BackupMode()
    
    # --- Before the while(1) loop ---
    last_lat, last_lon = 0.0, 0.0
    last_time = time.time()

    print("Starting Data Collection Loop...\n" + "="*30)

    while(1):
        x.L76X_Gat_GNRMC()
        
        current_time = time.time()
        
        # Display Status
        status_text = "[FIXED]" if x.Status == 1 else "[SEARCHING...]"
        print(f"STATUS: {status_text} | Satellites: {getattr(x, 'Satellites', 0)}")
        
        # 2. Calculated Speed vs Module Speed
        # We only calculate if we have a fix and a previous point
        calc_speed = 0.0
        if x.Status == 1 and last_lat != 0:
            distance = x.get_distance(last_lat, last_lon, x.Lat, x.Lon)
            time_delta = current_time - last_time
            
            # Convert m/s to km/h
            if time_delta > 0:
                calc_speed = (distance / time_delta) * 3.6

        print(f"MODULE SPEED: {x.Speed_kmh:.2f} km/h")
        print(f"CALC SPEED  : {calc_speed:.2f} km/h")

        # 3. Update trackers for next iteration
        last_lat, last_lon = x.Lat, x.Lon
        last_time = current_time
        
        # Display Time (This will be accurate because of the sync check)
        print('Time: {:02}:{:02}:{:02}'.format(x.Time_H, x.Time_M, int(x.Time_S)))
        
        if x.Lat != 0:
            print(f'Lat = {x.Lat:.7f}    Lon = {x.Lon:.7f}')
            maps_url = f"https://www.google.com/maps?q={x.Lat:.8f},{x.Lon:.8f}"
            print(f'Google Maps: {maps_url}')
        else:
            print('Coordinates: Waiting for valid satellite data...')
            
        print("-" * 30)
        time.sleep(1)

except KeyboardInterrupt:
    print("\nProgram end")
    sys.exit()