import sys
import cv2
import mediapipe as mp
import numpy as np
import time
import os
import threading
import winsound

# Add pylibs to path for torch/ultralytics (Windows long path workaround)
sys.path.insert(0, r'C:\pylibs')

BaseOptions = mp.tasks.BaseOptions
FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
FaceLandmarksConnections = mp.tasks.vision.FaceLandmarksConnections
VisionRunningMode = mp.tasks.vision.RunningMode

model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'face_landmarker.task')

# Initialize audio alert paths for different alert types
HELMET_ALERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Helmet1.wav')
DISTRACTION_ALERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Distraction.wav')

HELMET_ALERT_AVAILABLE = os.path.exists(HELMET_ALERT_PATH)
DISTRACTION_ALERT_AVAILABLE = os.path.exists(DISTRACTION_ALERT_PATH)

if HELMET_ALERT_AVAILABLE:
    print(f"Helmet alert sound found at: {HELMET_ALERT_PATH}")
else:
    print(f"Warning: Helmet alert sound not found at {HELMET_ALERT_PATH}")

if DISTRACTION_ALERT_AVAILABLE:
    print(f"Distraction alert sound found at: {DISTRACTION_ALERT_PATH}")
else:
    print(f"Warning: Distraction alert sound not found at {DISTRACTION_ALERT_PATH}")

last_helmet_alert_time = 0
last_distraction_alert_time = 0
ALERT_COOLDOWN = 2.0  # Prevent alert spam - play at most every 2 seconds

options = FaceLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.VIDEO,
    min_face_detection_confidence=0.5,
    min_tracking_confidence=0.6,
    num_faces=1)

landmarker = FaceLandmarker.create_from_options(options)

# Helmet detection setup — supports both classifier (.pt from train_helmet_model)
# and detector (.pt from train_helmet_roboflow)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HELMET_CLASSIFIER_PATH = os.path.join(SCRIPT_DIR, 'helmet_classifier.pt')
HELMET_DETECTOR_PATH = os.path.join(SCRIPT_DIR, 'helmet_detector.pt')
helmet_model = None
helmet_mode = None  # 'classify' or 'detect'
helmet_status = "No Model"
HELMET_CHECK_INTERVAL = 10  # check every N frames to save performance
helmet_frame_counter = 0

if os.path.exists(HELMET_DETECTOR_PATH):
    from ultralytics import YOLO
    helmet_model = YOLO(HELMET_DETECTOR_PATH)
    helmet_mode = 'detect'
    helmet_status = "Checking..."
    print("Helmet detection model loaded (Roboflow detector).")
elif os.path.exists(HELMET_CLASSIFIER_PATH):
    from ultralytics import YOLO
    helmet_model = YOLO(HELMET_CLASSIFIER_PATH)
    helmet_mode = 'classify'
    helmet_status = "Checking..."
    print("Helmet classification model loaded.")
else:
    print("No helmet model found. To enable helmet detection:")
    print("  Option 1: Run collect_helmet_data.py + train_helmet_model.py")
    print("  Option 2: Run train_helmet_roboflow.py with a Roboflow dataset")

# Distraction detection parameters
DISTRACTION_ANGLE_THRESHOLD = 10  # degrees away from forward
DISTRACTION_TIME_THRESHOLD = 2.0    # seconds of sustained distraction

# State machine: 'waiting_for_helmet' or 'face_pose'
app_state = 'waiting_for_helmet'

# Cached helmet bounding box for flicker-free drawing
# Format: (x1, y1, x2, y2, conf) or None
cached_helmet_bbox = None

def play_alert_sound(alert_type='distraction'):
    """Play alert sound with cooldown to prevent spam. Repeats every 2 seconds while condition is ongoing."""
    global last_helmet_alert_time, last_distraction_alert_time
    
    current_time = time.time()
    
    should_play = False
    alert_path = None
    
    if alert_type == 'helmet':
        if not HELMET_ALERT_AVAILABLE:
            return
        # Play if enough time has passed since last alert (cooldown-based)
        if current_time - last_helmet_alert_time >= ALERT_COOLDOWN:
            last_helmet_alert_time = current_time
            should_play = True
            alert_path = HELMET_ALERT_PATH
    elif alert_type == 'distraction':
        if not DISTRACTION_ALERT_AVAILABLE:
            return
        # Play if enough time has passed since last alert (cooldown-based)
        if current_time - last_distraction_alert_time >= ALERT_COOLDOWN:
            last_distraction_alert_time = current_time
            should_play = True
            alert_path = DISTRACTION_ALERT_PATH
    
    if should_play and alert_path:
        # Play sound in background thread (non-blocking)
        def play_audio():
            try:
                print(f"[ALERT {alert_type.upper()}] Playing sound: {alert_path}")
                # Use winsound for native WAV playback (asynchronous, non-blocking)
                winsound.PlaySound(alert_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                
            except Exception as e:
                print(f"[ALERT] Error: {e}")
        
        threading.Thread(target=play_audio, daemon=True).start()

def check_helmet(image, helmet_model, helmet_mode):
    """Run helmet detection on the current frame. Returns (wearing_helmet: bool, status_text: str, bbox or None)."""
    global cached_helmet_bbox
    helmet_results = helmet_model(image, verbose=False, conf=0.7)  # Adjust confidence threshold as needed
    wearing = False
    status = "NO HELMET"
    cached_helmet_bbox = None

    if helmet_mode == 'classify':
        if helmet_results and helmet_results[0].probs is not None:
            probs = helmet_results[0].probs
            class_idx = probs.top1
            class_name = helmet_results[0].names[class_idx]
            confidence = probs.top1conf.item()
            if class_name == 'helmet':
                wearing = True
                status = f"Helmet ON ({confidence:.0%})"
            else:
                status = f"NO HELMET ({confidence:.0%})"

    elif helmet_mode == 'detect':
        if helmet_results and helmet_results[0].boxes is not None:
            boxes = helmet_results[0].boxes
            names = helmet_results[0].names
            for box in boxes:
                cls_id = int(box.cls[0])
                conf = box.conf[0].item()
                label = names[cls_id].lower()
                if 'helmet' in label and 'no' not in label and 'without' not in label:
                    wearing = True
                    status = f"Helmet ON ({conf:.0%})"
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cached_helmet_bbox = (x1, y1, x2, y2, conf)
                    break

    return wearing, status

def draw_helmet_bbox(image):
    """Draw the cached helmet bounding box on the image."""
    if cached_helmet_bbox is not None:
        x1, y1, x2, y2, conf = cached_helmet_bbox
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(image, f"Helmet {conf:.0%}", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

cap = cv2.VideoCapture(0)
frame_timestamp_ms = 0
distraction_start_time = None
is_distracted = False

while cap.isOpened():
    success, image = cap.read()
    if not success:
        continue

    start = time.time()

    # Flip the image horizontally for a later selfie-view display
    image = cv2.flip(image, 1)
    img_h, img_w, img_c = image.shape

    # ------- STATE: WAITING FOR HELMET -------
    if app_state == 'waiting_for_helmet':
        if helmet_model is not None:
            wearing, helmet_status = check_helmet(image, helmet_model, helmet_mode)

            if wearing:
                # Helmet detected — switch to face pose estimation
                app_state = 'face_pose'
                helmet_frame_counter = 0
                distraction_start_time = None
                is_distracted = False
                print("Helmet detected! Starting face pose estimation.")
            else:
                # Show prominent "Please wear your helmet" message
                play_alert_sound('helmet')
                overlay = image.copy()
                cv2.rectangle(overlay, (0, 0), (img_w, img_h), (0, 0, 200), -1)
                cv2.addWeighted(overlay, 0.4, image, 0.6, 0, image)

                msg1 = "PLEASE WEAR YOUR HELMET"
                msg2 = "System will start when helmet is detected"
                text_size1 = cv2.getTextSize(msg1, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)[0]
                text_size2 = cv2.getTextSize(msg2, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                cv2.putText(image, msg1,
                            ((img_w - text_size1[0]) // 2, img_h // 2 - 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
                cv2.putText(image, msg2,
                            ((img_w - text_size2[0]) // 2, img_h // 2 + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 255), 2)
        else:
            # No helmet model — skip straight to face pose
            app_state = 'face_pose'

        cv2.imshow('Motorcyclist Attention System', image)
        if cv2.waitKey(5) & 0xFF == 27:
            break
        continue

    # ------- STATE: FACE POSE ESTIMATION -------
    # Periodically verify helmet is still on
    helmet_still_on = True
    if helmet_model is not None:
        helmet_frame_counter += 1
        if helmet_frame_counter >= HELMET_CHECK_INTERVAL:
            helmet_frame_counter = 0
            wearing, helmet_status = check_helmet(image, helmet_model, helmet_mode)
            if not wearing:
                helmet_still_on = False

    if not helmet_still_on:
        # Helmet removed — go back to waiting state
        play_alert_sound('helmet')
        app_state = 'waiting_for_helmet'
        print("Helmet removed! Pausing face pose estimation.")
        continue

    # Display helmet status and cached bounding box
    if helmet_model is not None:
        draw_helmet_bbox(image)
        cv2.putText(image, helmet_status, (20, img_h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    # Convert BGR to RGB for mediapipe
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)

    frame_timestamp_ms += 33  # ~30fps
    results = landmarker.detect_for_video(mp_image, frame_timestamp_ms)

    face_3d = []
    face_2d = []

    if results.face_landmarks:
        for face_landmarks in results.face_landmarks:
            for idx, lm in enumerate(face_landmarks):
                if idx == 33 or idx == 263 or idx == 1 or idx == 61 or idx == 291 or idx == 199:
                    if idx == 1:
                        nose_2d = (lm.x * img_w, lm.y * img_h)
                        nose_3d = (lm.x * img_w, lm.y * img_h, lm.z * 3000)

                    x, y = int(lm.x * img_w), int(lm.y * img_h)

                    # Get the 2D Coordinates
                    face_2d.append([x, y])

                    # Get the 3D Coordinates
                    face_3d.append([x, y, lm.z])       
            
            # Convert it to the NumPy array
            face_2d = np.array(face_2d, dtype=np.float64)

            # Convert it to the NumPy array
            face_3d = np.array(face_3d, dtype=np.float64)

            # The camera matrix
            focal_length = 1 * img_w

            cam_matrix = np.array([ [focal_length, 0, img_h / 2],
                                    [0, focal_length, img_w / 2],
                                    [0, 0, 1]])

            # The distortion parameters
            dist_matrix = np.zeros((4, 1), dtype=np.float64)

            # Solve PnP
            success, rot_vec, trans_vec = cv2.solvePnP(face_3d, face_2d, cam_matrix, dist_matrix)

            # Get rotational matrix
            rmat, jac = cv2.Rodrigues(rot_vec)

            # Get angles
            angles, mtxR, mtxQ, Qx, Qy, Qz = cv2.RQDecomp3x3(rmat)

            # Get the y rotation degree
            x = angles[0] * 360
            y = angles[1] * 360
            z = angles[2] * 360
          

            # Display head direction (sensitive threshold)
            if y < -10:
                text = "Looking Left"
            elif y > 10:
                text = "Looking Right"
            elif x < -10:
                text = "Looking Down"
            elif x > 10:
                text = "Looking Up"
            else:
                text = "Forward"

            # Distraction timing logic
            looking_away = (abs(y) > DISTRACTION_ANGLE_THRESHOLD or
                            x < -DISTRACTION_ANGLE_THRESHOLD or
                            x > 20)  # looking up has a higher threshold

            if looking_away:
                if distraction_start_time is None:
                    distraction_start_time = time.time()
                elapsed = time.time() - distraction_start_time
                if elapsed >= DISTRACTION_TIME_THRESHOLD:
                    is_distracted = True
                    # Play alert every 2 seconds while distracted
                    play_alert_sound('distraction')
            else:
                distraction_start_time = None
                is_distracted = False

            # Display the nose direction
            nose_3d_projection, jacobian = cv2.projectPoints(nose_3d, rot_vec, trans_vec, cam_matrix, dist_matrix)

            p1 = (int(nose_2d[0]), int(nose_2d[1]))
            p2 = (int(nose_2d[0] + y * 10) , int(nose_2d[1] - x * 10))
            
            cv2.line(image, p1, p2, (255, 0, 0), 3)

            # Add the text on the image
            direction_color = (0, 0, 255) if text != "Forward" else (0, 255, 0)
            cv2.putText(image, text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 2, direction_color, 2)
            cv2.putText(image, "x: " + str(np.round(x,2)), (500, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(image, "y: " + str(np.round(y,2)), (500, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(image, "z: " + str(np.round(z,2)), (500, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            # Show distraction warning
            if is_distracted:
                # Flashing red overlay
                overlay = image.copy()
                cv2.rectangle(overlay, (0, 0), (img_w, img_h), (0, 0, 255), -1)
                cv2.addWeighted(overlay, 0.3, image, 0.7, 0, image)
                distraction_text = "!! DISTRACTED - LOOK AHEAD !!"
                distraction_text_size = cv2.getTextSize(distraction_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                distraction_x = (img_w - distraction_text_size[0]) // 2
                cv2.putText(image, distraction_text, (distraction_x, img_h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            elif distraction_start_time is not None:
                # Show countdown progress bar
                elapsed = time.time() - distraction_start_time
                bar_width = int((elapsed / DISTRACTION_TIME_THRESHOLD) * (img_w - 40))
                cv2.rectangle(image, (20, img_h - 50), (20 + bar_width, img_h - 30), (0, 165, 255), -1)
                cv2.rectangle(image, (20, img_h - 50), (img_w - 20, img_h - 30), (255, 255, 255), 2)
                cv2.putText(image, f"Distraction warning: {elapsed:.1f}s / {DISTRACTION_TIME_THRESHOLD}s",
                            (20, img_h - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)


        end = time.time()
        totalTime = end - start

        fps = 1 / totalTime
        #print("FPS: ", fps)

        fps_text = f'FPS: {int(fps)}'
        text_size = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 2)[0]
        cv2.putText(image, fps_text, (img_w - text_size[0] - 10, img_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0,255,0), 2)

        # Draw face landmarks
        for face_lms in results.face_landmarks:
            connections = FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION
            for conn in connections:
                pt1 = face_lms[conn.start]
                pt2 = face_lms[conn.end]
                x1, y1 = int(pt1.x * img_w), int(pt1.y * img_h)
                x2, y2 = int(pt2.x * img_w), int(pt2.y * img_h)
                cv2.line(image, (x1, y1), (x2, y2), (200, 200, 200), 1)


    cv2.imshow('Motorcyclist Attention System', image)

    if cv2.waitKey(5) & 0xFF == 27:
        break

landmarker.close()
cap.release()
cv2.destroyAllWindows()