import threading
import time
import sys

# Import the readers and configurations from your existing scripts
from hlk2451 import read_radar_stream as read_front
from hlk2451 import RADAR_PORT as PORT_FRONT, BAUD_RATE as BAUD_FRONT

from hlk2417 import read_radar_stream as read_rear
from hlk2417 import RADAR_PORT as PORT_REAR, BAUD_RATE as BAUD_REAR

# Import the shared LED controller
from LED2 import led_controller 

# --- THREAD LINEAGE TRACKING ---
thread_prefixes = {}
original_thread_start = threading.Thread.start

def custom_thread_start(self, *args, **kwargs):
    parent_id = threading.get_ident()
    prefix = thread_prefixes.get(parent_id, None)
    
    original_thread_start(self, *args, **kwargs)
    
    if prefix and self.ident:
        thread_prefixes[self.ident] = prefix

threading.Thread.start = custom_thread_start

# --- SAFE STDOUT ROUTER ---
class LineageLogRouter:
    """Buffers fragmented print statements so multi-line radar logs don't mix."""
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.buffers = {}
        self.lock = threading.Lock()

    def write(self, msg):
        tid = threading.get_ident()
        prefix = thread_prefixes.get(tid, None)
        
        with self.lock:
            if not prefix:
                self.original_stdout.write(msg)
                return

            if tid not in self.buffers:
                self.buffers[tid] = ""
            
            self.buffers[tid] += msg
            
            while '\n' in self.buffers[tid]:
                line, self.buffers[tid] = self.buffers[tid].split('\n', 1)
                self.original_stdout.write(f"{prefix} {line}\n")

    def flush(self):
        with self.lock:
            self.original_stdout.flush()

sys.stdout = LineageLogRouter(sys.stdout)
sys.stderr = LineageLogRouter(sys.stderr)

def start_front_radar():
    thread_prefixes[threading.get_ident()] = "[LD2451_FRONT]"
    print(f"Starting Front Radar on {PORT_FRONT}")
    read_front(PORT_FRONT, BAUD_FRONT, duration=None)

def start_rear_radar():
    thread_prefixes[threading.get_ident()] = "[LD2417_BACK]"
    print(f"Starting Rear/Side Radar on {PORT_REAR}")
    read_rear(PORT_REAR, BAUD_REAR, duration=None)

def main():
    print("========================================")
    print("Starting Standalone Unified ARAS System")
    print("========================================")

    # Force LED initialization in the main thread before spawning radar children
    print("[SYSTEM] Pre-initializing hardware...")
    if not led_controller.ensure_initialized():
        print("\n[CRITICAL ERROR] LEDs failed to initialize!")
        print("Did you forget to use 'sudo -E'? The NeoPixels require root hardware access.")
        sys.exit(1)
        
    print("[SYSTEM] Hardware successfully claimed. Starting radar threads...\n")

    t_front = threading.Thread(target=start_front_radar, daemon=True)
    t_rear = threading.Thread(target=start_rear_radar, daemon=True)

    t_front.start()
    t_rear.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Ctrl+C detected. Shutting down unified ARAS system...")
        if hasattr(led_controller, 'cleanup'):
            led_controller.cleanup()
        else:
            led_controller.off()
        sys.exit(0)

if __name__ == "__main__":
    main()