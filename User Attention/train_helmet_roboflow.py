"""
Train Helmet Detection from a Roboflow Dataset
================================================

How to use:
1. Go to your Roboflow dataset page
2. Click "Download Dataset" -> Choose "YOLOv8" format
3. Select "download zip" and extract it into this project folder
   so you have a structure like:

   User Attention/
     roboflow_dataset/       <-- rename the extracted folder to this
       data.yaml
       train/
         images/
         labels/
       valid/
         images/
         labels/

4. Run this script:
       python train_helmet_roboflow.py

   OR use the Roboflow API method (fill in your details below):
       python train_helmet_roboflow.py --api

Output:
    helmet_detector.pt  (YOLOv8 detection model)
"""

import sys
import os
import shutil

sys.path.insert(0, r'C:\pylibs')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# =====================================================
# OPTION 1: Download via Roboflow API (fill these in)
# =====================================================
ROBOFLOW_API_KEY = ""       # Your Roboflow API key
ROBOFLOW_WORKSPACE = ""     # e.g. "my-workspace"
ROBOFLOW_PROJECT = ""       # e.g. "helmet-detection-xxxxx"
ROBOFLOW_VERSION = 1        # Dataset version number

# =====================================================
# OPTION 2: Manual download path
# =====================================================
DATASET_DIR = os.path.join(SCRIPT_DIR, 'Datasets')


def download_with_api():
    """Download dataset using Roboflow Python API."""
    try:
        from roboflow import Roboflow
    except ImportError:
        print("Installing roboflow package...")
        import subprocess
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', 'roboflow',
            '--target', r'C:\pylibs'
        ])
        from roboflow import Roboflow

    rf = Roboflow(api_key=ROBOFLOW_API_KEY)
    project = rf.workspace(ROBOFLOW_WORKSPACE).project(ROBOFLOW_PROJECT)
    version = project.version(ROBOFLOW_VERSION)
    dataset = version.download("yolov8", location=DATASET_DIR)
    return DATASET_DIR


def find_data_yaml(dataset_dir):
    """Find the data.yaml file in the dataset directory."""
    for root, dirs, files in os.walk(dataset_dir):
        for f in files:
            if f == 'data.yaml':
                return os.path.join(root, f)
    return None


def train_model(data_yaml_path):
    """Train a YOLOv8 detection model on the dataset."""
    print("Loading YOLO model (this may take a moment)...", flush=True)
    from ultralytics import YOLO

    print(f"Using dataset config: {data_yaml_path}", flush=True)

    # Use YOLOv8 nano for speed (good for Raspberry Pi / real-time use)
    model = YOLO('yolov8n.pt')

    # Use GPU if available, otherwise CPU
    import torch
    device = 0 if torch.cuda.is_available() else 'cpu'
    print(f"Training on: {'GPU - ' + torch.cuda.get_device_name(0) if device == 0 else 'CPU'}")

    results = model.train(
        data=data_yaml_path,
        epochs=350,
        imgsz=640,
        batch=16,
        workers=4,
        device=device,
        project=SCRIPT_DIR,
        name='helmet_roboflow_training',
        exist_ok=True,
        # Zoom: scale=0.9 means ±90% random resize (simulates near/far objects)
        scale=0.9,
        # Brightness: hsv_v=0.6 varies brightness ±60%
        hsv_v=0.6,
        # Also vary saturation and hue slightly for robustness
        hsv_h=0.015,
        hsv_s=0.7,
    )

    # Copy best model
    best_path = os.path.join(SCRIPT_DIR, 'helmet_roboflow_training', 'weights', 'best.pt')
    output_path = os.path.join(SCRIPT_DIR, 'helmet_detector.pt')

    if os.path.exists(best_path):
        shutil.copy2(best_path, output_path)
        print(f"\nModel saved to: {output_path}")
        print("Head_orientation.py will automatically use this model.")
    else:
        print("Training may have failed. Check output above.")


if __name__ == '__main__':
    use_api = '--api' in sys.argv

    if use_api:
        if not ROBOFLOW_API_KEY:
            print("Error: Fill in ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE,")
            print("ROBOFLOW_PROJECT, and ROBOFLOW_VERSION at the top of this script.")
            sys.exit(1)
        print("Downloading dataset from Roboflow API...")
        dataset_path = download_with_api()
    else:
        dataset_path = DATASET_DIR

    if not os.path.exists(dataset_path):
        print(f"Error: Dataset folder not found at: {dataset_path}")
        print()
        print("Either:")
        print("  1. Download from Roboflow website as 'YOLOv8' format,")
        print("     extract to 'roboflow_dataset/' folder here")
        print("  2. Fill in API details at top of this script and run with --api")
        sys.exit(1)

    data_yaml = find_data_yaml(dataset_path)
    if not data_yaml:
        print(f"Error: No data.yaml found in {dataset_path}")
        print("Make sure you downloaded in YOLOv8 format.")
        sys.exit(1)

    train_model(data_yaml)
