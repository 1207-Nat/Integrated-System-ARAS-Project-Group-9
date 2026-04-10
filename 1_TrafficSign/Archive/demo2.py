import cv2
import numpy as np
import time
from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import postprocess_nanodet_detection # Works for YOLO Nano

# 1. Setup Paths
MODEL_PATH = "/home/group9/TrafficSign/network.rpk"
LABEL_PATH = "labels.txt"

with open(LABEL_PATH, 'r') as f:
    labels = [line.strip() for line in f.readlines()]

# 2. Initialize Camera and AI Device
imx500 = IMX500(MODEL_PATH)
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={'size': (640, 640)})
picam2.configure(config)
picam2.start()

print("Camera started! Point it at the Nottingham entrance...")

# Initialize FPS variables before the loop
prev_time = time.time()
fps_smooth = 0.0

try:
    while True:
        # 1. Capture a request
        request = picam2.capture_request()
        
        # 2. Get the actual image frame and convert color
        frame = request.make_array("main")
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        # 3. Get metadata and extract tensors
        metadata = request.get_metadata()
        outputs = imx500.get_outputs(metadata)
        
        # List to hold the text we want to print below the FPS
        detection_texts = []

        if outputs:
            try:
                boxes = outputs[0]
                scores = outputs[1]
                classes = outputs[2]
                
                conf_threshold = 0.8  
                valid_detections = []
                
                for i in range(len(scores)):
                    if scores[i] > conf_threshold:
                        raw_box = boxes[i]
                        
                        # DEBUG: Print exactly what the model is outputting
                        print(f"RAW BOX DATA: {raw_box}") 
                        
                        # Auto-detect if coordinates are normalized (0 to 1) or absolute pixels
                        if max(raw_box) <= 2.0: 
                            # They are normalized, multiply by frame size
                            x1 = int(raw_box[0] * frame.shape[1])
                            y1 = int(raw_box[1] * frame.shape[0])
                            x2 = int(raw_box[2] * frame.shape[1])
                            y2 = int(raw_box[3] * frame.shape[0])
                        else:
                            # They are already absolute pixels, just convert to integers
                            x1, y1, x2, y2 = map(int, raw_box)

                        # Check if the model is actually outputting [y1, x1, y2, x2]
                        if y1 > x1 and y2 > x2 and raw_box[0] < raw_box[1]:
                            print("Format looks like [y1, x1, y2, x2]. Flipping...")
                            x1, y1 = y1, x1
                            x2, y2 = y2, x2

                        # Clamp coordinates to the screen size so OpenCV doesn't fail
                        x1 = max(0, min(x1, frame.shape[1]))
                        y1 = max(0, min(y1, frame.shape[0]))
                        x2 = max(0, min(x2, frame.shape[1]))
                        y2 = max(0, min(y2, frame.shape[0]))

                        # Relaxed validation check
                        if x2 > x1 and y2 > y1:
                            valid_detections.append({
                                'box': (x1, y1, x2, y2),
                                'class': int(classes[i]),
                                'score': scores[i]
                            })
                        else:
                            print(f"Invalid box dimensions after math: ({x1},{y1}) to ({x2},{y2})")
                            
                # --- DRAWING BOUNDING BOXES AND COLLECTING LABELS ---
                for det in valid_detections:
                    try:
                        label = labels[det['class']]
                    except IndexError:
                        label = f"Class {det['class']}"
                    
                    conf = det['score']
                    x1, y1, x2, y2 = det['box']
                    
                    # Add this detection to our list for the top-left display
                    detection_texts.append(f"- {label}: {conf:.0%}")
                    
                    # Draw the bounding box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
                    
                    # Prepare and draw the label text on the box
                    text = f"{label} {conf:.0%}"
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    y_label = max(y1, th + 10) 
                    cv2.rectangle(frame, (x1, y_label - th - 10), (x1 + tw, y_label), (0, 255, 0), -1)
                    cv2.putText(frame, text, (x1, y_label - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                            
            except (ValueError, IndexError, TypeError) as e:
                print(f"Detection error: {e}")

        # 4. CRITICAL: Release the request
        request.release()

        # --- FPS CALCULATION ---
        curr_time = time.time()
        fps_current = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0.0
        prev_time = curr_time
        fps_smooth = (0.9 * fps_smooth) + (0.1 * fps_current)

        # --- HUD DISPLAY (Top Left) ---
        # 1. Display FPS
        cv2.putText(frame, f"FPS: {fps_smooth:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        # 2. Display detections below FPS
        y_offset = 60 # Start drawing slightly below the FPS text (which is at y=30)
        for det_text in detection_texts:
            # Add a slight black background to the text so it's readable against bright skies
            (tw, th), _ = cv2.getTextSize(det_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (8, y_offset - th - 4), (10 + tw, y_offset + 4), (0, 0, 0), -1)
            
            # Draw the green text
            cv2.putText(frame, det_text, (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            y_offset += 25 # Move down 25 pixels for the next line

        try:
            cv2.imshow("Malaysian Traffic Detection", frame)
        except Exception as e:
            print(f"Error displaying frame: {e}")
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    picam2.stop()
    cv2.destroyAllWindows()


