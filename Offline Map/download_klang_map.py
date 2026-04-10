import os
import math
import urllib.request
import time

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile

def download_area_radius(center_lat, center_lon, radius_km, zooms):
    lat_offset = radius_km / 111.0
    lon_offset = radius_km / (111.0 * math.cos(math.radians(center_lat)))
    
    min_lat, max_lat = center_lat - lat_offset, center_lat + lat_offset
    min_lon, max_lon = center_lon - lon_offset, center_lon + lon_offset

    for z in zooms:
        print(f"\n--- Downloading Zoom Level {z} ---")
        x_min, y_max = deg2num(min_lat, min_lon, z)
        x_max, y_min = deg2num(max_lat, max_lon, z)
        
        total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
        print(f"Total tiles for zoom {z}: {total_tiles}")
        
        count = 0
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                dir_path = f"map_tiles/{z}/{x}"
                os.makedirs(dir_path, exist_ok=True)
                file_path = f"{dir_path}/{y}.png"
                
                if not os.path.exists(file_path):
                    url = f"https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga"
                    try:
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with open(file_path, "wb") as f:
                            f.write(urllib.request.urlopen(req).read())
                        time.sleep(0.05) # Protects against IP bans
                    except Exception as e:
                        print(f"Failed {x},{y}: {e}")
                
                count += 1
                if count % 500 == 0:
                    print(f"Progress: {count}/{total_tiles} ({(count/total_tiles)*100:.1f}%)")

if __name__ == "__main__":
    # Center of Klang
    center_lat = 3.0449
    center_lon = 101.4456
    radius_km = 20.0  # Massive 40x40km bounding box
    
    # 10=City view, 18=Extremely detailed building/street view
    zooms_to_download = [10, 11, 12, 13, 14, 15, 16, 17, 18] 
    
    print("WARNING: This will download tens of thousands of files.")
    print("Press Ctrl+C at any time to pause. Rerunning the script will resume where it left off.")
    time.sleep(3)
    
    download_area_radius(center_lat, center_lon, radius_km, zooms_to_download)
    print("\nDownload Complete!")