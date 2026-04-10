import cv2
import numpy as np
import time
import os
from datetime import datetime
from picamera2 import Picamera2
from picamera2.devices import IMX500

# 1. Setup Paths & Folders
MODEL_PATH = "/home/group9/TrafficSign/network.rpk"
LABEL_PATH = "labels.txt"
RECORD_DIR = "/home/group9/TrafficSign/recordings"
os.makedirs(RECORD_DIR, exist_ok=True)

with open(LABEL_PATH, 'r') as f:
    labels = [line.strip() for line in f.readlines()]

# 2. Color Map Configuration
# Edit these keys to match words in your labels.txt
COLOR_MAP = {
    "stop": (0, 0, 255),       # Red
    "limit": (255, 0, 0),      # Blue
    "yield": (0, 255, 255),    # Yellow
    "warning": (0, 165, 255),  # Orange
    "default": (0, 255, 0)     # Green
}

def get_obj_color(label_text):
    label_text = label_text.lower()
    for key, color in COLOR_MAP.items():
        if key in label_text:
            return color
    return COLOR_MAP["default"]

# 3. GUI Callback
def nothing(x):
    pass

# 4. Initialize Camera and AI
imx500 = IMX500(MODEL_PATH)
picam2 = Picamera2()
# Use RGB888 as per your successful color conversion version
config = picam2.create_preview_configuration(main={'size': (640, 640), 'format': 'RGB888'})
picam2.configure(config)
picam2.start()

# Setup Window and GUI "Button"
WINDOW_NAME = "Malaysian Traffic Dashboard"
cv2.namedWindow(WINDOW_NAME)
cv2.createTrackbar("REC (0/1)", WINDOW_NAME, 0, 1, nothing)

# Global Recording Vars
video_writer = None
is_recording = False
fourcc = cv2.VideoWriter_fourcc(*'mp4v')

print("System Ready! Use the slider to start/stop recording.")

prev_time = time.time()

try:
    while True:
        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0.0
        prev_time = curr_time

        # --- Capture & Color Fix ---
        request = picam2.capture_request()
        frame = request.make_array("main")
        
        # FIX: Manual conversion as per your reference version
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        metadata = request.get_metadata()
        outputs = imx500.get_outputs(metadata)

        # --- Detection Processing ---
        if outputs:
            boxes = outputs[0]   # (300, 4) normalized
            scores = outputs[1]  # (300,)
            classes = outputs[2] # (300,)

            for i in range(len(scores)):
                if scores[i] > 0.4:
                    # Scaling coordinates to 640x640 frame
                    x1 = int(boxes[i][0] * frame.shape[1])
                    y1 = int(boxes[i][1] * frame.shape[0])
                    x2 = int(boxes[i][2] * frame.shape[1])
                    y2 = int(boxes[i][3] * frame.shape[0])

                    if x2 > x1 and y2 > y1:
                        class_idx = int(classes[i])
                        label = labels[class_idx] if class_idx < len(labels) else f"ID {class_idx}"
                        
                        # Get Dynamic Color
                        box_color = get_obj_color(label)

                        # Draw Box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 3)

                        # Draw Label with Background
                        text = f"{label} {scores[i]:.0%}"
                        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                        cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw, y1), box_color, -1)
                        cv2.putText(frame, text, (x1, y1 - 5), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # --- Recording Logic (GUI Dashboard Integration) ---
        rec_slider = cv2.getTrackbarPos("REC (0/1)", WINDOW_NAME)
        
        if rec_slider == 1:
            if not is_recording:
                # Start new file
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(RECORD_DIR, f"traffic_{ts}.mp4")
                video_writer = cv2.VideoWriter(save_path, fourcc, 15.0, (640, 640))
                is_recording = True
                print(f"[*] Started recording to {save_path}")
            
            # Write frame to file
            video_writer.write(frame)
            
            # Visual indicator
            cv2.circle(frame, (30, 70), 10, (0, 0, 255), -1)
            cv2.putText(frame, "REC ACTIVE", (50, 75), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            if is_recording:
                video_writer.release()
                is_recording = False
                print("[*] Recording stopped.")

        # --- Final UI Output ---
        request.release()
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        
        cv2.imshow(WINDOW_NAME, frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    if video_writer:
        video_writer.release()
    picam2.stop()
    cv2.destroyAllWindows()