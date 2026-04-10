import cv2
import numpy as np
import base64
import sys
import os
import json
import time  # <-- Make sure time is imported!
from datetime import datetime
from picamera2 import Picamera2
from picamera2.devices import IMX500

MODEL_PATH = "network.rpk"
LABEL_PATH = "labels.txt"
RECORDING_DIR = "recordings"
os.makedirs(RECORDING_DIR, exist_ok=True)

confidence_threshold = 0.4

# The GUI creates this file when you click "Start Recording"
RECORD_FLAG = ".record_flag"
# File sitting in the Pi's RAM containing live GPS data
SHARED_GPS_FILE = "/dev/shm/aras_gps_data.json"

with open(LABEL_PATH, 'r') as f:
    labels = [line.strip() for line in f.readlines()]

imx500 = IMX500(MODEL_PATH)
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={'size': (640, 640)})
config['controls']['FrameRate'] = 30
picam2.configure(config)
picam2.start()

print("Camera AI Headless Interface Started.")

out = None
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
is_recording = False

# --- 1Hz FPS Tracker Variables ---
fps_start_time = time.time()
fps_frame_count = 0
current_fps = 0

try:
    while True:
        # --- Handle Recording Logic ---
        gui_wants_record = os.path.exists(RECORD_FLAG)
        
        if gui_wants_record and not is_recording:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_filename = os.path.join(RECORDING_DIR, f"traffic_{timestamp}.mp4")
            out = cv2.VideoWriter(video_filename, fourcc, 15.0, (640, 640))
            is_recording = True
            print(f"Recording started: {video_filename}")
            
        elif not gui_wants_record and is_recording:
            if out: out.release()
            is_recording = False
            print("Recording saved and stopped.")

        # --- Frame Capture & Inference ---
        request = picam2.capture_request()
        frame = request.make_array("main")
        metadata = request.get_metadata()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        h, w = frame.shape[:2]
        
        outputs = imx500.get_outputs(metadata)
        detected_labels = []

        if outputs:
            boxes, scores, classes = outputs[0], outputs[1], outputs[2]
            for i in range(len(scores)):
                if scores[i] > 0.5:
                    xmin, ymin, xmax, ymax = boxes[i]
                    
                    # --- 16:9 to 1:1 GEOMETRY CORRECTION ---
                    # To get a 1:1 crop from a 16:9 sensor, we lose ~21.8% of the left and right sides.
                    # The visible width is only 56.25% of the total sensor width.
                    x_offset = 0.21875  # 21.875% cropped from the left
                    x_scale = 0.5625    # 56.25% visible width
                    
                    # The Y-axis is usually uncropped in this mode, but if the boxes are 
                    # still hovering slightly above or below the object, you can tweak these.
                    y_offset = 0.0
                    y_scale = 1.0

                    if np.max(boxes[i]) <= 1.5:
                        x1 = int(((xmin - x_offset) / x_scale) * 640)
                        x2 = int(((xmax - x_offset) / x_scale) * 640)
                        y1 = int(((ymin - y_offset) / y_scale) * 640)
                        y2 = int(((ymax - y_offset) / y_scale) * 640)
                    else:
                        x1, y1 = int(xmin), int(ymin)
                        x2, y2 = int(xmax), int(ymax)
                        
                    # 3. Only draw if the box is actually visible on the cropped screen
                    if x1 < 640 and x2 > 0:
                        # Prevent OpenCV from crashing by clamping coordinates to the screen edges
                        x1 = max(0, min(640, x1))
                        x2 = max(0, min(640, x2))
                        y1 = max(0, min(640, y1))
                        y2 = max(0, min(640, y2))
                        
                        # Verify it's a valid box before drawing
                        if x2 > x1 and y2 > y1:
                            label = labels[int(classes[i])] if int(classes[i]) < len(labels) else "Unknown"
                            detected_labels.append(label)
                            
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        
        request.release()
        
        # --- Calculate 1Hz FPS ---
        fps_frame_count += 1
        current_time = time.time()
        if current_time - fps_start_time >= 1.0:
            current_fps = fps_frame_count / (current_time - fps_start_time)
            fps_frame_count = 0
            fps_start_time = current_time

        # --- AESTHETIC DASHCAM OVERLAY (Date, Time, GPS, FPS) ---
        
        # 1. Fetch latest GPS data from RAM
        gps_speed, gps_lat, gps_lon = 0.0, 0.0, 0.0
        gps_status = "SEARCHING"
        gps_area = "Unknown Area"
        try:
            if os.path.exists(SHARED_GPS_FILE):
                with open(SHARED_GPS_FILE, "r") as f:
                    gps_data = json.load(f)
                    gps_speed = gps_data.get("speed", 0.0)
                    gps_lat = gps_data.get("lat", 0.0)
                    gps_lon = gps_data.get("lon", 0.0)
                    gps_status = gps_data.get("status", "SEARCHING")
                    gps_area = gps_data.get("area", "Unknown Area")
        except Exception:
            pass

        # 2. Draw Semi-Transparent Banner at bottom
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h - 45), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        # 3. Draw Date/Time & Area (Left side, Yellow)
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, dt_str, (10, h - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Loc: {gps_area}", (10, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

        # 4. Draw GPS Data (Right side, White)
        if ("FIXED" in gps_status or "INDOORS" in gps_status) and gps_lat != 0:
            speed_str = f"{gps_speed:.1f} km/h"
            coord_str = f"{gps_lat:.5f}, {gps_lon:.5f}"
            
            (tw1, _), _ = cv2.getTextSize(speed_str, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.putText(frame, speed_str, (w - tw1 - 10, h - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
            
            (tw2, _), _ = cv2.getTextSize(coord_str, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.putText(frame, coord_str, (w - tw2 - 10, h - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            gps_str = "GPS: SEARCHING..."
            (tw, _), _ = cv2.getTextSize(gps_str, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.putText(frame, gps_str, (w - tw - 10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1, cv2.LINE_AA)

        # 5. Draw 1Hz FPS (Top Right, Green)
        fps_str = f"FPS: {int(current_fps)}"
        cv2.putText(frame, fps_str, (w - 120, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)

        # --- Recording Indicator & Saving ---
        if is_recording:
            cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)
            cv2.putText(frame, "REC", (50, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            # Because we draw FPS before this line, it will be saved in the video file
            if out: out.write(frame)

        # --- Send Data to GUI ---
        success, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
        if success: print(f"__FRAME__:{base64.b64encode(buffer).decode('utf-8')}")
        if detected_labels: print(f"__DETECT__:{','.join(detected_labels)}")
        sys.stdout.flush()

finally:
    picam2.stop()
    if out: out.release()