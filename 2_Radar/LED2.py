import time
import threading
import os

try:
    import adafruit_pixelbuf
    import board
    from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    ADAFRUIT_AVAILABLE = True
except ImportError as e:
    ADAFRUIT_AVAILABLE = False
    print(f"[WARNING] Adafruit libraries not available: {e}")

MAIN_PIN = None
NUM_LOGICAL_PIXELS = 8
NUM_PHYSICAL_PIXELS = 16

COLOR_FAST = [0, 255, 0]
COLOR_MID = [0, 255, 255]
COLOR_SLOW = [0, 0, 255]
COLOR_OFF = [0, 0, 0]

MID_SPEED_KMH = 4.0
FAST_SPEED_KMH = 5.0
AEB_DIST_M = 3.0
FCW_DIST_M = 8.0
BSM_DIST_LEVEL_1 = 20.0
BSM_DIST_LEVEL_2 = 15.0
BSM_DIST_LEVEL_3 = 10.0
AUDIO_DEBOUNCE_SEC = 2.0

_state_lock = threading.Lock()
_render_lock = threading.Lock()
_init_lock = threading.Lock()
_in_memory_state = {"sources": {}}

def _blank_strip():
    return [COLOR_OFF.copy() for _ in range(NUM_LOGICAL_PIXELS)]

physical_pixels = None
led_controller = None

if ADAFRUIT_AVAILABLE:
    class Pi5Pixelbuf(adafruit_pixelbuf.PixelBuf):
        def __init__(self, pin, size, **kwargs):
            self._pin = pin
            super().__init__(size=size, **kwargs)
        def _transmit(self, buf):
            neopixel_write(self._pin, buf)
else:
    class Pi5Pixelbuf:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Adafruit NeoPixel libraries are not available")

def init_neopixel():
    global physical_pixels, MAIN_PIN
    with _init_lock:
        if physical_pixels is not None: return physical_pixels
        if not ADAFRUIT_AVAILABLE: return None
        try:
            MAIN_PIN = board.D17
            physical_pixels = Pi5Pixelbuf(MAIN_PIN, NUM_PHYSICAL_PIXELS, auto_write=False, byteorder="BGR")
            print(f"[NEOPIXEL] Daisy-chained strip on GPIO17, {NUM_PHYSICAL_PIXELS} LEDs total")
            return physical_pixels
        except Exception as e:
            print(f"[ERROR] Failed to initialize neopixels: {e}")
            return None

def _coerce_source_buffers(source_state):
    left = source_state.get("left", _blank_strip())
    right = source_state.get("right", _blank_strip())
    if not isinstance(left, list) or len(left) != NUM_LOGICAL_PIXELS: left = _blank_strip()
    if not isinstance(right, list) or len(right) != NUM_LOGICAL_PIXELS: right = _blank_strip()
    return left, right

class RadarLEDController:
    def __init__(self, physical_pixels_obj=None, num_logical_leds=8):
        self.pixels = physical_pixels_obj
        self.num_leds = num_logical_leds
        self.last_alert_time = 0
        self.current_audio_state = "SAFE"

    def ensure_initialized(self):
        if self.pixels is None:
            self.pixels = init_neopixel()
        return self.pixels is not None

    def _render_composed(self):
        if not self.ensure_initialized(): return False
        composed_left = _blank_strip()
        composed_right = _blank_strip()

        with _state_lock:
            sources = list(_in_memory_state.get("sources", {}).values())

        for source_state in sources:
            src_left, src_right = _coerce_source_buffers(source_state)
            for i in range(self.num_leds):
                if src_left[i] != COLOR_OFF: composed_left[i] = src_left[i]
                if src_right[i] != COLOR_OFF: composed_right[i] = src_right[i]

        if _render_lock.acquire(blocking=False):
            try:
                for i in range(self.num_leds):
                    self.pixels[i] = tuple(composed_left[i])
                    self.pixels[i + 8] = tuple(composed_right[i])
                self.pixels.show()
                return True
            finally:
                _render_lock.release()
        return False

    def publish(self, source, left_buffer, right_buffer):
        if len(left_buffer) != self.num_leds or len(right_buffer) != self.num_leds: return False
        normalized_left = [[int(c) for c in color] for color in left_buffer]
        normalized_right = [[int(c) for c in color] for color in right_buffer]

        with _state_lock:
            _in_memory_state["sources"][source] = {"left": normalized_left, "right": normalized_right}
        return self._render_composed()

    def clear_source(self, source):
        with _state_lock:
            _in_memory_state.get("sources", {}).pop(source, None)
        return self._render_composed()

    def update_ld2451(self, distance_m, speed_kmh, source="ld2451"):
        left = _blank_strip()
        right = _blank_strip()
        current_time = time.time()
        new_audio_state = "SAFE"

        if distance_m <= AEB_DIST_M and speed_kmh >= FAST_SPEED_KMH:
            color = COLOR_FAST
            new_audio_state = "AEB"
        elif distance_m <= FCW_DIST_M or speed_kmh >= MID_SPEED_KMH:
            color = COLOR_MID
            if current_time - self.last_alert_time > AUDIO_DEBOUNCE_SEC:
                new_audio_state = "FCW"
                self.last_alert_time = current_time
        else:
            color = COLOR_OFF

        # Only broadcast to the GUI if the audio state changes or debounces
        if new_audio_state == "FCW" or new_audio_state != self.current_audio_state:
            print(f"__AUDIO_TRIGGER__:{new_audio_state}")
            self.current_audio_state = new_audio_state

        left[0] = left[1] = color
        right[6] = right[7] = color
        return self.publish(source, left, right)

    def update_ld2417(self, left_target=None, right_target=None, source="ld2417"):
        left = _blank_strip()
        right = _blank_strip()
        self._fill_ld2417_side(left, left_target, start_pixel=4)
        self._fill_ld2417_side(right, right_target, start_pixel=0)
        return self.publish(source, left, right)

    def _fill_ld2417_side(self, strip, target_info, start_pixel=0):
        if target_info is None: return
        distance_m, speed_kmh = target_info

        if speed_kmh >= FAST_SPEED_KMH: color = COLOR_FAST
        elif speed_kmh >= MID_SPEED_KMH: color = COLOR_MID
        else: color = COLOR_SLOW

        if distance_m >= BSM_DIST_LEVEL_1: active = [start_pixel + 3]
        elif distance_m >= BSM_DIST_LEVEL_2: active = [start_pixel + 2, start_pixel + 3]
        elif distance_m >= BSM_DIST_LEVEL_3: active = [start_pixel + 1, start_pixel + 2, start_pixel + 3]
        else: active = [start_pixel, start_pixel + 1, start_pixel + 2, start_pixel + 3]

        for idx in active:
            strip[idx] = color

    def off(self, source=None):
        if source is None:
            with _state_lock:
                _in_memory_state["sources"].clear()
            return self._render_composed()
        return self.clear_source(source)

    def cleanup(self):
        self.off() 

led_controller = RadarLEDController(None, NUM_LOGICAL_PIXELS)