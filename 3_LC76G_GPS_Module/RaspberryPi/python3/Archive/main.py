import L76Xmodified as L76X
import time
import math

def convert_to_google(raw_val):
    # Fix for your specific L76X library output format (D.MMmmmm)
    # Raw: 2.5678 -> Degrees: 2, Minutes: 56.78
    
    degrees = int(raw_val)
    minutes = (raw_val - degrees) * 100
    
    decimal_degrees = degrees + (minutes / 60)
    return decimal_degrees

try:
    x = L76X.L76X()
    x.L76X_Set_Baudrate(115200)
    x.L76X_Send_Command(x.SET_POS_FIX_400MS)
    x.L76X_Send_Command(x.SET_NMEA_OUTPUT)
    x.L76X_Exit_BackupMode()

    while(1):
        x.L76X_Gat_GNRMC()
        if(x.Status == 1):
            print('Already positioned')
        else:
            print('No positioning')
        
        print('Time: {:02}:{:02}:{:02}'.format(x.Time_H, x.Time_M, int(x.Time_S)))
        print('Lon = %f'%x.Lon,'   Lat=',x.Lat)
        
        # Original Baidu Output
        x.L76X_Baidu_Coordinates(x.Lat, x.Lon)
        print('Baidu coordinate ', x.Lat_Baidu, ',', x.Lon_Baidu)
        
        # FIXED Google Coordinate Calculation
        google_lat = convert_to_google(x.Lat)
        google_lon = convert_to_google(x.Lon)
        
        print(f'Google coordinate  {google_lat:.8f} , {google_lon:.8f}')
        print(f'Google Maps Link: http://googleusercontent.com/maps.google.com/8{google_lat:.8f},{google_lon:.8f}')
        print("-" * 30)
        
        time.sleep(1)

except KeyboardInterrupt:
    print("\nProgram end")
    exit()
