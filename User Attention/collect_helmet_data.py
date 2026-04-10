"""
Helmet Detection Data Collection Tool
=====================================
Use this script to collect training images for the helmet classifier.

Instructions:
1. Run this script
2. Press 'h' to capture frames labelled as "helmet"
3. Press 'n' to capture frames labelled as "no_helmet"
4. Press 'q' to quit

Images are saved to dataset/helmet/ and dataset/no_helmet/
After collecting enough images (~50-100 per class), run train_helmet_model.py
"""

import cv2
import os
import time

DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dataset')
HELMET_DIR = os.path.join(DATASET_DIR, 'train', 'helmet')
NO_HELMET_DIR = os.path.join(DATASET_DIR, 'train', 'no_helmet')

os.makedirs(HELMET_DIR, exist_ok=True)
os.makedirs(NO_HELMET_DIR, exist_ok=True)

cap = cv2.VideoCapture(0)
helmet_count = len(os.listdir(HELMET_DIR))
no_helmet_count = len(os.listdir(NO_HELMET_DIR))

print("Press 'h' to save as HELMET, 'n' to save as NO HELMET, 'q' to quit")

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        continue

    frame = cv2.flip(frame, 1)
    display = frame.copy()

    cv2.putText(display, f"Helmet: {helmet_count} | No Helmet: {no_helmet_count}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(display, "H=helmet  N=no_helmet  Q=quit",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.imshow('Collect Helmet Data', display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('h'):
        filename = os.path.join(HELMET_DIR, f'helmet_{int(time.time()*1000)}.jpg')
        cv2.imwrite(filename, frame)
        helmet_count += 1
        print(f"Saved helmet image ({helmet_count})")
    elif key == ord('n'):
        filename = os.path.join(NO_HELMET_DIR, f'no_helmet_{int(time.time()*1000)}.jpg')
        cv2.imwrite(filename, frame)
        no_helmet_count += 1
        print(f"Saved no_helmet image ({no_helmet_count})")
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print(f"\nDone! Collected {helmet_count} helmet and {no_helmet_count} no_helmet images.")
print("Now run: python train_helmet_model.py")
