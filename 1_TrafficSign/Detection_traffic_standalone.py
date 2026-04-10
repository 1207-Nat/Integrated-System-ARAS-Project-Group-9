import cv2
import numpy as np
import time
import os
from datetime import datetime
from picamera2 import Picamera2
from picamera2.devices import IMX500

# --- 1. Setup & Folders ---
MODEL_PATH = "/home/group9/1_TrafficSign/network.rpk"
LABEL_PATH = "labels.txt"
RECORDING_DIR = "/home/group9/1_TrafficSign/recordings"
os.makedirs(RECORDING_DIR, exist_ok=True)

with open(LABEL_PATH, 'r') as f:
    labels = [line.strip() for line in f.readlines()]

# --- 2. Color Mapping ---
# Customize these to match your labels.txt exactly
colors = {
    "Stop": (0, 0, 255),        # Red
    "SL_30": (255, 0, 0), # Blue
    "Yield": (0, 255, 255),     # Yellow
    "Pedestrian": (0, 255, 0),  # Green
    "Default": (0, 255, 0)      # Fallback Green
}

def get_color(label):
    for key in colors:
        if key.lower() in label.lower():
            return colors[key]
    return colors["Default"]

# --- 3. GUI Callback ---
def on_record_toggle(val):
    pass # We read the value directly in the loop

# --- 4. Initialize Hardware ---
imx500 = IMX500(MODEL_PATH)
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={'size': (640, 640)})
picam2.configure(config)
picam2.start()

# Setup Window and "Button"
window_name = "Traffic Dashboard"
cv2.namedWindow(window_name)
# Trackbar as a Toggle: 0 = Off, 1 = On
cv2.createTrackbar("RECORD (0/1)", window_name, 0, 1, on_record_toggle)

# Recording State
out = None
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
is_recording = False

print("System Active. Use the Slider in the window to Record.")

prev_time = time.time()

try:
    while True:
        # Check the GUI "Button" state
        gui_rec_state = cv2.getTrackbarPos("RECORD (0/1)", window_name)
        
        # Handle Record Start/Stop Logic
        if gui_rec_state == 1 and not is_recording:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_filename = os.path.join(RECORDING_DIR, f"traffic_{timestamp}.mp4")
            out = cv2.VideoWriter(video_filename, fourcc, 15.0, (640, 640))
            is_recording = True
            print(f"Recording started: {video_filename}")
        elif gui_rec_state == 0 and is_recording:
            if out:
                out.release()
            is_recording = False
            print("Recording saved.")

        # Frame Capture
        request = picam2.capture_request()
        frame = request.make_array("main")
        metadata = request.get_metadata()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        outputs = imx500.get_outputs(metadata)
        
        if outputs:
            boxes, scores, classes = outputs[0], outputs[1], outputs[2]

            for i in range(len(scores)):
                if scores[i] > 0.4:
                    # Coordinate scaling
                    box = boxes[i]
                    x1, y1 = (int(box[0]*640), int(box[1]*640)) if np.max(box) <= 1.5 else (int(box[0]), int(box[1]))
                    x2, y2 = (int(box[2]*640), int(box[3]*640)) if np.max(box) <= 1.5 else (int(box[2]), int(box[3]))
                    
                    label = labels[int(classes[i])] if int(classes[i]) < len(labels) else "Unknown"
                    obj_color = get_color(label)
                    
                    # Draw Styled Box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), obj_color, 2)
                    
                    # Label Background
                    text = f"{label} {scores[i]:.0%}"
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                    cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw, y1), obj_color, -1)
                    cv2.putText(frame, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        request.release()

        # Display recording indicator
        if is_recording:
            cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)
            cv2.putText(frame, "RECORDING", (50, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.imshow(window_name, frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    picam2.stop()
    if out: out.release()
    cv2.destroyAllWindows()