"""
Train Helmet Detection Model
==============================
Trains a YOLOv8 image classifier on your collected helmet/no_helmet dataset.

Prerequisites:
1. Run collect_helmet_data.py first to gather training images
2. Ensure you have at least ~50 images per class

Usage:
    python train_helmet_model.py

Output:
    helmet_classifier.pt  (saved in this directory)
"""

import sys
import os

# Add pylibs to path for torch/ultralytics
sys.path.insert(0, r'C:\pylibs')

from ultralytics import YOLO

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(SCRIPT_DIR, 'dataset')

# Check dataset exists
train_dir = os.path.join(DATASET_DIR, 'train')
if not os.path.exists(train_dir):
    print("Error: No dataset found. Run collect_helmet_data.py first.")
    sys.exit(1)

helmet_count = len(os.listdir(os.path.join(train_dir, 'helmet'))) if os.path.exists(os.path.join(train_dir, 'helmet')) else 0
no_helmet_count = len(os.listdir(os.path.join(train_dir, 'no_helmet'))) if os.path.exists(os.path.join(train_dir, 'no_helmet')) else 0

print(f"Dataset: {helmet_count} helmet images, {no_helmet_count} no_helmet images")

if helmet_count < 10 or no_helmet_count < 10:
    print("Warning: You should collect at least 50 images per class for good results.")
    print("Recommend: 100+ images per class.")

# Use GPU if available
import torch
device = 0 if torch.cuda.is_available() else 'cpu'
print(f"Training on: {'GPU - ' + torch.cuda.get_device_name(0) if device == 0 else 'CPU'}")

# Load a pre-trained YOLOv8 classification model (nano for speed)
model = YOLO('yolov8n-cls.pt')

# Train the classifier
results = model.train(
    data=DATASET_DIR,
    epochs=30,
    imgsz=224,
    batch=32,
    device=device,
    project=SCRIPT_DIR,
    name='helmet_training',
    exist_ok=True
)

# Copy the best model to the project directory
best_model_path = os.path.join(SCRIPT_DIR, 'helmet_training', 'weights', 'best.pt')
output_path = os.path.join(SCRIPT_DIR, 'helmet_classifier.pt')

if os.path.exists(best_model_path):
    import shutil
    shutil.copy2(best_model_path, output_path)
    print(f"\nModel saved to: {output_path}")
    print("You can now run Head_orientation.py - it will use the helmet detector automatically.")
else:
    print("Training may have failed. Check the output above for errors.")
