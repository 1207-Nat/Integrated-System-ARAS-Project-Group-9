import time

try:
    import adafruit_pixelbuf
    import board
    from adafruit_led_animation.animation.rainbow import Rainbow
    from adafruit_led_animation.animation.rainbowchase import RainbowChase
    from adafruit_led_animation.animation.rainbowcomet import RainbowComet
    from adafruit_led_animation.animation.rainbowsparkle import RainbowSparkle
    from adafruit_led_animation.sequence import AnimationSequence
    from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    ADAFRUIT_AVAILABLE = True
except ImportError as e:
    ADAFRUIT_AVAILABLE = False
    print(f"[WARNING] Adafruit libraries not available: {e}")

LEFT_PIN = None   # GPIO 17
RIGHT_PIN = None  # GPIO 27
num_pixels = 8

# NOTE: The LD2451 data format provides:
#   - Distance in meters (0–100 m)
#   - Speed value in km/h  (0–120 km/h)
# The thresholds below assume the values passed into update_by_radar()
# are in **meters** for distance and **km/h** for speed.
#
# These values are tuned for **on-foot testing** (people walking/running),
# not for cars. Adjust as needed for your scenario.

# Radar distance thresholds (meters) for human-scale testing
CLOSE_THRESHOLD = 3         # <= 5  m : very close / emergency (red)
FAR_THRESHOLD = 8          # 5–20 m : warning zone (yellow)

# Speed thresholds (km/h) for human walking/running
#SLOW_SPEED = 7              # ~2 km/h : slow movement (reference)
MID_SPEED = 7               # 4–8 km/h : fast walk (yellow)
FAST_SPEED = 14              # >= 8 km/h : jog/run (red)

# Global instances - initialized lazily on first use
left_pixels = None
right_pixels = None
led_controller = None

class Pi5Pixelbuf(adafruit_pixelbuf.PixelBuf):
    def __init__(self, pin, size, **kwargs):
        self._pin = pin
        super().__init__(size=size, **kwargs)

    def _transmit(self, buf):
        neopixel_write(self._pin, buf)

def init_neopixel():
    """Initialize left/right neopixel strips on first use.

    Left strip  : GPIO 17 (board.D17)
    Right strip : GPIO 27 (board.D27)
    """
    global left_pixels, right_pixels, LEFT_PIN, RIGHT_PIN

    # If already initialized, just return existing objects
    if left_pixels is not None and right_pixels is not None:
        return left_pixels, right_pixels

    if not ADAFRUIT_AVAILABLE:
        print("[ERROR] Cannot initialize neopixel - adafruit libraries not available")
        return None, None

    try:
        LEFT_PIN = board.D17
        RIGHT_PIN = board.D27

        left_pixels = Pi5Pixelbuf(LEFT_PIN, num_pixels, auto_write=True, byteorder="BGR")
        right_pixels = Pi5Pixelbuf(RIGHT_PIN, num_pixels, auto_write=True, byteorder="BGR")
        print(f"[NEOPIXEL] Left strip on GPIO17 (board.D17), right strip on GPIO27 (board.D27), {num_pixels} LEDs each")
        return left_pixels, right_pixels
    except Exception as e:
        print(f"[ERROR] Failed to initialize neopixels: {e}")
        return None, None

class RadarLEDController:
    """Control LED animations based on radar detection data"""
    
    def __init__(self, left_pixels_obj=None, right_pixels_obj=None, num_leds=8):
        self.left_pixels = left_pixels_obj
        self.right_pixels = right_pixels_obj
        self.num_leds = num_leds
        self.last_animation_time = time.time()
        self.current_mode = "idle"
    
    def ensure_initialized(self):
        """Ensure both left and right strips are initialized before use"""
        if self.left_pixels is None or self.right_pixels is None:
            self.left_pixels, self.right_pixels = init_neopixel()
        return self.left_pixels is not None and self.right_pixels is not None
        
    def set_color_solid(self, color):
        """Set all LEDs to a solid color"""
        if not self.ensure_initialized():
            return False
        for i in range(self.num_leds):
            self.left_pixels[i] = color
            self.right_pixels[i] = color
        self.left_pixels.show()
        self.right_pixels.show()
        return True
    
    def set_color_gradient(self, start_color, end_color, brightness=1.0):
        """Set LEDs with a gradient from start to end color"""
        if not self.ensure_initialized():
            return False
        for i in range(self.num_leds):
            ratio = i / max(self.num_leds - 1, 1)
            r = int(start_color[0] * (1 - ratio) + end_color[0] * ratio)
            g = int(start_color[1] * (1 - ratio) + end_color[1] * ratio)
            b = int(start_color[2] * (1 - ratio) + end_color[2] * ratio)
            
            # Apply brightness
            r = int(r * brightness)
            g = int(g * brightness)
            b = int(b * brightness)

            color = (r, g, b)
            self.left_pixels[i] = color
            self.right_pixels[i] = color
        self.left_pixels.show()
        self.right_pixels.show()
        return True
    
    def strobe(self, color, speed=0.1, num_leds=4):
        """Strobe effect on specified number of LEDs"""
        if not self.ensure_initialized():
            return False
        # Toggle between full brightness and off
        brightness = 1.0 if (int(time.time() * speed) % 2) == 0 else 0.0
        
        r = int(color[0] * brightness)
        g = int(color[1] * brightness)
        b = int(color[2] * brightness)
        
        strobed_color = (r, g, b)
        
        # Set only the first num_leds to strobe on both strips
        for i in range(num_leds):
            self.left_pixels[i] = strobed_color
            self.right_pixels[i] = strobed_color

        # Turn off remaining LEDs
        for i in range(num_leds, self.num_leds):
            self.left_pixels[i] = (0, 0, 0)
            self.right_pixels[i] = (0, 0, 0)

        self.left_pixels.show()
        self.right_pixels.show()
        return True
    
    def get_color_by_distance(self, distance):
        """Return color based on distance threshold"""
        # Kept for compatibility (not used by the new indicator logic)
        if distance < CLOSE_THRESHOLD:
            return (0, 255, 0)   # RED   - very close (BGR format)
        elif distance < FAR_THRESHOLD:
            return (0, 255, 255) # YELLOW - warning range (BGR format)
        else:
            return (0, 0, 0)     # OFF - beyond range
    
    def get_speed_animation(self, speed):
        """Return animation speed based on target speed"""
        # Map speed (0-150+ cm/s) to animation speed (0.01-0.1)
        normalized_speed = min(speed / FAST_SPEED, 1.0)
        return 0.01 + (normalized_speed * 0.09)
    
    def update_by_radar(self, distance, speed):
        """Update LEDs using a *combined* distance + speed hazard level.

        Logic (units: meters and km/h):
        - RED (emergency):
            distance <= CLOSE_THRESHOLD  AND  speed >= FAST_SPEED
        - YELLOW (intermediate warning):
            otherwise, if distance <= FAR_THRESHOLD OR speed >= MID_SPEED
        - OFF (safe):
            distance > FAR_THRESHOLD AND speed < MID_SPEED

        Output:
        - LEFT strip LED  index 0
        - RIGHT strip LED index num_leds-1
        are set to the SAME colour representing the combined state.
        All other LEDs are off.
        """

        if not self.ensure_initialized():
            return False

        # Decide combined hazard colour
        if distance <= CLOSE_THRESHOLD and speed >= FAST_SPEED:
            color = (0, 255, 0)        # RED   - emergency (close + fast)
        elif distance <= FAR_THRESHOLD or speed >= MID_SPEED:
            color = (0, 255, 255)      # YELLOW - intermediate warning
        else:
            color = (0, 0, 0)          # OFF   - safe

        # Clear all LEDs on both strips
        for i in range(1):
            self.left_pixels[i] = (0, 0, 0)
            self.right_pixels[i] = (0, 0, 0)

        # Set combined indicator on LED0 (left) and LED7 (right)
        self.left_pixels[0] = color
        self.right_pixels[0] = color

        self.left_pixels.show()
        self.right_pixels.show()
        return True
        
    def idle(self):
        """Idle state - turn off"""
        self.off()
    
    def off(self):
        """Turn off all LEDs"""
        self.set_color_solid((0, 0, 0))

# Create LED controller (lazy initialization - doesn't init pixels until first use)
led_controller = RadarLEDController(None, None, num_pixels)

# Example usage - uncomment to test:
# if __name__ == "__main__":
#     try:
#         while True:
#             # Simulate radar data
#             distance = 10  # meters
#             speed = 5      # km/h
#
#             led_controller.update_by_radar(distance, speed)
#             time.sleep(0.05)
#     finally:
#         led_controller.off()


