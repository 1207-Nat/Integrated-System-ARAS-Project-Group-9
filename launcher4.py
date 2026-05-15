import os
import sys

# --- THE CHEAT CODE: Force Python to look in the User PIP folder ---
sys.path.append("/usr/local/lib/python3.12/site-packages")
sys.path.append("/home/group9/.local/lib/python3.12/site-packages")

import shutil
import threading
import subprocess
import time
import base64
import json
import math
import cv2

from dataclasses import dataclass, field
from typing import List, Optional
from media_browser_widget import MediaBrowserWidget

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QPushButton, QToolBar, QWidget, 
    QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QSizePolicy, QPinchGesture, QListWidget, QComboBox, QTreeView,
    QFileSystemModel, QAbstractItemView, QHeaderView, QMessageBox,
    QScroller, QScrollerProperties, QSlider, QStyle, QLineEdit,QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QEvent, QTimer, QSize
from PyQt5.QtGui import QFont, QPixmap, QImage, QPainter, QColor, QIcon

SETTINGS_FILE = "aras_settings.json"

#=================================================================================
# Tier I: Orchestration (The "What Runs")
#=================================================================================
def sync_system_time():
    print("[SYSTEM] Checking internet connection for time sync...")
    try:
        subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "systemctl", "restart", "systemd-timesyncd"], timeout=5)
    except:
        pass
    
@dataclass
class ModuleConfig:
    name: str
    script_relative_path: str
    cwd_relative: Optional[str] = None
    python_executable: Optional[str] = None
    startup_delay: float = 0.0

class LogSignal(QObject):
    new_log = pyqtSignal(str, str)
    new_frame = pyqtSignal(bytes)
    new_detection = pyqtSignal(str)
    new_gps = pyqtSignal(dict)
    new_ups = pyqtSignal(dict)
    new_alert = pyqtSignal(str, dict)
    play_audio = pyqtSignal(str) 
    new_sysmon = pyqtSignal(dict)
    emergency_triggered = pyqtSignal(str)
    qr_url_ready = pyqtSignal(str)

@dataclass
class ModuleRunner:
    config: ModuleConfig
    project_root: str
    log_signal: Optional[LogSignal] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self) -> None:
        if self.config.startup_delay > 0: time.sleep(self.config.startup_delay)
        script_path = os.path.join(self.project_root, self.config.script_relative_path)
        cwd = os.path.join(self.project_root, self.config.cwd_relative) if self.config.cwd_relative else self.project_root
        
        if self.config.python_executable:
            cmd = self.config.python_executable.split()
            cmd.append("-u") 
        else:
            cmd = ["python3", "-u"]
            
        cmd.append(script_path)

        self.process = subprocess.Popen(
            cmd, 
            cwd=cwd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            bufsize=1, 
            env=os.environ.copy(),
            close_fds=True 
        )

        for line in iter(self.process.stdout.readline, ''):
            if not line: break
            line_str = line.strip()
            
            if "__AUDIO_TRIGGER__:" in line_str:
                alert_type = line_str.split("__AUDIO_TRIGGER__:")[1].strip()
                self.log_signal.play_audio.emit(alert_type)
            elif line_str.startswith("__EMERGENCY_BRAKE_DETECTED__"):
                self.log_signal.emergency_triggered.emit("SUDDEN_DECELERATION")
            elif line_str.startswith("__FRONT__:"):
                self.log_signal.new_log.emit("LD2451_Front", line_str.split(":", 1)[1])
            elif line_str.startswith("__BACK__:"):
                self.log_signal.new_log.emit("LD2417_Back", line_str.split(":", 1)[1])
            elif line_str.startswith("__FRAME__:"):
                try: self.log_signal.new_frame.emit(base64.b64decode(line_str.split(":", 1)[1]))
                except: pass
            elif line_str.startswith("__DETECT__:"):
                self.log_signal.new_detection.emit(line_str.split(":", 1)[1])
            elif line_str.startswith("__GPS__:"):
                try: self.log_signal.new_gps.emit(json.loads(line_str.split(":", 1)[1]))
                except: pass
            elif line_str.startswith("__UPS__:"):
                try: self.log_signal.new_ups.emit(json.loads(line_str.split(":", 1)[1]))
                except: pass
            elif line_str.startswith("__SYSMON__:"):
                try: self.log_signal.new_sysmon.emit(json.loads(line_str.split(":", 1)[1]))
                except: pass
            elif line_str.startswith("__LOG__:"):
                self.log_signal.new_log.emit(self.config.name, line_str.split(":", 1)[1])
            else: 
                if self.config.name == "Integrated_Radar":
                    self.log_signal.new_log.emit("LD2451_Front", f"[SYS] {line_str}")
                    self.log_signal.new_log.emit("LD2417_Back", f"[SYS] {line_str}")
                else:
                    self.log_signal.new_log.emit(self.config.name, line_str)

    def stop(self) -> None:
        self.stop_event.set()
        if self.process: 
            if self.config.python_executable and "sudo" in self.config.python_executable:
                script_name = os.path.basename(self.config.script_relative_path)
                subprocess.run(["sudo", "pkill", "-15", "-f", script_name])
            else:
                self.process.terminate() 
            
            try:
                self.process.wait(timeout=2.0) 
            except subprocess.TimeoutExpired:
                if self.config.python_executable and "sudo" in self.config.python_executable:
                    script_name = os.path.basename(self.config.script_relative_path)
                    subprocess.run(["sudo", "pkill", "-9", "-f", script_name])
                else:
                    self.process.kill()

def build_modules(root: str) -> List[ModuleRunner]:
    return [
        ModuleRunner(ModuleConfig("Integrated_Radar", os.path.join("2_Radar", "integrated.py"), cwd_relative="2_Radar", python_executable="sudo -n -E /usr/local/bin/python3.12"), root),
        ModuleRunner(ModuleConfig("AI_Vision", os.path.join("1_TrafficSign", "Detection_traffic_headless.py"), cwd_relative="1_TrafficSign"), root),
        #ModuleRunner(ModuleConfig("GPS", os.path.join("3_LC76G_GPS_Module", "gps_headless.py"), startup_delay=0.1), root),
        ModuleRunner(ModuleConfig("GPS", os.path.join("3_LC76G_GPS_Module", "neo6m_headless.py"), startup_delay=0.1), root),
        ModuleRunner(ModuleConfig("UPS_Monitor", os.path.join("4_UPS_HAT_E", "ups_headless.py"), python_executable="python3"), root),
        ModuleRunner(ModuleConfig("System_Monitor", os.path.join("5_SystemMonitor", "sys_monitor_headless.py"), python_executable="python3"), root)
    ]

#=================================================================================
# II. Custom UI Components (The "Blocks")
#=================================================================================

class NativeMapWidget(QWidget):
    def __init__(self, project_root):
        super().__init__()
        self.tiles_dir = os.path.join(project_root, "map_tiles")
        
        # Change zoom to a float to support infinite in-between scaling
        self.zoom = 14.0 
        
        self.marker_lat = 2.94941 
        self.marker_lon = 101.87505
        self.view_lat = 2.94941
        self.view_lon = 101.87505
        self.auto_follow = True
        self.last_mouse_pos = None
        self.setCursor(Qt.OpenHandCursor)
        self.tile_cache = {}
        self.grabGesture(Qt.PinchGesture)

    def updatePos(self, lat, lon):
        if lat != 0:
            self.marker_lat = lat
            self.marker_lon = lon
            if self.auto_follow:
                self.view_lat = lat
                self.view_lon = lon
            self.update()

    def deg2num(self, lat, lon, zoom):
        n = 2.0 ** zoom
        x = (lon + 180.0) / 360.0 * n
        y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
        return x, y

    def num2deg(self, x, y, zoom):
        n = 2.0 ** zoom
        lon_deg = x / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat_deg = math.degrees(lat_rad)
        return lat_deg, lon_deg

    def smooth_zoom(self, pos, scale_factor):
        """Calculates floating-point zoom while keeping the map anchored to the user's fingers"""
        if scale_factor == 1.0: return
        
        # Calculate the new continuous zoom level
        new_zoom = self.zoom + math.log2(scale_factor)
        new_zoom = max(10.0, min(18.0, new_zoom)) # Clamp to available map tiles
        
        # Find the geographic coordinate directly under the user's fingers right now
        ex, ey = self.deg2num(self.view_lat, self.view_lon, self.zoom)
        dx = pos.x() - self.width() / 2
        dy = pos.y() - self.height() / 2
        mouse_lat, mouse_lon = self.num2deg(ex + (dx / 256.0), ey + (dy / 256.0), self.zoom)

        # Apply the zoom
        self.zoom = new_zoom

        # Shift the view center so that the geographic coordinate stays perfectly under the fingers
        mx2, my2 = self.deg2num(mouse_lat, mouse_lon, self.zoom)
        self.view_lat, self.view_lon = self.num2deg(mx2 - (dx / 256.0), my2 - (dy / 256.0), self.zoom)
        self.update()

    def event(self, event):
        if event.type() == QEvent.Gesture: return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        pinch = event.gesture(Qt.PinchGesture)
        if pinch:
            if pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
                self.auto_follow = False
                
                # FIX: Map the global screen coordinate to a local widget coordinate!
                local_pos = self.mapFromGlobal(pinch.centerPoint().toPoint())
                
                self.smooth_zoom(local_pos, pinch.scaleFactor())
            return True
        return False

    def wheelEvent(self, event):
        self.auto_follow = False
        # Translate the mouse wheel click into a smooth 15% zoom jump
        scale_factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)
        self.smooth_zoom(event.pos(), scale_factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            self.auto_follow = False 

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            n = 2.0 ** self.zoom
            lon_per_pixel = 360.0 / (256 * n)
            lat_per_pixel = 180.0 / (256 * n) 
            self.view_lon -= delta.x() * lon_per_pixel
            self.view_lat += delta.y() * lat_per_pixel
            self.update()

    def mouseReleaseEvent(self, event):
        self.last_mouse_pos = None
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#1e272e"))

        # Calculate the mathematical difference between our continuous float zoom 
        # and the closest available underlying map tile directory
        base_zoom = int(self.zoom)
        scale = 2.0 ** (self.zoom - base_zoom)
        tile_size = 256 * scale

        ex, ey = self.deg2num(self.view_lat, self.view_lon, base_zoom)
        cx, cy = int(self.width()/2), int(self.height()/2)
        
        # Dynamically load more tiles if we are zoomed far out between integer levels
        span = int(4 / scale) + 1 
        
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                tx, ty = int(ex) + dx, int(ey) + dy
                path = f"{self.tiles_dir}/{base_zoom}/{tx}/{ty}.png"
                if os.path.exists(path):
                    key = f"{base_zoom}_{tx}_{ty}"
                    if key not in self.tile_cache:
                        self.tile_cache[key] = QPixmap(path)
                    
                    # Dynamically scale the image tile to bridge the gap between zoom levels
                    draw_x = cx + (tx - ex) * tile_size
                    draw_y = cy + (ty - ey) * tile_size
                    painter.drawPixmap(int(draw_x), int(draw_y), math.ceil(tile_size), math.ceil(tile_size), self.tile_cache[key])

        # Draw the GPS Location Marker
        mx, my = self.deg2num(self.marker_lat, self.marker_lon, self.zoom)
        ex_f, ey_f = self.deg2num(self.view_lat, self.view_lon, self.zoom)
        m_screen_x = cx + (mx - ex_f) * 256
        m_screen_y = cy + (my - ey_f) * 256
        
        painter.setBrush(Qt.red)
        painter.setPen(Qt.white)
        painter.drawEllipse(int(m_screen_x)-8, int(m_screen_y)-8, 16, 16)
        
        if not self.auto_follow:
            painter.setPen(Qt.yellow)
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(15, 30, "📍 Manual Pan Mode (Click 'Follow' to reset)") 

# --- CUSTOM RESPONSIVE TOUCH SLIDER ---
class JumpSlider(QSlider):
    def mousePressEvent(self, event):
        # Let Qt process the click first
        super().mousePressEvent(event)
        
        if event.button() == Qt.LeftButton:
            # Instantly teleport the slider handle to the exact pixel you touched
            val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), event.x(), self.width())
            self.setValue(val)
            self.sliderMoved.emit(val)


class VideoLabel(QLabel):
    pinch_zoomed = pyqtSignal(bool) # Emits True to Zoom In, False to Zoom Out
    double_clicked = pyqtSignal()   # Fallback for double-tapping

    def __init__(self, text=""):
        super().__init__(text)
        self.grabGesture(Qt.PinchGesture)
        self.pinch_accum = 1.0

    def event(self, event):
        if event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        pinch = event.gesture(Qt.PinchGesture)
        if pinch:
            if pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
                self.pinch_accum *= pinch.scaleFactor()
                # If pinched outward by 30%, trigger Fullscreen
                if self.pinch_accum > 1.3: 
                    self.pinch_zoomed.emit(True)
                    self.pinch_accum = 1.0
                # If pinched inward by 30%, trigger Exit Fullscreen
                elif self.pinch_accum < 0.7:
                    self.pinch_zoomed.emit(False)
                    self.pinch_accum = 1.0
                    
            if pinch.state() == Qt.GestureFinished:
                self.pinch_accum = 1.0
            return True
        return False
        
    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

class GestureTerminal(QTextEdit):
    pinch_zoomed = pyqtSignal(bool) # Emits True to enter fullscreen, False to exit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.grabGesture(Qt.PinchGesture)
        self.pinch_accum = 1.0

        # 1. Disable text selection so dragging doesn't highlight words
        self.setTextInteractionFlags(Qt.NoTextInteraction)

        # 2. Attach the kinetic touch scroller to the terminal's viewport
        # We use LeftMouseButtonGesture because Pi touchscreens usually emulate mouse clicks
        QScroller.grabGesture(self.viewport(), QScroller.LeftMouseButtonGesture)
        
        # 3. Tune the scrolling physics for the touchscreen
        scroller = QScroller.scroller(self.viewport())
        props = scroller.scrollerProperties()
        
        # Make it highly sensitive to touch movements
        props.setScrollMetric(QScrollerProperties.DragStartDistance, 0.001) 
        # Add a bit of friction so it doesn't fly out of control on small screens
        props.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.5) 
        
        scroller.setScrollerProperties(props)

    def event(self, event):
        if event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        pinch = event.gesture(Qt.PinchGesture)
        if pinch:
            if pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
                self.pinch_accum *= pinch.scaleFactor()
                
                # Pinch Out (> 1.3) = Enter Fullscreen
                if self.pinch_accum > 1.3:
                    self.pinch_zoomed.emit(True)
                    self.pinch_accum = 1.0
                # Pinch In (< 0.7) = Exit Fullscreen
                elif self.pinch_accum < 0.7:
                    self.pinch_zoomed.emit(False)
                    self.pinch_accum = 1.0
                    
            if pinch.state() == Qt.GestureFinished:
                self.pinch_accum = 1.0
            return True
        return False
        
    def mouseDoubleClickEvent(self, event):
        # Fallback allowing you to double-tap to toggle fullscreen
        self.pinch_zoomed.emit(True) 
        super().mouseDoubleClickEvent(event)
        
# ==========================================================
# III. Main Application (The "Conductor")
# ==========================================================
class LauncherMainWindow(QMainWindow):
    
    # A. Initialization & Setup
    def __init__(self, modules: List[ModuleRunner], project_root: str):
        super().__init__()
        self.modules = modules
        self.project_root = project_root
        self.em_queued = False
        
        # --- Dedicated Clock Timer (1Hz Update) ---
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        
        self.load_settings()
        
        # Define the Trash Directory
        self.TRASH_DIR = "/home/group9/media/.trash"
        os.makedirs(self.TRASH_DIR, exist_ok=True)

        self.paths = {
            "Regular Video": os.path.join(self.project_root, "1_TrafficSign", "recordings"),
            "Emergency Video": os.path.join(self.project_root, "1_TrafficSign", "emergency_recordings"),
            "GPS Tracks": os.path.join(self.project_root, "3_LC76G_GPS_Module", "tracks"),
            "Power Logs": os.path.join(self.project_root, "4_UPS_HAT_E", "UPS_Records"),
            "Recycle Bin": self.TRASH_DIR
        }
        for p in self.paths.values(): os.makedirs(p, exist_ok=True)

        self.terminals = {}
        self.last_emergency_time = 0.0 
        self.qrcp_process = None 
        
        self.cam_record_flag = os.path.join(self.project_root, "1_TrafficSign", ".record_flag")
        self.ups_record_flag = os.path.join(self.project_root, "4_UPS_HAT_E", ".ups_record_flag")
        self.track_record_flag = "/dev/shm/aras_tracking.flag"
        
        self.emergency_flag_cam = os.path.join(self.project_root, "1_TrafficSign", ".emergency_flag")
        self.emergency_flag_led = os.path.join(self.project_root, "2_Radar", ".led_emergency_flag")
        
        self.fcw_flag_led = os.path.join(self.project_root, "2_Radar", ".led_fcw_flag")
        self.aeb_flag_led = os.path.join(self.project_root, "2_Radar", ".led_aeb_flag")
        
        # Clean them up on boot
        for flag in [self.fcw_flag_led, self.aeb_flag_led, self.cam_record_flag, 
                     self.ups_record_flag, self.track_record_flag, 
                     self.emergency_flag_cam, self.emergency_flag_led]:
            if os.path.exists(flag): os.remove(flag)
        
        self.is_cam_recording = False
        self.is_ups_recording = False
        self.is_tracking = False
        
        subprocess.run(["sudo", "pkill", "-9", "-f", "integrated.py"], stderr=subprocess.DEVNULL)
        
        self.signals = LogSignal()
        self.signals.new_log.connect(self.append_log)
        self.signals.new_frame.connect(self.update_video)
        self.signals.new_detection.connect(self.update_detections)
        self.signals.new_gps.connect(self.update_gps)
        self.signals.new_ups.connect(self.update_ups)
        self.signals.new_alert.connect(self.update_alert)
        self.signals.play_audio.connect(self.handle_audio_trigger)
        self.signals.new_sysmon.connect(self.update_sysmon)
        self.signals.emergency_triggered.connect(self.trigger_emergency_protocol)

        self.aeb_path = os.path.join(self.project_root, "Asset", "aeb.wav")
        self.fcw_path = os.path.join(self.project_root, "Asset", "fcw.wav")
        self.em_path = os.path.join(self.project_root, "Asset", "emergency_alert.wav")
        
        self.audio_proc_aeb = None
        self.audio_proc_fcw = None
        self.audio_proc_em = None
        self.alert_timeout_timer = None

        self.init_ui()
        
        for m in self.modules:
            m.log_signal = self.signals
            m.start()
    
    def trigger_simulation(self, alert_type):
        if alert_type == "FCW":
            open(self.fcw_flag_led, 'w').close()
            self.signals.new_alert.emit("FCW", {'distance': 7, 'speed': 60})
            
        elif alert_type == "AEB":
            open(self.aeb_flag_led, 'w').close()
            self.signals.new_alert.emit("AEB", {'distance': 2, 'speed': 60})
    
    def load_settings(self):
        default_settings = {
            "aeb_audio": True, 
            "fcw_audio": True, 
            "em_audio": True,
            "em_duration": "Medium (40s total)"
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    self.settings = json.load(f)
            except Exception:
                self.settings = default_settings
        else:
            self.settings = default_settings
            
        self.save_settings()

    def save_settings(self):
        with open(SETTINGS_FILE, 'w') as f: 
            json.dump(self.settings, f)
            
        dur_map = {"Short (20s total)": 10, "Medium (40s total)": 20, "Long (60s total)": 30}
        val = dur_map.get(self.settings.get("em_duration", "Medium (40s total)"), 20)
        
        try:
            with open(os.path.join(self.project_root, "1_TrafficSign", ".buffer_cfg"), "w") as f:
                f.write(str(val))
        except Exception as e:
            pass
    
    def _update_clock(self):
        from datetime import datetime
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        if hasattr(self, 'lbl_top_time'):
            self.lbl_top_time.setText(f"📅 {date_str}  🕒 {time_str}")
            
    # B. Primary UI Construction (The "GUI Builder")
    
    def init_ui(self):
        # --- 1. GLOBAL DARK MODE ---
        self.setWindowTitle("ARAS Master Interface")
        self.setFixedSize(800, 480)
        #self.setMinimumSize(800, 480) # Allows expanding, but prevents shrinking below 800x480
        #self.resize(1024, 600) # Optional: Sets a default starting size for windowed mode
        
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QGroupBox { color: #3498db; font-weight: bold; border: 1px solid #34495e; border-radius: 4px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 5px; }
        """)

        # --- 2. TAB WIDGET INITIALIZATION ---
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.setDocumentMode(True)
        #self.tabs.tabBar().setExpanding(True)
        
         # DARK MODE TABS (Auto-fit to avoid scrolling)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #2c3e50; background: #121212; }
            QTabBar::tab { 
                width: 113px; /* 112px * 7 tabs = 784px (Fits perfectly in 800px) */
                height: 35px; 
                font-size: 11px;
                font-weight: bold; 
                background: #1e272e;
                color: #bdc3c7;
                border-right: 1px solid #2c3e50;
                padding: 0px;
            }
            QTabBar::tab:selected { background: #2980b9; color: white; }
        """)
        
        # --- SOFTWARE BRIGHTNESS OVERLAY ---
        self.dim_overlay = QWidget(self)
        self.dim_overlay.setStyleSheet("background-color: black;")
        self.dim_overlay.setAttribute(Qt.WA_TransparentForMouseEvents) # Lets you click right through it!
        self.dim_overlay.hide()
        
        # --- 3. TOOLBAR CONFIGURATION ---
        self.top_toolbar = QToolBar("Controls")
        self.top_toolbar.setMinimumHeight(35)
        self.top_toolbar.setMovable(False)
        self.top_toolbar.setStyleSheet("QToolBar { background-color: #1a1a1a; border-bottom: 1px solid #333; }") 
        self.addToolBar(Qt.TopToolBarArea, self.top_toolbar)
        
        btn_stop = QPushButton("⏹️ Graceful Stop All")
        btn_stop.setStyleSheet("""
            background-color: #c0392b; color: white; font-weight: bold; 
            padding: 4px 8px; border-radius: 4px; font-size: 11px;
        """)
        btn_stop.clicked.connect(self.close)
        self.top_toolbar.addWidget(btn_stop)
        self.top_toolbar.addSeparator()
        
        self.lbl_top_ups = QLabel("🔋 UPS: --% (-- min) | --")
        self.lbl_top_ups.setStyleSheet("""
            QLabel {
                color: #ecf0f1; font-size: 11px; font-weight: bold; 
                padding: 4px 8px; background-color: #2c3e50; border: 1px solid #7f8c8d;
                border-radius: 4px;
            }
        """)
        self.top_toolbar.addWidget(self.lbl_top_ups)
        
        spacer_expanding = QWidget()
        spacer_expanding.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.top_toolbar.addWidget(spacer_expanding)

        self.lbl_top_time = QLabel("📅 --/--/--  🕒 --:--:--")
        self.lbl_top_time.setMinimumHeight(25) 
        self.lbl_top_time.setStyleSheet("""
            color: #bdc3c7; font-size: 11px; font-weight: bold; 
            background: #2c3e50; border-radius: 4px; padding: 4px 8px;
        """)
        self.top_toolbar.addWidget(self.lbl_top_time)
                               
        self.lbl_top_ups.setAlignment(Qt.AlignCenter)
        self.lbl_top_time.setAlignment(Qt.AlignCenter)

        # --- 4. TAB BUILDING SEQUENCE ---
        self._build_vision_tab()
        self._build_radar_tab()
        self._build_gps_tab()
        self._build_ups_tab()
        self._build_sysmon_tab()
        self._build_settings_tab()
        self._build_media_browser_tab()
    
    def _build_vision_tab(self):
        tab_vision = QWidget()
        tab_vision.setStyleSheet("background-color: #121212; color: white;")
        
        self.vision_layout = QVBoxLayout(tab_vision)
        self.vision_layout.setContentsMargins(5, 5, 5, 5)

        splitter = QSplitter(Qt.Horizontal)
        
        # --- TOUCH-FRIENDLY VISIBLE SPLITTER ---
        # Reduced from 40px to 24px (Slightly thinner, but still easy for a finger to grab)
        splitter.setHandleWidth(30) 
        
        splitter.setStyleSheet("""
            QSplitter::handle:horizontal {
                /* Draws a crisp, thin 2px vertical line down the center of the invisible hitbox */
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 transparent, stop:0.45 transparent, 
                    stop:0.45 #5d6d7e, stop:0.55 #5d6d7e, 
                    stop:0.55 transparent, stop:1 transparent);
            }
            QSplitter::handle:horizontal:pressed {
                /* Turns the line blue and makes it slightly thicker while being dragged */
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 transparent, stop:0.40 transparent, 
                    stop:0.40 #3498db, stop:0.60 #3498db, 
                    stop:0.60 transparent, stop:1 transparent);
            }
        """)

        # ==========================================
        # LEFT PANEL
        # ==========================================
        left_widget = QWidget()
        col_left = QVBoxLayout(left_widget)
        col_left.setContentsMargins(0, 0, 0, 0)
        col_left.setSpacing(10)

        # Replace QLabel with our new Gesture-Aware VideoLabel
        self.lbl_video = VideoLabel("Initializing Camera Feed...")
        self.lbl_video.setAlignment(Qt.AlignCenter)
        self.lbl_video.setStyleSheet("background-color: black; border: 2px solid #34495e; border-radius: 6px;")
        self.lbl_video.setMinimumSize(320, 180) 
        self.lbl_video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        # Connect the pinch and double-tap signals
        self.is_video_fullscreen = False
        self.lbl_video.pinch_zoomed.connect(self.set_video_fullscreen)
        self.lbl_video.double_clicked.connect(self.toggle_video_fullscreen)
        
        col_left.addWidget(self.lbl_video, stretch=1)

        # Save sim_group as self.sim_group so we can hide it later
        self.sim_group = QGroupBox("🧪 Simulation Controls")
        self.sim_group.setStyleSheet("""
            QGroupBox { color: #bdc3c7; font-weight: bold; font-size: 11px; border: 1px solid #34495e; border-radius: 4px; margin-top: 5px; }
            QGroupBox::title { subcontrol-origin: margin; left: 5px; top: 0px; padding: 0 5px; }
        """)
        sim_layout = QHBoxLayout(self.sim_group)
        sim_layout.setContentsMargins(5, 15, 5, 5)
        sim_layout.setSpacing(5)

        self.btn_sim_fcw = QPushButton("Simulate FCW (7m @ 60km/h)")
        self.btn_sim_fcw.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold; font-size: 10px; padding: 6px; border-radius: 4px;")
        self.btn_sim_fcw.clicked.connect(lambda: self.trigger_simulation("FCW"))

        self.btn_sim_aeb = QPushButton("Simulate AEB (2m @ 60km/h)")
        self.btn_sim_aeb.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; font-size: 10px; padding: 6px; border-radius: 4px;")
        self.btn_sim_aeb.clicked.connect(lambda: self.trigger_simulation("AEB"))
        
        self.btn_sim_brake = QPushButton("Hard Braking (100 ➔ 60 km/h)")
        self.btn_sim_brake.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold; font-size: 10px; padding: 6px; border-radius: 4px;")
        self.btn_sim_brake.clicked.connect(lambda: self.signals.emergency_triggered.emit("SIMULATED_HARD_BRAKE"))

        sim_layout.addWidget(self.btn_sim_fcw)
        sim_layout.addWidget(self.btn_sim_aeb)
        sim_layout.addWidget(self.btn_sim_brake)
        
        col_left.addWidget(self.sim_group, stretch=0)

        # ==========================================
        # RIGHT PANEL
        # ==========================================
        # Save right_widget as self.right_widget so we can hide it later
        self.right_widget = QWidget()
        self.right_widget.setMinimumWidth(100) 
        col_right = QVBoxLayout(self.right_widget)
        col_right.setContentsMargins(0, 0, 0, 0)
        col_right.setSpacing(5)

        # Wrap detections in a widget so we can easily hide it during terminal fullscreen
        self.vision_detections_widget = QWidget()
        col_detections = QVBoxLayout(self.vision_detections_widget)
        col_detections.setContentsMargins(0, 0, 0, 0)
        col_detections.setSpacing(4)

        def create_det_tile(title, initial_text, bg_color):
            container = QWidget()
            layout = QVBoxLayout(container); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
            t_lbl = QLabel(f"<b>{title.upper()}</b>"); t_lbl.setAlignment(Qt.AlignCenter); t_lbl.setStyleSheet("color: #bdc3c7; font-size: 10px;")
            v_lbl = QLabel(initial_text); v_lbl.setAlignment(Qt.AlignCenter); v_lbl.setWordWrap(True)
            v_lbl.setStyleSheet(f"background-color: {bg_color}; color: white; font-size: 12px; font-weight: bold; border-radius: 4px; min-height: 35px; padding: 2px;")
            layout.addWidget(t_lbl); layout.addWidget(v_lbl)
            return container, v_lbl

        self.lbl_speed_sign = QLabel("N/A")
        self.lbl_speed_sign.setAlignment(Qt.AlignCenter)
        self.lbl_speed_sign.setStyleSheet("background-color: white; color: black; border: 3px solid red; border-radius: 25px; font-size: 22px; font-weight: bold; min-height: 50px;")
        
        col_detections.addWidget(QLabel("<b>SPEED LIMIT</b>", alignment=Qt.AlignCenter, styleSheet="color: #bdc3c7; font-size: 10px;"))
        col_detections.addWidget(self.lbl_speed_sign)

        tc_tile, self.lbl_control_sign = create_det_tile("Traffic Control", "No Signs", "#34495e")
        rh_tile, self.lbl_hazard_sign = create_det_tile("Road Hazards", "Road Clear", "#27ae60")
        vb_tile, self.lbl_vru_sign = create_det_tile("Peds / Bikes", "Clear", "#2c3e50")

        col_detections.addWidget(tc_tile)
        col_detections.addWidget(rh_tile)
        col_detections.addWidget(vb_tile)
        
        # Add the grouped detections widget to the right column
        col_right.addWidget(self.vision_detections_widget)
        
        # ==========================================
        # AI VISION TERMINAL
        # ==========================================
        self.vision_term_group = QGroupBox("System Logs")
        self.vision_term_group.setStyleSheet("""
            QGroupBox { color: #bdc3c7; font-weight: bold; font-size: 10px; border: 1px solid #34495e; border-radius: 4px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 5px; top: 0px; padding: 0 5px; }
        """)
        term_layout = QVBoxLayout(self.vision_term_group)
        term_layout.setContentsMargins(2, 12, 2, 2)

        self.vision_console = GestureTerminal()
        self.vision_console.setFont(QFont("Consolas", 8))
        self.vision_console.setStyleSheet("background-color: #1a1a1a; color: #2ecc71; border: none;")
        
        # Connect the pinch gesture to our new handler
        self.vision_console.pinch_zoomed.connect(self._toggle_vision_terminal_fullscreen)
        
        self.terminals["AI_Vision"] = self.vision_console
        
        term_layout.addWidget(self.vision_console)
        col_right.addWidget(self.vision_term_group, stretch=1)
        # ==========================================

        self.btn_cam_record = QPushButton("⏺️ Start Camera\nRecording")
        self.btn_cam_record.setStyleSheet("""
            QPushButton { background-color: #34495e; color: white; font-size: 11px; font-weight: bold; padding: 8px 4px; border-radius: 4px; border: 2px solid #5d6d7e; }
            QPushButton:checked { background-color: #c0392b; border-color: #e74c3c; }
        """)
        self.btn_cam_record.setCheckable(True)
        self.btn_cam_record.clicked.connect(self.toggle_cam_recording)
        
        col_right.addWidget(self.btn_cam_record, stretch=0)

        # ==========================================
        # ASSEMBLE SPLITTER
        # ==========================================
        splitter.addWidget(left_widget)
        splitter.addWidget(self.right_widget)
        splitter.setSizes([560, 240])

        self.vision_layout.addWidget(splitter)
        self.tabs.addTab(tab_vision, "📷 AI Vision")
    
    def _build_radar_tab(self):
        tab_radar = QWidget()
        tab_radar.setStyleSheet("background-color: #121212;")
        main_layout = QVBoxLayout(tab_radar)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        font = QFont("Consolas", 9)
        
        # Save the container so we can manipulate it during fullscreen
        self.terminals_widget = QWidget()
        terminals_layout = QHBoxLayout(self.terminals_widget)
        terminals_layout.setContentsMargins(0, 0, 0, 0)
        terminals_layout.setSpacing(10) 
        
        # We need to save references to the individual group boxes to hide/show them
        self.radar_groups = {}
        
        for name in ["LD2451_Front", "LD2417_Back"]:
            group = QGroupBox(name.replace("_", " ") + " Terminal") 
            group.setStyleSheet("""
                QGroupBox { 
                    color: #3498db; font-weight: bold; font-size: 12px;
                    border: 2px solid #34495e; border-radius: 6px; margin-top: 20px; 
                } 
                QGroupBox::title { 
                    subcontrol-origin: margin; subcontrol-position: top left;
                    left: 10px; padding: 0 5px; 
                }
            """)
            
            l = QVBoxLayout(group)
            l.setContentsMargins(5, 20, 5, 5) 
            
            # --- USE THE CUSTOM GESTURE TERMINAL ---
            t = GestureTerminal()
            t.setFont(font)
            t.setStyleSheet("background-color: #1a1a1a; color: #2ecc71; border: 1px solid #2c3e50; border-radius: 4px; padding: 5px;")
            l.addWidget(t)
            
            # Connect the pinch gesture to a dedicated fullscreen handler, passing the terminal's name
            t.pinch_zoomed.connect(lambda zoomed_in, term_name=name: self._toggle_radar_fullscreen(term_name, zoomed_in))
            
            terminals_layout.addWidget(group)
            self.terminals[name] = t
            self.radar_groups[name] = group
        
        main_layout.addWidget(self.terminals_widget, stretch=1)
        
        # Save alert panel so we can hide it during fullscreen
        self.radar_alert_panel = QWidget()
        alert_layout = QHBoxLayout(self.radar_alert_panel)
        alert_layout.setContentsMargins(10, 10, 10, 10)
        alert_layout.setSpacing(15)
        self.radar_alert_panel.setMaximumHeight(65)
        
        self.lbl_current_alert = QLabel("✅ SAFE")
        self.lbl_current_alert.setAlignment(Qt.AlignCenter)
        self.lbl_current_alert.setStyleSheet("background-color: #27ae60; color: white; font-size: 14pt; font-weight: bold; border-radius: 6px; padding: 5px;")
        alert_layout.addWidget(self.lbl_current_alert, stretch=2)
        
        self.lbl_alert_distance = QLabel("Distance: -- m")
        self.lbl_alert_distance.setStyleSheet("color: #bdc3c7; font-size: 13px; font-weight: bold;")
        self.lbl_alert_distance.setAlignment(Qt.AlignCenter)
        alert_layout.addWidget(self.lbl_alert_distance, stretch=1)
        
        self.lbl_alert_speed = QLabel("Speed: -- km/h")
        self.lbl_alert_speed.setStyleSheet("color: #bdc3c7; font-size: 13px; font-weight: bold;")
        self.lbl_alert_speed.setAlignment(Qt.AlignCenter)
        alert_layout.addWidget(self.lbl_alert_speed, stretch=1)
        
        self.radar_alert_panel.setStyleSheet("background-color: #1e272e; border: 1px solid #34495e; border-radius: 6px;")
        main_layout.addWidget(self.radar_alert_panel)
        
        self.is_radar_fullscreen = False
        self.tabs.addTab(tab_radar, "📡 Radar Terminals")
    
    def _build_gps_tab(self):
        tab_gps = QWidget()
        tab_gps.setStyleSheet("background-color: #121212;")
        gps_layout = QHBoxLayout(tab_gps)
        gps_layout.setContentsMargins(2, 2, 2, 2)
        gps_layout.setSpacing(4)
        
        # --- LEFT PANEL (Stats and Terminals) ---
        left_panel = QWidget()
        left_panel.setFixedWidth(240)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        lbl_style = "color: #ecf0f1; font-size: 12px;"
        val_style = "color: #f1c40f; font-size: 14px; font-weight: bold;"

        self.lbl_gps_status = QLabel("STATUS: INITIALIZING")
        self.lbl_gps_status.setStyleSheet(val_style)
        self.lbl_gps_status.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_status)

        self.lbl_gps_limit = QLabel("LIMIT: N/A")
        self.lbl_gps_limit.setStyleSheet("background-color: #c0392b; color: white; font-size: 16px; font-weight: bold; padding: 5px; border-radius: 4px;")
        self.lbl_gps_limit.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_limit)

        self.lbl_gps_mod_speed = QLabel("Module: 0.0 km/h")
        self.lbl_gps_mod_speed.setStyleSheet(val_style)
        self.lbl_gps_mod_speed.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_mod_speed)

        self.lbl_gps_calc_speed = QLabel("Calc: 0.0 km/h")
        self.lbl_gps_calc_speed.setStyleSheet(lbl_style)
        self.lbl_gps_calc_speed.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_calc_speed)

        lbl_odo_title = QLabel("ODOMETER:")
        lbl_odo_title.setStyleSheet(lbl_style)
        lbl_odo_title.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(lbl_odo_title)

        self.lbl_gps_odo = QLabel("0.0 m")
        self.lbl_gps_odo.setStyleSheet("color: #3498db; font-size: 14px; font-weight: bold;")
        self.lbl_gps_odo.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_odo)

        self.lbl_gps_coords = QLabel("Waiting for fix...")
        self.lbl_gps_coords.setStyleSheet(lbl_style)
        self.lbl_gps_coords.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_coords)
        
        self.lbl_gps_alt = QLabel("Alt: ---")
        self.lbl_gps_alt.setStyleSheet("color: #ecf0f1; font-size: 12px;")
        self.lbl_gps_alt.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_alt)

        gps_ctrl_frame = QWidget()
        gps_ctrl_layout = QHBoxLayout(gps_ctrl_frame)
        gps_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_track = QPushButton("⏺️ Track")
        self.btn_track.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 5px; border-radius: 4px;")
        self.btn_track.clicked.connect(self.toggle_tracking)
        
        btn_reset_view = QPushButton("🎯 Follow")
        btn_reset_view.setStyleSheet("background-color: #7f8c8d; color: white; padding: 5px; border-radius: 4px;")
        btn_reset_view.clicked.connect(lambda: setattr(self.map_view, 'auto_follow', True))
        
        gps_ctrl_layout.addWidget(self.btn_track)
        gps_ctrl_layout.addWidget(btn_reset_view)
        left_layout.addWidget(gps_ctrl_frame)

        self.gps_console = QTextEdit()
        self.gps_console.setReadOnly(True)
        self.gps_console.setStyleSheet("background-color: #1a1a1a; color: #2ecc71; font-family: monospace; font-size: 10px; border: 1px solid #34495e; border-radius: 4px;")
        left_layout.addWidget(self.gps_console, stretch=1)

        # --- RIGHT PANEL (Satellites + Map) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        sat_group = QGroupBox("🛰️ Satellites In View")
        sat_group.setStyleSheet("QGroupBox { border: 1px solid #34495e; border-radius: 4px; margin-top: 1ex; color: #3498db; font-weight: bold;}")
        
        # New Horizontal Layout for Satellites above the map
        sat_layout = QHBoxLayout(sat_group)
        sat_layout.setContentsMargins(2, 10, 2, 2)
        
        self.sat_labels = {} 
        constellations = [("GPS", "🇺🇸"), ("GLONASS", "🇷🇺"), ("Galileo", "🇪🇺"), ("BeiDou", "🇨🇳"), ("QZSS", "🇯🇵")]
        
        for name, flag in constellations:
            box = QVBoxLayout()
            lbl_name = QLabel(f"{flag} {name}")
            lbl_name.setStyleSheet("color: #ecf0f1; font-size: 10px;")
            lbl_name.setAlignment(Qt.AlignCenter)
            
            self.sat_labels[name] = QLabel("0")
            self.sat_labels[name].setStyleSheet("color: #f1c40f; font-size: 14px; font-weight: bold;")
            self.sat_labels[name].setAlignment(Qt.AlignCenter)
            
            box.addWidget(lbl_name)
            box.addWidget(self.sat_labels[name])
            sat_layout.addLayout(box)
        
        right_layout.addWidget(sat_group)
        
        self.map_view = NativeMapWidget(self.project_root)
        self.map_view.setStyleSheet("border: 1px solid #34495e; border-radius: 4px;")
        right_layout.addWidget(self.map_view, stretch=1)

        gps_layout.addWidget(left_panel)
        gps_layout.addWidget(right_panel, stretch=1)
        self.tabs.addTab(tab_gps, "🛰️ GPS Dashboard")
    
    def _build_ups_tab(self):
        tab_ups = QWidget()
        tab_ups.setStyleSheet("background-color: #121212;")
        main_layout = QVBoxLayout(tab_ups)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        top_layout = QHBoxLayout()
        
        self.lbl_big_power = QLabel("0.0 W\nIdle")
        self.lbl_big_power.setAlignment(Qt.AlignCenter)
        self.lbl_big_power.setStyleSheet("background-color: #1e272e; color: white; font-size: 18px; font-weight: bold; border-radius: 6px; padding: 10px; border: 1px solid #34495e;")
        
        self.lbl_big_wh = QLabel("0.000 Wh\nUsed")
        self.lbl_big_wh.setAlignment(Qt.AlignCenter)
        self.lbl_big_wh.setStyleSheet("background-color: #1e272e; color: white; font-size: 18px; font-weight: bold; border-radius: 6px; padding: 10px; border: 1px solid #34495e;")
        
        self.lbl_big_time = QLabel("-- min\nRemaining")
        self.lbl_big_time.setAlignment(Qt.AlignCenter)
        self.lbl_big_time.setStyleSheet("background-color: #1e272e; color: white; font-size: 18px; font-weight: bold; border-radius: 6px; padding: 10px; border: 1px solid #34495e;")
        
        top_layout.addWidget(self.lbl_big_power)
        top_layout.addWidget(self.lbl_big_wh)
        top_layout.addWidget(self.lbl_big_time)
        main_layout.addLayout(top_layout, stretch=1)

        bottom_layout = QHBoxLayout()
        
        left = QVBoxLayout()
        val_style = "color: #f1c40f; font-size: 16px; font-weight: bold;"
        lbl_style = "color: white; font-size: 12px;"
        
        group_bat = QGroupBox("Battery Status")
        group_bat.setStyleSheet("QGroupBox { color: #3498db; font-weight: bold; border: 1px solid #34495e; border-radius: 5px; margin-top: 10px;} QGroupBox::title { subcontrol-origin: margin; left: 5px; }")
        gl_bat = QGridLayout(group_bat)
        gl_bat.setContentsMargins(2, 12, 2, 2)
        
        self.lbl_ups_pct = QLabel("0%")
        self.lbl_ups_pct.setStyleSheet("color: #2ecc71; font-size: 28px; font-weight: bold;")
        self.lbl_ups_pct.setAlignment(Qt.AlignCenter)
        gl_bat.addWidget(self.lbl_ups_pct, 0, 0, 1, 2)
        
        self.lbl_ups_bat_v = QLabel("0 mV"); self.lbl_ups_bat_v.setStyleSheet(val_style)
        self.lbl_ups_bat_c = QLabel("0 mA"); self.lbl_ups_bat_c.setStyleSheet(val_style)
        self.lbl_ups_cap = QLabel("0 mAh"); self.lbl_ups_cap.setStyleSheet(val_style)
        
        l1=QLabel("Volts:"); l1.setStyleSheet(lbl_style)
        l2=QLabel("Amps:"); l2.setStyleSheet(lbl_style)
        l3=QLabel("Cap:"); l3.setStyleSheet(lbl_style)
        
        gl_bat.addWidget(l1, 1, 0); gl_bat.addWidget(self.lbl_ups_bat_v, 1, 1)
        gl_bat.addWidget(l2, 2, 0); gl_bat.addWidget(self.lbl_ups_bat_c, 2, 1)
        gl_bat.addWidget(l3, 3, 0); gl_bat.addWidget(self.lbl_ups_cap, 3, 1)
        left.addWidget(group_bat)
        bottom_layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        
        group_vbus = QGroupBox("Input Power")
        group_vbus.setStyleSheet("QGroupBox { color: #3498db; font-weight: bold; border: 1px solid #34495e; border-radius: 5px; margin-top: 10px;} QGroupBox::title { subcontrol-origin: margin; left: 5px; }")
        gl_vbus = QGridLayout(group_vbus)
        gl_vbus.setContentsMargins(2, 12, 2, 2)
        
        self.lbl_ups_vbus_v = QLabel("0 mV"); self.lbl_ups_vbus_v.setStyleSheet(val_style)
        self.lbl_ups_vbus_p = QLabel("0 mW"); self.lbl_ups_vbus_p.setStyleSheet(val_style)
        l5=QLabel("Volts:"); l5.setStyleSheet(lbl_style)
        l6=QLabel("Power:"); l6.setStyleSheet(lbl_style)
        
        gl_vbus.addWidget(l5, 0, 0); gl_vbus.addWidget(self.lbl_ups_vbus_v, 0, 1)
        gl_vbus.addWidget(l6, 1, 0); gl_vbus.addWidget(self.lbl_ups_vbus_p, 1, 1)
        right.addWidget(group_vbus)

        group_cells = QGroupBox("Cells (mV)")
        group_cells.setStyleSheet("QGroupBox { color: #3498db; font-weight: bold; border: 1px solid #34495e; border-radius: 5px; margin-top: 10px;} QGroupBox::title { subcontrol-origin: margin; left: 5px; }")
        gl_cells = QHBoxLayout(group_cells)
        gl_cells.setContentsMargins(2, 12, 2, 2)
        self.lbl_c1 = QLabel("0"); self.lbl_c1.setStyleSheet(val_style); self.lbl_c1.setAlignment(Qt.AlignCenter)
        self.lbl_c2 = QLabel("0"); self.lbl_c2.setStyleSheet(val_style); self.lbl_c2.setAlignment(Qt.AlignCenter)
        self.lbl_c3 = QLabel("0"); self.lbl_c3.setStyleSheet(val_style); self.lbl_c3.setAlignment(Qt.AlignCenter)
        self.lbl_c4 = QLabel("0"); self.lbl_c4.setStyleSheet(val_style); self.lbl_c4.setAlignment(Qt.AlignCenter)
        gl_cells.addWidget(self.lbl_c1); gl_cells.addWidget(self.lbl_c2)
        gl_cells.addWidget(self.lbl_c3); gl_cells.addWidget(self.lbl_c4)
        right.addWidget(group_cells)
        
        self.btn_ups_record = QPushButton("⏺️ Record Power")
        self.btn_ups_record.setStyleSheet("background-color: #8e44ad; color: white; font-size: 14px; font-weight: bold; padding: 10px; border-radius: 4px; margin-top: 5px;")
        self.btn_ups_record.clicked.connect(self.toggle_ups_recording)
        right.addWidget(self.btn_ups_record)
        
        bottom_layout.addLayout(right, stretch=1)
        main_layout.addLayout(bottom_layout, stretch=2)
        
        self.tabs.addTab(tab_ups, "🔋 UPS Dashboard")
    
    def _build_sysmon_tab(self):
        tab_sysmon = QWidget()
        tab_sysmon.setStyleSheet("background-color: #121212;")
        layout = QGridLayout(tab_sysmon)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        tile_style = "background-color: #1e272e; color: white; border-radius: 8px; padding: 10px; border: 1px solid #34495e;"
        
        self.lbl_cpu = QLabel("CPU Load\n0.0%")
        self.lbl_cpu.setAlignment(Qt.AlignCenter)
        self.lbl_cpu.setStyleSheet(tile_style + "font-size: 18px; font-weight: bold;")
        
        self.lbl_temp = QLabel("Core Temp\n0.0 °C")
        self.lbl_temp.setAlignment(Qt.AlignCenter)
        self.lbl_temp.setStyleSheet(tile_style + "font-size: 18px; font-weight: bold;")
        
        self.lbl_fan = QLabel("Fan Speed\n0 RPM")
        self.lbl_fan.setAlignment(Qt.AlignCenter)
        self.lbl_fan.setStyleSheet(tile_style + "font-size: 18px; font-weight: bold;")
        
        self.lbl_ram = QLabel("RAM Usage\n0.0/0.0 GB (0%)")
        self.lbl_ram.setAlignment(Qt.AlignCenter)
        self.lbl_ram.setStyleSheet(tile_style + "font-size: 16px; font-weight: bold;")
        
        self.lbl_disk = QLabel("Storage\n0.0/0.0 GB")
        self.lbl_disk.setAlignment(Qt.AlignCenter)
        self.lbl_disk.setStyleSheet(tile_style + "font-size: 16px; font-weight: bold;")

        self.lbl_rtc = QLabel("RTC Battery\n0.00 V")
        self.lbl_rtc.setAlignment(Qt.AlignCenter)
        self.lbl_rtc.setStyleSheet(tile_style + "font-size: 16px; font-weight: bold;")

        lbl_info = QLabel("Low load proves IMX500 sensor is handling AI Vision independently.")
        lbl_info.setAlignment(Qt.AlignCenter)
        lbl_info.setStyleSheet("color: #ecf0f1; font-size: 12px; font-style: italic; background-color: transparent;")

        layout.addWidget(self.lbl_cpu, 0, 0)
        layout.addWidget(self.lbl_temp, 0, 1)
        layout.addWidget(self.lbl_fan, 0, 2)
        layout.addWidget(self.lbl_ram, 1, 0)
        layout.addWidget(self.lbl_disk, 1, 1)
        layout.addWidget(self.lbl_rtc, 1, 2)
        layout.addWidget(lbl_info, 2, 0, 1, 3)

        self.tabs.addTab(tab_sysmon, "💻 System Monitor")
    
    def _build_settings_tab(self):
        tab = QWidget()
        tab.setStyleSheet("background-color: #121212; color: white;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10) 
        layout.setSpacing(10)

        # --- 1. AUDIO ALERTS ---
        grp = QGroupBox("Audio Alerts")
        grp.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; font-size: 14px; border: 1px solid #34495e; 
                margin-top: 15px; border-radius: 6px; color: #3498db;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: 0px; padding: 0 5px; }
        """)
        gl = QGridLayout(grp)
        gl.setContentsMargins(10, 20, 10, 10) 
        gl.setSpacing(10)

        self.btn_aeb = self._create_toggle_btn("🚨 AEB", "aeb_audio")
        self.btn_fcw = self._create_toggle_btn("⚠️ FCW", "fcw_audio")
        self.btn_em  = self._create_toggle_btn("🛡️ Emergency Rec", "em_audio")
        
        gl.addWidget(self.btn_aeb, 0, 0)
        gl.addWidget(self.btn_fcw, 0, 1)
        gl.addWidget(self.btn_em, 1, 0, 1, 2)
        layout.addWidget(grp)

        # --- ROW 2: BUFFER, VOLUME, & BRIGHTNESS (Side-by-Side) ---
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)

        # 2A. Emergency Buffer Duration
        grp2 = QGroupBox("Emergency Buffer Duration")
        grp2.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; font-size: 14px; border: 1px solid #3498db; 
                margin-top: 15px; border-radius: 6px; color: #3498db;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: 0px; padding: 0 5px; }
        """)
        l2 = QVBoxLayout(grp2)
        l2.setContentsMargins(10, 20, 10, 10) 
        l2.setSpacing(5) 
        
        lbl_desc = QLabel("Total recording length:")
        lbl_desc.setStyleSheet("font-size: 12px; color: #bdc3c7;")
        
        self.combo_dur = QComboBox()
        self.combo_dur.addItems(["Short (20s total)", "Medium (40s total)", "Long (60s total)"])
        self.combo_dur.setCurrentText(self.settings.get("em_duration", "Medium (40s total)"))
        self.combo_dur.setStyleSheet("""
            QComboBox {
                height: 35px; font-size: 13px; background: #1e272e; 
                color: white; padding-left: 10px; border: 1px solid #34495e; border-radius: 4px;
            }
            QComboBox::drop-down { border: 0px; }
            QComboBox QAbstractItemView { background-color: #1e272e; selection-background-color: #3498db; }
        """)
        self.combo_dur.currentTextChanged.connect(self._update_dur)
        
        l2.addWidget(lbl_desc)
        l2.addWidget(self.combo_dur)
        row2_layout.addWidget(grp2, stretch=2)
        
        # 2B. System Volume Control (Shrunk)
        grp_vol = QGroupBox("🔊 Volume")
        grp_vol.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; border: 1px solid #3498db; margin-top: 15px; border-radius: 6px; color: #3498db; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: 0px; padding: 0 5px; }
        """)
        l_vol = QHBoxLayout(grp_vol)
        l_vol.setContentsMargins(10, 20, 10, 10)
        
        # --- FIX: Changed QSlider to JumpSlider ---
        self.slider_vol = JumpSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(80)
        self.slider_vol.valueChanged.connect(self._change_volume)
        
        self.lbl_vol = QLabel("80%")
        self.lbl_vol.setStyleSheet("color: white; font-weight: bold; font-size: 14px; min-width: 35px;")
        self.lbl_vol.setAlignment(Qt.AlignCenter)
        
        l_vol.addWidget(self.slider_vol)
        l_vol.addWidget(self.lbl_vol)
        row2_layout.addWidget(grp_vol, stretch=2)

        # 2C. Software Brightness Control (New)
        grp_bri = QGroupBox("☀️ Brightness")
        grp_bri.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; border: 1px solid #3498db; margin-top: 15px; border-radius: 6px; color: #3498db; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: 0px; padding: 0 5px; }
        """)
        l_bri = QHBoxLayout(grp_bri)
        l_bri.setContentsMargins(10, 20, 10, 10)
        
        # --- FIX: Changed QSlider to JumpSlider ---
        self.slider_bri = JumpSlider(Qt.Horizontal)
        self.slider_bri.setRange(20, 100) 
        self.slider_bri.setValue(100)
        self.slider_bri.valueChanged.connect(self._change_brightness)
        
        self.lbl_bri = QLabel("100%")
        self.lbl_bri.setStyleSheet("color: white; font-weight: bold; font-size: 14px; min-width: 35px;")
        self.lbl_bri.setAlignment(Qt.AlignCenter)
        
        l_bri.addWidget(self.slider_bri)
        l_bri.addWidget(self.lbl_bri)
        row2_layout.addWidget(grp_bri, stretch=2)

        layout.addLayout(row2_layout) 

        # --- 3. NETWORK CONFIGURATION ---
        grp_net = QGroupBox("Network Configuration")
        grp_net.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; border: 1px solid #3498db; margin-top: 15px; border-radius: 6px; color: #3498db; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: 0px; padding: 0 5px; }
        """)
        l_net = QVBoxLayout(grp_net)
        l_net.setContentsMargins(10, 20, 10, 10)
        l_net.setSpacing(10)

        # Part A: Host a Hotspot
        self.btn_hotspot = QPushButton("📡 Start ARAS Hotspot")
        self.btn_hotspot.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; font-size: 13px; padding: 8px; border-radius: 4px;")
        self.btn_hotspot.setCheckable(True)
        self.btn_hotspot.clicked.connect(self.toggle_hotspot)
        l_net.addWidget(self.btn_hotspot)

        # Part B: Connect to existing Wi-Fi
        l_wifi = QHBoxLayout()
        
        self.btn_scan = QPushButton("🔄 Scan")
        self.btn_scan.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; font-size: 12px; padding: 6px; border-radius: 4px;")
        self.btn_scan.clicked.connect(self.scan_wifi)

        self.combo_ssid = QComboBox()
        self.combo_ssid.setStyleSheet("""
            QComboBox { background-color: #1a1a1a; color: white; border: 1px solid #34495e; border-radius: 4px; padding: 6px; font-size: 12px; }
            QComboBox QAbstractItemView { background-color: #1a1a1a; color: white; selection-background-color: #3498db; }
        """)
        
        self.input_pwd = QLineEdit()
        self.input_pwd.setPlaceholderText("Password")
        self.input_pwd.setEchoMode(QLineEdit.Password)
        self.input_pwd.setStyleSheet("background-color: #1a1a1a; color: white; border: 1px solid #34495e; border-radius: 4px; padding: 6px; font-size: 12px;")
        
        self.btn_connect = QPushButton("🔗 Connect")
        self.btn_connect.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; font-size: 12px; padding: 6px; border-radius: 4px;")
        self.btn_connect.clicked.connect(self.connect_to_wifi)

        l_wifi.addWidget(self.btn_scan)
        l_wifi.addWidget(self.combo_ssid, stretch=3)
        l_wifi.addWidget(self.input_pwd, stretch=2)
        l_wifi.addWidget(self.btn_connect)
        
        l_net.addLayout(l_wifi)
        layout.addWidget(grp_net)

        layout.addStretch() 
        self.tabs.addTab(tab, "⚙️ Settings")
    
    def _build_media_browser_tab(self):
        self.media_browser = MediaBrowserWidget(
            paths=self.paths, 
            signals=self.signals, 
            is_small_screen=True, 
            trash_dir=self.TRASH_DIR
        )
        
        # CRITICAL FIX: Inject aggressive compact styling specifically for the Media Browser widget
        self.media_browser.setStyleSheet("""
            QPushButton { font-size: 11px; padding: 6px; border-radius: 4px; }
            QLabel { font-size: 11px; }
            QListWidget { font-size: 11px; background: #1a1a1a; color: #ecf0f1; border: 1px solid #34495e;}
            QTreeView { font-size: 11px; background: #1a1a1a; color: #ecf0f1; border: 1px solid #34495e;}
            QHeaderView::section { font-size: 11px; padding: 2px; background-color: #2c3e50; border: none;}
        """)
        
        self.signals.qr_url_ready.connect(self.media_browser.display_qr_code)
        self.tabs.addTab(self.media_browser, "📂 Media Browser")
        QTimer.singleShot(500, self.media_browser._select_latest_file_on_boot)
        
    
    # C. Backened Data Handlers (The "Middle-layer")
    
        # This method should be connected to a signal emitted by your background 
        # thread whenever a new frame arrives from the headless script
    def update_video(self, img_bytes): 
        image = QImage.fromData(img_bytes)
        
        if not image.isNull():
            """
            Updates the lbl_video with the newest frame while preserving the 16:9 ratio.
            """
            # 1. Convert the incoming QImage to a QPixmap
            pixmap = QPixmap.fromImage(image)
            
            # 2. Scale the pixmap to fit the label's current dynamic size 
            #    (Qt.KeepAspectRatio guarantees it stays 16:9 and doesn't stretch)
            scaled_pixmap = pixmap.scaled(
                self.lbl_video.size(), 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            # 3. Apply the perfectly scaled image to the dashboard
            self.lbl_video.setPixmap(scaled_pixmap)
        
    def update_detections(self, detection_string):
        signs = detection_string.split(",")
        hazard_texts = []; control_texts = []; vru_texts = []
        for sign in signs:
            if sign.startswith("SL_"): self.lbl_speed_sign.setText(sign.replace("SL_", ""))
            elif sign in ["Bump sign", "Bumps"]: hazard_texts.append("BUMP")
            elif sign == "Pothole": hazard_texts.append("POTHOLE")
            elif sign == "Manhole": hazard_texts.append("MANHOLE")
            elif sign == "Stop": control_texts.append("STOP SIGN")
            elif sign == "Give way": control_texts.append("GIVE WAY")
            elif sign == "Intersection_Alert": control_texts.append("INTERSECTION")
            elif sign == "red-traffic-lights": control_texts.append("RED LIGHT")
            elif sign == "yellow-traffic-lights": control_texts.append("YELLOW LIGHT")
            elif sign == "green-traffic-lights": control_texts.append("GREEN LIGHT")
            elif sign == "Pedestrian": vru_texts.append("PEDESTRIAN")
            elif sign == "Two_Wheeler": vru_texts.append("BICYCLE")
            elif sign == "Motorcycles only": vru_texts.append("MOTORCYCLE")

        if hazard_texts:
            self.lbl_hazard_sign.setText("\n".join(set(hazard_texts)))
            self.lbl_hazard_sign.setStyleSheet("background-color: #e67e22; color: white; font-size: 16px; font-weight: bold; border-radius: 6px; margin: 2px;")
        else:
            self.lbl_hazard_sign.setText("Road Clear")
            self.lbl_hazard_sign.setStyleSheet("background-color: #27ae60; color: white; font-size: 14px; font-weight: bold; border-radius: 6px; margin: 2px;")

        if control_texts:
            self.lbl_control_sign.setText("\n".join(set(control_texts)))
            if "RED LIGHT" in control_texts or "STOP SIGN" in control_texts:
                self.lbl_control_sign.setStyleSheet("background-color: #c0392b; color: white; font-size: 16px; font-weight: bold; border-radius: 6px; margin: 2px;")
            elif "YELLOW LIGHT" in control_texts or "GIVE WAY" in control_texts:
                self.lbl_control_sign.setStyleSheet("background-color: #f39c12; color: white; font-size: 16px; font-weight: bold; border-radius: 6px; margin: 2px;")
            else:
                self.lbl_control_sign.setStyleSheet("background-color: #2980b9; color: white; font-size: 16px; font-weight: bold; border-radius: 6px; margin: 2px;")
        else:
            self.lbl_control_sign.setText("No Signs")
            self.lbl_control_sign.setStyleSheet("background-color: #1e272e; color: white; font-size: 14px; font-weight: bold; border-radius: 6px; margin: 2px; border: 1px solid #34495e;")

        if vru_texts:
            self.lbl_vru_sign.setText("\n".join(set(vru_texts)))
            self.lbl_vru_sign.setStyleSheet("background-color: #f1c40f; color: black; font-size: 16px; font-weight: bold; border-radius: 6px; margin: 2px;")
        else:
            self.lbl_vru_sign.setText("Clear")
            self.lbl_vru_sign.setStyleSheet("background-color: #1e272e; color: white; font-size: 14px; font-weight: bold; border-radius: 6px; margin: 2px; border: 1px solid #34495e;")
        
    def update_gps(self, data):
        self.lbl_gps_status.setText(f"STATUS: {data.get('status', 'SEARCHING')} | Sats: {data.get('sats', 0)}")
        self.lbl_gps_limit.setText(f"LIMIT: {data.get('limit', 'N/A')}")
        self.lbl_gps_mod_speed.setText(f"Module: {data.get('speed', 0.0):.1f} km/h")
        self.lbl_gps_calc_speed.setText(f"Calc: {data.get('calc_speed', 0.0):.1f} km/h")
        self.lbl_gps_coords.setText(f"Lat: {data.get('lat', 0):.6f} | Lon: {data.get('lon', 0):.6f}")
        
        altitude = data.get('alt', 0.0)
        self.lbl_gps_alt.setText(f"Alt: {altitude:.1f} m")
        
        dist = data.get('odo', 0)
        self.lbl_gps_odo.setText(f"{dist:.1f} m" if dist < 1000 else f"{dist/1000.0:.2f} km")
        self.map_view.updatePos(data.get('lat', 0), data.get('lon', 0))
        
        con_data = data.get("constellations", {})
        for name, count in con_data.items():
            if name in self.sat_labels:
                self.sat_labels[name].setText(str(count))

        try:
            temp_path = "/dev/shm/aras_gps_data.tmp"
            final_path = "/dev/shm/aras_gps_data.json"
            
            with open(temp_path, "w") as f:
                json.dump({
                    "speed": data.get('speed', 0.0),
                    "lat": data.get('lat', 0.0),
                    "lon": data.get('lon', 0.0),
                    "status": data.get('status', 'SEARCHING'),
                    "area": data.get('area', 'Unknown Area') 
                }, f)
            
            os.replace(temp_path, final_path)
            
        except Exception:
            pass
        
    def update_ups(self, data):
        pct = data.get("bat_pct", 0)
        time_rem = data.get("time_rem", "--").replace(" in ", " ")
        state = data.get("state", "Idle").upper()
        
        icon = "⚡" if "CHARGING" in state else "🔋"
        
        if (pct <= 20 and "DISCHARGING" in state):
            text_color = "#ff4d4d" 
            border_color = "#c0392b"
        elif "CHARGING" in state:
            text_color = "#3498db"
            border_color = "#2980b9"
        else:
            text_color = "#2ecc71"
            border_color = "#27ae60"

        self.lbl_top_ups.setText(f"{icon} {pct}% ({time_rem}) | {state}")
        self.lbl_top_ups.setStyleSheet(f"""
            QLabel {{
                color: {text_color}; font-size: 11px; font-weight: bold; 
                padding: 4px 8px; background-color: #1a1a1a; border: 2px solid {border_color};
                border-radius: 4px;
            }}
        """)
            
        power_w = data.get("bat_power_w", 0)
        
        if power_w > 0:
            self.lbl_big_power.setText(f"+{power_w:.2f} W\nCharging")
            self.lbl_big_power.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; border-radius: 6px; padding: 10px;")
        elif power_w < 0:
            self.lbl_big_power.setText(f"{abs(power_w):.2f} W\nDischrg")
            self.lbl_big_power.setStyleSheet("background-color: #e74c3c; color: white; font-size: 18px; font-weight: bold; border-radius: 6px; padding: 10px;")
        else:
            self.lbl_big_power.setText(f"0.00 W\nIdle")
            self.lbl_big_power.setStyleSheet("background-color: #1e272e; color: white; font-size: 18px; font-weight: bold; border-radius: 6px; padding: 10px; border: 1px solid #34495e;")
            
        self.lbl_big_wh.setText(f"{data.get('session_used_wh', 0):.3f} Wh\nUsed")
        self.lbl_big_time.setText(f"{data.get('time_rem', '--').replace(' in ', ' ')}\nStatus")
        
        self.lbl_ups_pct.setText(f"{data.get('bat_pct', 0)}%")
        if data.get('bat_pct', 0) <= 20: self.lbl_ups_pct.setStyleSheet("color: #e74c3c; font-size: 28px; font-weight: bold;")
        else: self.lbl_ups_pct.setStyleSheet("color: #2ecc71; font-size: 28px; font-weight: bold;")
        
        self.lbl_ups_bat_v.setText(f"{data.get('bat_v', 0)} mV")
        self.lbl_ups_bat_c.setText(f"{data.get('bat_c', 0)} mA")
        self.lbl_ups_cap.setText(f"{data.get('bat_cap', 0)} mAh")
        self.lbl_ups_vbus_v.setText(f"{data.get('vbus_v', 0)} mV")
        self.lbl_ups_vbus_p.setText(f"{data.get('vbus_p', 0)} mW")
        self.lbl_c1.setText(str(data.get("V1", 0)))
        self.lbl_c2.setText(str(data.get("V2", 0)))
        self.lbl_c3.setText(str(data.get("V3", 0)))
        self.lbl_c4.setText(str(data.get("V4", 0)))

    def update_sysmon(self, data):
        cpu = data.get("cpu_pct", 0)
        freqs = data.get("core_freqs", [0.0, 0.0, 0.0, 0.0])
        max_f = data.get("max_freq", 2.4)
        
        cpu_html = f"""
        <div style='text-align: center;'>
            <span style='font-size: 20px; font-weight: bold;'>CPU: {cpu}%</span><br>
            <span style='font-size: 12px; color: #bdc3c7;'>
                C0:{freqs[0]:.1f} | C1:{freqs[1]:.1f} | C2:{freqs[2]:.1f} | C3:{freqs[3]:.1f}
            </span>
        </div>
        """
        
        self.lbl_cpu.setText(cpu_html)
        if cpu > 80: self.lbl_cpu.setStyleSheet("background-color: #c0392b; color: white; border-radius: 8px; padding: 10px;")
        else: self.lbl_cpu.setStyleSheet("background-color: #1e272e; color: white; border-radius: 8px; padding: 10px; border: 1px solid #34495e;")
            
        temp = data.get("temp", 0)
        self.lbl_temp.setText(f"Core Temp\n{temp} °C")
        if temp > 75: self.lbl_temp.setStyleSheet("background-color: #c0392b; color: white; border-radius: 8px; padding: 10px; font-size: 20px; font-weight: bold;")
        else: self.lbl_temp.setStyleSheet("background-color: #1e272e; color: white; border-radius: 8px; padding: 10px; font-size: 20px; font-weight: bold; border: 1px solid #34495e;")

        self.lbl_fan.setText(f"Fan Speed\n{data.get('fan_rpm', 0)} RPM")
        
        ram_u = data.get("ram_used_gb", 0)
        ram_t = data.get("ram_total_gb", 0)
        ram_pct = data.get("ram_pct", 0)
        self.lbl_ram.setText(f"RAM Usage\n{ram_u:.1f}/{ram_t:.1f} GB ({ram_pct}%)")
        if ram_pct > 85: self.lbl_ram.setStyleSheet("background-color: #c0392b; color: white; border-radius: 8px; padding: 10px; font-size: 16px; font-weight: bold;")
        else: self.lbl_ram.setStyleSheet("background-color: #1e272e; color: white; border-radius: 8px; padding: 10px; font-size: 16px; font-weight: bold; border: 1px solid #34495e;")

        disk_u = data.get("disk_used_gb", 0)
        disk_t = data.get("disk_total_gb", 0)
        hours = data.get("hours_left", 0)
        self.lbl_disk.setText(f"Storage\n{disk_u:.1f}/{disk_t:.1f} GB\n(~{hours:.1f} hrs left)")
        if hours < 2.0: self.lbl_disk.setStyleSheet("background-color: #f39c12; color: white; border-radius: 8px; padding: 10px; font-size: 16px; font-weight: bold;")
        else: self.lbl_disk.setStyleSheet("background-color: #1e272e; color: white; border-radius: 8px; padding: 10px; font-size: 16px; font-weight: bold; border: 1px solid #34495e;")

        rtc_batt = data.get("rtc_batt_v", 0)
        rtc_chg = data.get("rtc_charging_v", 0)
        self.lbl_rtc.setText(f"RTC Battery\n{rtc_batt:.2f} V\n(Chg: {rtc_chg:.2f} V)")
        if 0.1 < rtc_batt < 2.5: self.lbl_rtc.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 8px; padding: 10px; font-size: 16px; font-weight: bold;")
        else: self.lbl_rtc.setStyleSheet("background-color: #1e272e; color: white; border-radius: 8px; padding: 10px; font-size: 16px; font-weight: bold; border: 1px solid #34495e;")
    
    def append_log(self, name, text):
        if name == "UPS_Monitor" or name == "System_Monitor":
            pass 
        elif name == "GPS":
            self.gps_console.append(text)
            self.gps_console.verticalScrollBar().setValue(self.gps_console.verticalScrollBar().maximum())
        elif name in self.terminals:
            self.terminals[name].append(text)
            self.terminals[name].verticalScrollBar().setValue(self.terminals[name].verticalScrollBar().maximum())
            if name == "LD2451_Front":
                if "Target" in text and "Distance=" in text:
                    self._parse_radar_alert(text)

    def _parse_radar_alert(self, log_text):
        try:
            import re
            match = re.search(r'Distance=(\d+)', log_text)
            speed_match = re.search(r'Speed=(\d+)', log_text)
            
            if match and speed_match:
                distance = int(match.group(1))
                speed = int(speed_match.group(1))
                
                AE_DIST_M = 3.0
                FCW_DIST_M = 8.0
                FAST_SPEED_KMH = 5.0
                MID_SPEED_KMH = 4.0
                
                alert_type = "SAFE"
                if distance <= AE_DIST_M and speed >= FAST_SPEED_KMH:
                    alert_type = "AEB"
                elif distance <= FCW_DIST_M or speed >= MID_SPEED_KMH:
                    alert_type = "FCW"
                
                self.signals.new_alert.emit(alert_type, {'distance': distance, 'speed': speed})
        except Exception:
            pass

    def update_alert(self, alert_type, data):
        distance = data.get('distance', 0)
        speed = data.get('speed', 0)
        
        self.lbl_alert_distance.setText(f"Dist: {distance} m")
        self.lbl_alert_speed.setText(f"Speed: {speed} km/h")
        
        if self.alert_timeout_timer is not None:
            self.alert_timeout_timer.cancel()
            self.alert_timeout_timer = None
        
        if alert_type == "AEB":
            self.lbl_current_alert.setText("🚨 AEB")
            self.lbl_current_alert.setStyleSheet("background-color: #c0392b; color: white; font-size: 14pt; font-weight: bold; border-radius: 5px; padding: 5px;")
            self.signals.play_audio.emit("AEB")
            self.trigger_emergency_protocol("RADAR_AEB")
            self.alert_timeout_timer = threading.Timer(8.0, self._reset_alert_to_safe)
            self.alert_timeout_timer.start()
            
        elif alert_type == "FCW":
            self.lbl_current_alert.setText("⚠️ FCW")
            self.lbl_current_alert.setStyleSheet("background-color: #f39c12; color: white; font-size: 14pt; font-weight: bold; border-radius: 5px; padding: 5px;")
            self.signals.play_audio.emit("FCW")
            self.trigger_emergency_protocol("RADAR_FCW")
            self.alert_timeout_timer = threading.Timer(8.0, self._reset_alert_to_safe)
            self.alert_timeout_timer.start()
            
        else:  
            self.lbl_current_alert.setText("✅ SAFE")
            self.lbl_current_alert.setStyleSheet("background-color: #27ae60; color: white; font-size: 14pt; font-weight: bold; border-radius: 5px; padding: 5px;")
            self.signals.play_audio.emit("SAFE")

    def _reset_alert_to_safe(self):
        self.lbl_current_alert.setText("✅ SAFE")
        self.lbl_current_alert.setStyleSheet("background-color: #27ae60; color: white; font-size: 14pt; font-weight: bold; border-radius: 5px; padding: 5px;")
        self.lbl_alert_distance.setText("Dist: -- m")
        self.lbl_alert_speed.setText("Speed: -- km/h")
        self.alert_timeout_timer = None
        
    # D. System Actions & Protocols
    
    def trigger_emergency_protocol(self, cause):
        now = time.time()
        if now - self.last_emergency_time < 5.0:
            return
        
        self.last_emergency_time = now
        print(f"[EMERGENCY] Protocol Triggered By: {cause}")
        
        try:
            with open(self.emergency_flag_cam, 'w') as f: f.write("trigger")
            with open(self.emergency_flag_led, 'w') as f: f.write("trigger")
        except Exception as e:
            print(f"Error writing emergency flags: {e}")
            
        self.signals.play_audio.emit("EMERGENCY")
        
        self.lbl_video.setStyleSheet("background-color: black; color: white; border: 8px solid red;")
        threading.Timer(2.0, lambda: self.lbl_video.setStyleSheet("background-color: black; color: white; border: 2px solid #34495e; border-radius: 6px;")).start()
    
    def handle_audio_trigger(self, trigger_type):
        aeb_busy = self.audio_proc_aeb is not None and self.audio_proc_aeb.poll() is None
        fcw_busy = self.audio_proc_fcw is not None and self.audio_proc_fcw.poll() is None
        em_busy = self.audio_proc_em is not None and self.audio_proc_em.poll() is None

        if trigger_type == "EMERGENCY":
            if em_busy or getattr(self, 'em_queued', False):
                return 
                
            if aeb_busy or fcw_busy:
                self.em_queued = True
                threading.Thread(target=self._wait_and_play_em, daemon=True).start()
            elif os.path.exists(self.em_path) and self.settings.get("em_audio", True):
                self.audio_proc_em = subprocess.Popen(['aplay', '-q', self.em_path], stderr=subprocess.DEVNULL)

        elif trigger_type == "AEB" and self.settings.get("aeb_audio", True) and not em_busy:
            if fcw_busy: 
                self.audio_proc_fcw.terminate()  
            if not aeb_busy and os.path.exists(self.aeb_path):
                self.audio_proc_aeb = subprocess.Popen(['aplay', '-q', self.aeb_path], stderr=subprocess.DEVNULL)
                
        elif trigger_type == "FCW" and self.settings.get("fcw_audio", True) and not em_busy:
            if not aeb_busy and not fcw_busy and os.path.exists(self.fcw_path):
                self.audio_proc_fcw = subprocess.Popen(['aplay', '-q', self.fcw_path], stderr=subprocess.DEVNULL)

    def _wait_and_play_em(self):
        if self.audio_proc_aeb is not None:
            self.audio_proc_aeb.wait()
        if self.audio_proc_fcw is not None:
            self.audio_proc_fcw.wait()
            
        if os.path.exists(self.em_path) and self.settings.get("em_audio", True):
            self.audio_proc_em = subprocess.Popen(['aplay', '-q', self.em_path], stderr=subprocess.DEVNULL)
        
        self.em_queued = False
        
    def toggle_cam_recording(self):
            self.is_cam_recording = not self.is_cam_recording
            if self.is_cam_recording:
                self.btn_cam_record.setText("⏹️ Stop Recording")
                self.btn_cam_record.setStyleSheet("background-color: #e74c3c; color: white; font-size: 12px; font-weight: bold; padding: 4px; border-radius: 4px;")
                open(self.cam_record_flag, 'a').close()
            else:
                self.btn_cam_record.setText("⏺️ Start Recording")
                self.btn_cam_record.setStyleSheet("background-color: #34495e; color: white; font-size: 12px; font-weight: bold; padding: 4px; border-radius: 4px;")
                if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
        
    def toggle_tracking(self):
        self.is_tracking = not self.is_tracking
        if self.is_tracking:
            self.btn_track.setText("⏹️ Stop Track")
            self.btn_track.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 5px; border-radius: 4px;")
            open(self.track_record_flag, 'a').close()
        else:
            self.btn_track.setText("⏺️ Track")
            self.btn_track.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 5px; border-radius: 4px;")
            if os.path.exists(self.track_record_flag): 
                os.remove(self.track_record_flag)
                
    def toggle_ups_recording(self):
        self.is_ups_recording = not self.is_ups_recording
        if self.is_ups_recording:
            self.btn_ups_record.setText("⏹️ Stop Power Rec")
            self.btn_ups_record.setStyleSheet("background-color: #e74c3c; color: white; font-size: 14px; font-weight: bold; padding: 10px; border-radius: 4px; margin-top: 5px;")
            open(self.ups_record_flag, 'a').close()
        else:
            self.btn_ups_record.setText("⏺️ Record Power")
            self.btn_ups_record.setStyleSheet("background-color: #8e44ad; color: white; font-size: 14px; font-weight: bold; padding: 10px; border-radius: 4px; margin-top: 5px;")
            if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)
     
    def _create_toggle_btn(self, text, key):
        btn = QPushButton(f"{text}: {'ON' if self.settings.get(key, True) else 'OFF'}")
        color = "#27ae60" if self.settings.get(key, True) else "#e74c3c"
        btn.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 4px;")
        btn.clicked.connect(lambda: self._toggle_setting(btn, text, key))
        return btn

    def _toggle_setting(self, btn, text, key):
        self.settings[key] = not self.settings.get(key, True)
        color = "#27ae60" if self.settings[key] else "#e74c3c"
        btn.setText(f"{text}: {'ON' if self.settings[key] else 'OFF'}")
        btn.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 4px;")
        self.save_settings()

    def _update_dur(self, text):
        self.settings["em_duration"] = text
        self.save_settings()
    
    # --- HARDWARE CONTROLS ---
    def _change_volume(self, val):
        self.lbl_vol.setText(f"{val}%")
        subprocess.Popen(["amixer", "-q", "sset", "Master", f"{val}%"], stderr=subprocess.DEVNULL)
        subprocess.Popen(["amixer", "-q", "sset", "PCM", f"{val}%"], stderr=subprocess.DEVNULL)
        
    def _change_brightness(self, val):
        self.lbl_bri.setText(f"{val}%")
        
        if val == 100:
            self.dim_overlay.hide()
        else:
            self.dim_overlay.show()
            self.dim_overlay.raise_() # Make sure it stays on top of everything
            
            # Map 100-20% to an opacity of 0.0 to 0.8 (0 to 204 alpha)
            opacity = (100 - val) / 100.0
            alpha = int(opacity * 255)
            self.dim_overlay.setStyleSheet(f"background-color: rgba(0, 0, 0, {alpha});")

    def scan_wifi(self):
        self.btn_scan.setText("⏳...")
        self.btn_scan.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; font-size: 12px; padding: 6px; border-radius: 4px;")
        QApplication.processEvents() # Force UI update

        try:
            # Query NetworkManager for available networks
            result = subprocess.run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list"], capture_output=True, text=True)
            ssids = result.stdout.split('\n')
            
            # Clean up: remove empty strings, remove the Pi's own ARAS network, and sort alphabetically
            clean_ssids = sorted(list(set([s.strip() for s in ssids if s.strip() and s.strip() != "ARAS"])))
            
            self.combo_ssid.clear()
            self.combo_ssid.addItems(clean_ssids)
        except Exception as e:
            print(f"Wi-Fi Scan Error: {e}")

        # Reset button visually
        self.btn_scan.setText("🔄 Scan")
        self.btn_scan.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; font-size: 12px; padding: 6px; border-radius: 4px;")

    def toggle_hotspot(self):
        if self.btn_hotspot.isChecked():
            self.btn_hotspot.setText("📡 Starting Hotspot...")
            self.btn_hotspot.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; font-size: 13px; padding: 8px; border-radius: 4px;")
            QApplication.processEvents() 
            
            subprocess.Popen(["sudo", "nmcli", "device", "wifi", "hotspot", "ifname", "wlan0", "ssid", "ARAS", "password", "aras1234"])
            
            self.btn_hotspot.setText("📡 Stop ARAS Hotspot")
            self.btn_hotspot.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; font-size: 13px; padding: 8px; border-radius: 4px;")
        else:
            self.btn_hotspot.setText("📡 Stopping Hotspot...")
            self.btn_hotspot.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; font-size: 13px; padding: 8px; border-radius: 4px;")
            QApplication.processEvents() 
            
            # Delete the connection instead of just bringing it down to prevent the Pi from reconnecting to it
            subprocess.Popen(["sudo", "nmcli", "connection", "delete", "Hotspot"], stderr=subprocess.DEVNULL)
            subprocess.Popen(["sudo", "nmcli", "connection", "delete", "ARAS"], stderr=subprocess.DEVNULL)
            
            self.btn_hotspot.setText("📡 Start ARAS Hotspot")
            self.btn_hotspot.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; font-size: 13px; padding: 8px; border-radius: 4px;")

    def connect_to_wifi(self):
        ssid = self.combo_ssid.currentText() # Get selected item from dropdown
        pwd = self.input_pwd.text().strip()
        if not ssid: return
        
        self.btn_connect.setText("⏳ Connecting...")
        self.btn_connect.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; font-size: 12px; padding: 6px; border-radius: 4px;")
        QApplication.processEvents()
        
        def worker():
            subprocess.run(["sudo", "nmcli", "device", "wifi", "connect", ssid, "password", pwd], capture_output=True)
            
        threading.Thread(target=worker, daemon=True).start()
        
        QTimer.singleShot(6000, lambda: self.btn_connect.setText("🔗 Connect"))
        QTimer.singleShot(6000, lambda: self.btn_connect.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; font-size: 12px; padding: 6px; border-radius: 4px;"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # Keep the dimming overlay covering the whole screen
        if hasattr(self, 'dim_overlay'):
            self.dim_overlay.resize(self.size())
            
        # Force the camera feed to immediately recalculate its 16:9 bounds
        if hasattr(self, 'lbl_video') and self.lbl_video.pixmap() and not self.lbl_video.pixmap().isNull():
            self.lbl_video.setPixmap(self.lbl_video.pixmap().scaled(
                self.lbl_video.size(), 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            ))
            
    def set_video_fullscreen(self, make_fullscreen: bool):
        if make_fullscreen and not self.is_video_fullscreen:
            self.is_video_fullscreen = True
            
            # Hide the UI clutter
            self.sim_group.hide()
            self.right_widget.hide()
            self.tabs.tabBar().hide()
            self.top_toolbar.hide()
            
            # Remove padding so the video bleeds perfectly to the screen edges
            self.vision_layout.setContentsMargins(0, 0, 0, 0)
            self.lbl_video.setStyleSheet("background-color: black; border: none;")
            
        elif not make_fullscreen and self.is_video_fullscreen:
            self.is_video_fullscreen = False
            
            # Restore the UI
            self.sim_group.show()
            self.right_widget.show()
            self.tabs.tabBar().show()
            self.top_toolbar.show()
            
            # Restore the dashboard styling
            self.vision_layout.setContentsMargins(5, 5, 5, 5)
            self.lbl_video.setStyleSheet("background-color: black; border: 2px solid #34495e; border-radius: 6px;")

    def toggle_video_fullscreen(self):
        # Fallback allowing you to double-tap the video to toggle it
        self.set_video_fullscreen(not self.is_video_fullscreen)
    
    def _toggle_radar_fullscreen(self, target_terminal_name, make_fullscreen):
        if make_fullscreen and not self.is_radar_fullscreen:
            self.is_radar_fullscreen = True
            
            # 1. Hide the Alert Panel
            self.radar_alert_panel.hide()
            
            # 2. Hide Global UI
            self.tabs.tabBar().hide()
            self.top_toolbar.hide()
            
            # 3. Hide the OTHER terminal
            for name, group in self.radar_groups.items():
                if name != target_terminal_name:
                    group.hide()
                    
            # 4. Make text slightly larger for fullscreen reading
            font = QFont("Consolas", 11)
            self.terminals[target_terminal_name].setFont(font)
            
        elif not make_fullscreen and self.is_radar_fullscreen:
            self.is_radar_fullscreen = False
            
            # 1. Restore the Alert Panel
            self.radar_alert_panel.show()
            
            # 2. Restore Global UI
            self.tabs.tabBar().show()
            self.top_toolbar.show()
            
            # 3. Show ALL terminals again
            for group in self.radar_groups.values():
                group.show()
                
            # 4. Revert text size
            font = QFont("Consolas", 9)
            for terminal in self.terminals.values():
                terminal.setFont(font)
                
    def _toggle_vision_terminal_fullscreen(self, make_fullscreen: bool):
        if not hasattr(self, 'is_vision_term_fullscreen'):
            self.is_vision_term_fullscreen = False
            
        if make_fullscreen and not self.is_vision_term_fullscreen:
            self.is_vision_term_fullscreen = True
            
            # Hide the left half of the screen (Video & Sim Controls)
            self.lbl_video.parentWidget().hide()
            
            # Hide top toolbar & tabs
            self.tabs.tabBar().hide()
            self.top_toolbar.hide()
            
            # Hide siblings in the right column
            self.vision_detections_widget.hide()
            self.btn_cam_record.hide()
            
            # Make text larger for fullscreen reading
            self.vision_console.setFont(QFont("Consolas", 11))
            
        elif not make_fullscreen and self.is_vision_term_fullscreen:
            self.is_vision_term_fullscreen = False
            
            # Restore left half
            self.lbl_video.parentWidget().show()
            
            # Restore UI
            self.tabs.tabBar().show()
            self.top_toolbar.show()
            
            # Restore right column siblings
            self.vision_detections_widget.show()
            self.btn_cam_record.show()
            
            # Revert font
            self.vision_console.setFont(QFont("Consolas", 8))
            
if __name__ == "__main__":
    sync_system_time()
    
    # --- CRITICAL: FORCE NATIVE 800x480 SCALING ---
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_Use96Dpi, True)
    
    app = QApplication(sys.argv)
    project_root = os.path.dirname(os.path.abspath(__file__))
    window = LauncherMainWindow(build_modules(project_root), project_root)
    
    # Launch purely in Full Screen
    window.showFullScreen()
    #window.show()
    sys.exit(app.exec_())