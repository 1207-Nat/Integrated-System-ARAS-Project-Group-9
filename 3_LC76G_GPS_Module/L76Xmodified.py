import config
import math
import time
from micropyGPS import MicropyGPS

# Initialize MicroPyGPS with +8 timezone (Malaysia)
g = MicropyGPS(8) 
Temp = '0123456789ABCDEF*'
x_pi = 3.14159265358979324 * 3000.0 / 180.0

class L76X(object):
    # Variables
    Lon = 0.0
    Lat = 0.0
    Time_H = 0
    Time_M = 0
    Time_S = 0
    Status = 0
    
    # Coordinates
    Lon_Baidu = 0.0
    Lat_Baidu = 0.0
    Lon_Google = 0.0
    Lat_Google = 0.0
    
    # Extras
    Satellites = 0
    Speed_kmh = 0.0

    def __init__(self):
        self.config = config.config(115200)

    def L76X_Send_Command(self, data):
        # Calculates and appends checksum automatically. 
        Check = ord(data[1]) 
        for i in range(2, len(data)):
            Check = Check ^ ord(data[i]) 
        data = data + Temp[16]
        data = data + Temp[(Check//16)]
        data = data + Temp[(Check%16)]
        self.config.Uart_SendString(data.encode())
        self.config.Uart_SendByte('\r'.encode())
        self.config.Uart_SendByte('\n'.encode())

    def L76X_Gat_GNRMC(self):
        """
        Reads data from UART and parses via MicropyGPS.
        """
        while self.config.serial.in_waiting > 0:
            try:
                data_chunk = self.config.serial.read(self.config.serial.in_waiting)
                for byte in data_chunk:
                    char = chr(byte)
                    g.update(char)
            except Exception as e:
                print(f"Serial Read Error: {e}")
                break

        if g.valid:
            self.Status = 1
        else:
            self.Status = 0

        if g.latitude[0] is not None:
            self.Lat = g.latitude[0] + (g.latitude[1] / 60.0)
            if g.latitude[2] == 'S': 
                self.Lat = -self.Lat
        
        if g.longitude[0] is not None:
            self.Lon = g.longitude[0] + (g.longitude[1] / 60.0)
            if g.longitude[2] == 'W': 
                self.Lon = -self.Lon
        
        self.Time_H = g.timestamp[0]
        self.Time_M = g.timestamp[1]
        self.Time_S = g.timestamp[2]
        self.Satellites = g.satellites_in_use
        
        if g.speed[2] is not None:
            self.Speed_kmh = g.speed[2]
        else:
            self.Speed_kmh = 0.0

    def bd_encrypt(self):
        x = self.Lon_Google
        y = self.Lat_Google
        z = math.sqrt(x * x + y * y) + 0.00002 * math.sin(y * x_pi)
        theta = math.atan2(y, x) + 0.000003 * math.cos(x * x_pi)
        self.Lon_Baidu = z * math.cos(theta) + 0.0065
        self.Lat_Baidu = z * math.sin(theta) + 0.006

    def L76X_Google_Coordinates(self):
        self.Lat_Google = self.Lat
        self.Lon_Google = self.Lon
        self.bd_encrypt()

    def L76X_Set_Baudrate(self, Baudrate):
        self.config.Uart_Set_Baudrate(Baudrate)

    # REMOVED: def L76X_Exit_BackupMode(self) - It was violently pulsing Pin 17

    def get_distance(self, lat1, lon1, lat2, lon2):
        R = 6371000  
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))