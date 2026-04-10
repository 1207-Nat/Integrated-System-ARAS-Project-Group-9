import cv2
import numpy as np
import time
from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import postprocess_nanodet_detection # Works for YOLO Nano

# 1. Setup Paths
MODEL_PATH = "/home/group9/1_TrafficSign/network.rpk"
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

prev_time = time.time()
fps = 0.0

try:
    while True:
        # Calculate FPS
        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0.0
        prev_time = curr_time
        # 1. Capture a request (synchronizes image and AI metadata)
        request = picam2.capture_request()
        
        # 2. Get the actual image frame
        frame = request.make_array("main")
        
        # Convert from RGB to BGR for OpenCV
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        # 3. FIX: Use .get_metadata() instead of .metadata
        metadata = request.get_metadata()
        
        # 4. Extract tensors from metadata
        outputs = imx500.get_outputs(metadata)
        
        # DEBUG: Check output statistics
        if outputs:
            print(f"Max score: {np.max(outputs[1]):.4f}, Min score: {np.min(outputs[1]):.4f}")
        
        if outputs:
            # 5. Process the detection outputs
            # Outputs are already separated: [boxes, scores, classes, ...]
            try:
                boxes = outputs[0]  # (300, 4) - normalized [x1, y1, x2, y2]
                scores = outputs[1]  # (300,) - confidence scores
                classes = outputs[2]  # (300,) - class indices
                
                # Filter detections by confidence threshold
                conf_threshold = 0.4  # Lowered to debug
                valid_detections = []
                detection_count = 0
                
                for i in range(len(scores)):
                    if scores[i] > conf_threshold:
                        # Try both coordinate orders - the model might use [y1, x1, y2, x2]
                        # First try: [x1, y1, x2, y2]
                        x1 = int(boxes[i][0] * frame.shape[1])
                        y1 = int(boxes[i][1] * frame.shape[0])
                        x2 = int(boxes[i][2] * frame.shape[1])
                        y2 = int(boxes[i][3] * frame.shape[0])
                        
                        # Ensure coordinates are valid
                        if x1 >= 0 and y1 >= 0 and x2 > x1 and y2 > y1:
                            class_idx = int(classes[i])
                            score = scores[i]
                            confidence = int(score * 100)
                            
                            valid_detections.append({
                                'box': (x1, y1, x2, y2),
                                'class': class_idx,
                                'score': score
                            })
                            
                            # Print detection to terminal
                            try:
                                object_name = labels[class_idx]
                            except IndexError:
                                object_name = f"Class {class_idx}"
                            print(f"[DETECTION] {object_name}: {confidence}% confidence at ({x1}, {y1}) to ({x2}, {y2})")
                            detection_count += 1
                
                detections = valid_detections
                if detection_count > 0:
                    print(f"Frame: {detection_count} object(s) detected")
                else:
                    print(f"Found {len(detections)} detections above threshold {conf_threshold}")
                    if len(detections) == 0 and len(scores) > 0:
                        print(f"Top 5 scores: {sorted(scores, reverse=True)[:5]}")
                
            except (ValueError, IndexError, TypeError) as e:
                print(f"Detection error: {e}")
                detections = []
            
            if detections:
                for det in detections:
                    # category = class ID, conf = score, box = [x1, y1, x2, y2]
                    try:
                        label = labels[det['class']]
                    except IndexError:
                        label = f"Class {det['class']}"
                    conf = det['score']
                    box = det['box']
                    
                    # Draw bounding box with thick border
                    cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 3)
                    
                    # Draw label background for readability
                    text = f"{label} {conf:.0%}"
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(frame, (box[0], box[1] - th - 10), (box[0] + tw, box[1]), (0, 255, 0), -1)
                    cv2.putText(frame, text, (box[0], box[1] - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # 6. CRITICAL: Release the request to free up camera memory
        request.release()

        # Display FPS on frame
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        try:
            cv2.imshow("Malaysian Traffic Detection", frame)
        except Exception as e:
            print(f"Error displaying frame: {e}")
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    picam2.stop()

