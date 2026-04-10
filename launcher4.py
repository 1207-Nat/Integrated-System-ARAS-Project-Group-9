import os
import sys
import threading
import subprocess
import time
import base64
import json
import math
from dataclasses import dataclass, field
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QPushButton, QToolBar, QWidget, 
    QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout, QSizePolicy,
    QPinchGesture
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QEvent
from PyQt5.QtGui import QFont, QPixmap, QImage, QPainter, QColor


def sync_system_time():
    print("[SYSTEM] Checking internet connection for time sync...")
    try:
        subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "systemctl", "restart", "systemd-timesyncd"], timeout=5)
    except:
        pass


class NativeMapWidget(QWidget):
    def __init__(self, project_root):
        super().__init__()
        self.tiles_dir = os.path.join(project_root, "map_tiles")
        self.zoom = 14
        self.marker_lat = 2.94941 
        self.marker_lon = 101.87505
        self.view_lat = 2.94941
        self.view_lon = 101.87505
        self.auto_follow = True
        self.last_mouse_pos = None
        self.setCursor(Qt.OpenHandCursor)
        self.tile_cache = {}
        self.grabGesture(Qt.PinchGesture)
        self.pinch_accum = 1.0

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

    def zoom_at_cursor(self, pos, zoom_in):
        if zoom_in and self.zoom >= 18: return
        if not zoom_in and self.zoom <= 10: return

        ex, ey = self.deg2num(self.view_lat, self.view_lon, self.zoom)
        dx = pos.x() - self.width() / 2
        dy = pos.y() - self.height() / 2
        mouse_lat, mouse_lon = self.num2deg(ex + (dx / 256.0), ey + (dy / 256.0), self.zoom)
        self.zoom += 1 if zoom_in else -1
        mx2, my2 = self.deg2num(mouse_lat, mouse_lon, self.zoom)
        new_ex = mx2 - (dx / 256.0)
        new_ey = my2 - (dy / 256.0)
        self.view_lat, self.view_lon = self.num2deg(new_ex, new_ey, self.zoom)
        self.update()

    def event(self, event):
        if event.type() == QEvent.Gesture: return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        pinch = event.gesture(Qt.PinchGesture)
        if pinch:
            if pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
                self.pinch_accum *= pinch.scaleFactor()
                if self.pinch_accum > 1.3: 
                    self.auto_follow = False
                    self.zoom_at_cursor(pinch.centerPoint().toPoint(), True)
                    self.pinch_accum = 1.0
                elif self.pinch_accum < 0.7:
                    self.auto_follow = False
                    self.zoom_at_cursor(pinch.centerPoint().toPoint(), False)
                    self.pinch_accum = 1.0
            if pinch.state() == Qt.GestureFinished: self.pinch_accum = 1.0
            return True
        return False

    def wheelEvent(self, event):
        self.auto_follow = False
        zoom_in = event.angleDelta().y() > 0
        self.zoom_at_cursor(event.pos(), zoom_in)

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

        ex, ey = self.deg2num(self.view_lat, self.view_lon, self.zoom)
        cx, cy = int(self.width()/2), int(self.height()/2)
        
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                tx, ty = int(ex) + dx, int(ey) + dy
                path = f"{self.tiles_dir}/{self.zoom}/{tx}/{ty}.png"
                if os.path.exists(path):
                    key = f"{self.zoom}_{tx}_{ty}"
                    if key not in self.tile_cache:
                        self.tile_cache[key] = QPixmap(path)
                    pix = self.tile_cache[key]
                    draw_x = cx + (tx - ex) * 256
                    draw_y = cy + (ty - ey) * 256
                    painter.drawPixmap(int(draw_x), int(draw_y), pix)

        mx, my = self.deg2num(self.marker_lat, self.marker_lon, self.zoom)
        m_screen_x = cx + (mx - ex) * 256
        m_screen_y = cy + (my - ey) * 256
        
        painter.setBrush(Qt.red)
        painter.setPen(Qt.white)
        painter.drawEllipse(int(m_screen_x)-8, int(m_screen_y)-8, 16, 16)
        
        if not self.auto_follow:
            painter.setPen(Qt.yellow)
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.drawText(15, 30, "📍 Manual Pan Mode (Click 'Reset View' to follow car)")        


class LogSignal(QObject):
    new_log = pyqtSignal(str, str)
    new_frame = pyqtSignal(bytes)
    new_detection = pyqtSignal(str)
    new_gps = pyqtSignal(dict)
    new_ups = pyqtSignal(dict)
    new_alert = pyqtSignal(str, dict)  # alert_type and data dict
    play_audio = pyqtSignal(str) 


@dataclass
class ModuleConfig:
    name: str
    script_relative_path: str
    cwd_relative: Optional[str] = None
    python_executable: Optional[str] = None
    startup_delay: float = 0.0

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
            
            # --- AUDIO INTERCEPTOR ---
            if "__AUDIO_TRIGGER__:" in line_str:
                alert_type = line_str.split("__AUDIO_TRIGGER__:")[1].strip()
                self.log_signal.play_audio.emit(alert_type)
                continue
            
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
        ModuleRunner(ModuleConfig("GPS", os.path.join("3_LC76G_GPS_Module", "gps_headless.py"), startup_delay=1.0), root),
        ModuleRunner(ModuleConfig("UPS_Monitor", os.path.join("4_UPS_HAT_E", "ups_headless.py"), python_executable="python3"), root),
    ]


class LauncherMainWindow(QMainWindow):
    def __init__(self, modules: List[ModuleRunner], project_root: str):
        super().__init__()
        self.modules = modules
        self.project_root = project_root
        self.terminals = {}
        
        self.cam_record_flag = os.path.join(self.project_root, "1_TrafficSign", ".record_flag")
        self.ups_record_flag = os.path.join(self.project_root, "4_UPS_HAT_E", ".ups_record_flag")
        # Add the GPS tracking flag pointing to the RAM disk
        self.track_record_flag = "/dev/shm/aras_tracking.flag"
        
        if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
        if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)
        # Clean up any leftover tracking flags on startup
        if os.path.exists(self.track_record_flag): os.remove(self.track_record_flag)
        
        self.is_cam_recording = False
        self.is_ups_recording = False
        self.is_tracking = False
        
        # Audio Settings Flags
        self.aeb_audio_enabled = True
        self.fcw_audio_enabled = True
        
        subprocess.run(["sudo", "pkill", "-9", "-f", "integrated.py"], stderr=subprocess.DEVNULL)
        
        self.signals = LogSignal()
        self.signals.new_log.connect(self.append_log)
        self.signals.new_frame.connect(self.update_video)
        self.signals.new_detection.connect(self.update_detections)
        self.signals.new_gps.connect(self.update_gps)
        self.signals.new_ups.connect(self.update_ups)
        self.signals.new_alert.connect(self.update_alert)
        self.signals.play_audio.connect(self.handle_audio_trigger)

        # File paths for Linux aplay
        self.aeb_path = os.path.join(self.project_root, "Asset", "aeb.wav")
        self.fcw_path = os.path.join(self.project_root, "Asset", "fcw.wav")
        self.audio_proc_aeb = None
        self.audio_proc_fcw = None
        
        # Alert timeout timer
        self.alert_timeout_timer = None

        self.init_ui()
        
        for m in self.modules:
            m.log_signal = self.signals
            m.start()

    def handle_audio_trigger(self, trigger_type):
        # Check if audio processes are currently running
        aeb_busy = self.audio_proc_aeb is not None and self.audio_proc_aeb.poll() is None
        fcw_busy = self.audio_proc_fcw is not None and self.audio_proc_fcw.poll() is None

        if trigger_type == "AEB" and self.aeb_audio_enabled:
            # AEB is critical: Interrupt lower warnings immediately
            if fcw_busy: 
                self.audio_proc_fcw.terminate() 
            
            # Only start AEB if it isn't already playing (prevents stuttering)
            if not aeb_busy and os.path.exists(self.aeb_path):
                self.audio_proc_aeb = subprocess.Popen(['aplay', '-q', self.aeb_path], stderr=subprocess.DEVNULL)
                
        elif trigger_type == "FCW" and self.fcw_audio_enabled:
            # Only play FCW if NOTHING else is playing. 
            # This allows the sound to finish its full duration.
            if not aeb_busy and not fcw_busy and os.path.exists(self.fcw_path):
                self.audio_proc_fcw = subprocess.Popen(['aplay', '-q', self.fcw_path], stderr=subprocess.DEVNULL)
                
        elif trigger_type == "SAFE":
            # REMOVED: self.audio_proc_fcw.terminate()
            # By removing the terminate here, the current beep will finish playing 
            # even if you step away, which sounds much more natural.
            pass

    def init_ui(self):
        self.setWindowTitle("ARAS Master Interface")
        self.setMinimumSize(900, 650)
        self.resize(1300, 850)

        toolbar = QToolBar("Controls")
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        btn_stop = QPushButton("⏹️ Graceful Stop All")
        btn_stop.setStyleSheet("background-color: #d97706; color: white; font-weight: bold; padding: 6px; border: 1px solid #b45f06; border-radius: 4px;")
        btn_stop.clicked.connect(self.close)
        toolbar.addWidget(btn_stop)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_radar_tab()
        self._build_vision_tab()
        self._build_gps_tab()
        self._build_ups_tab()
        self._build_audio_tab()

    def _build_audio_tab(self):
        tab_audio = QWidget()
        tab_audio.setStyleSheet("background-color: #2c3e50;")
        layout = QVBoxLayout(tab_audio)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(30)

        group_toggles = QGroupBox("Audio Alert Modules")
        group_toggles.setStyleSheet("QGroupBox { color: white; font-weight: bold; font-size: 18px; border: 2px solid #7f8c8d; border-radius: 8px; margin-top: 15px;} QGroupBox::title { subcontrol-origin: margin; left: 15px; }")
        toggles_layout = QVBoxLayout(group_toggles)
        toggles_layout.setSpacing(15)
        toggles_layout.setContentsMargins(20, 30, 20, 20)

        self.btn_aeb_toggle = QPushButton("🚨 AEB Sound: ON")
        self.btn_aeb_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 20px; font-weight: bold; padding: 20px; border-radius: 10px;")
        self.btn_aeb_toggle.clicked.connect(self.toggle_aeb)
        toggles_layout.addWidget(self.btn_aeb_toggle)

        self.btn_fcw_toggle = QPushButton("🚀 🥧 🔥FCW Sound: ON")
        self.btn_fcw_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 20px; font-weight: bold; padding: 20px; border-radius: 10px;")
        self.btn_fcw_toggle.clicked.connect(self.toggle_fcw)
        toggles_layout.addWidget(self.btn_fcw_toggle)

        layout.addWidget(group_toggles)
        layout.addStretch()
        self.tabs.addTab(tab_audio, "🔊 Audio Settings")

    def toggle_aeb(self):
        self.aeb_audio_enabled = not self.aeb_audio_enabled
        if self.aeb_audio_enabled:
            self.btn_aeb_toggle.setText("🚨 AEB Sound: ON")
            self.btn_aeb_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 20px; font-weight: bold; padding: 20px; border-radius: 10px;")
        else:
            self.btn_aeb_toggle.setText("🔇 AEB Sound: OFF")
            self.btn_aeb_toggle.setStyleSheet("background-color: #e74c3c; color: white; font-size: 20px; font-weight: bold; padding: 20px; border-radius: 10px;")

    def toggle_fcw(self):
        self.fcw_audio_enabled = not self.fcw_audio_enabled
        if self.fcw_audio_enabled:
            self.btn_fcw_toggle.setText("⚠️ FCW Sound: ON")
            self.btn_fcw_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 20px; font-weight: bold; padding: 20px; border-radius: 10px;")
        else:
            self.btn_fcw_toggle.setText("🔇 FCW Sound: OFF")
            self.btn_fcw_toggle.setStyleSheet("background-color: #e74c3c; color: white; font-size: 20px; font-weight: bold; padding: 20px; border-radius: 10px;")


    def _build_radar_tab(self):
        tab_radar = QWidget()
        main_layout = QVBoxLayout(tab_radar)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        font = QFont("Consolas", 10)
        
        # Radar terminals at the top
        terminals_widget = QWidget()
        terminals_layout = QHBoxLayout(terminals_widget)
        terminals_layout.setContentsMargins(0, 0, 0, 0)
        for name in ["LD2451_Front", "LD2417_Back"]:
            group = QGroupBox(name + " Terminal")
            l = QVBoxLayout(group)
            t = QTextEdit()
            t.setReadOnly(True)
            t.setFont(font)
            t.setStyleSheet("background-color: #1e1e1e; color: #00ff00;")
            l.addWidget(t)
            terminals_layout.addWidget(group)
            self.terminals[name] = t
        
        main_layout.addWidget(terminals_widget, stretch=1)
        
        # Alert status panel at the bottom (below LD2451_Front)
        alert_panel = QWidget()
        alert_layout = QHBoxLayout(alert_panel)
        alert_layout.setContentsMargins(5, 5, 5, 5)
        alert_layout.setSpacing(15)
        alert_panel.setMaximumHeight(100)
        
        self.lbl_current_alert = QLabel("✅ SAFE")
        self.lbl_current_alert.setAlignment(Qt.AlignCenter)
        self.lbl_current_alert.setStyleSheet("background-color: #27ae60; color: white; font-size: 18pt; font-weight: bold; border-radius: 5px; padding: 10px;")
        alert_layout.addWidget(self.lbl_current_alert, stretch=1)
        
        self.lbl_alert_distance = QLabel("Distance: -- m")
        self.lbl_alert_distance.setStyleSheet("color: white; font-size: 12px;")
        self.lbl_alert_distance.setAlignment(Qt.AlignCenter)
        alert_layout.addWidget(self.lbl_alert_distance, stretch=1)
        
        self.lbl_alert_speed = QLabel("Speed: -- km/h")
        self.lbl_alert_speed.setStyleSheet("color: white; font-size: 12px;")
        self.lbl_alert_speed.setAlignment(Qt.AlignCenter)
        alert_layout.addWidget(self.lbl_alert_speed, stretch=1)
        
        alert_panel.setStyleSheet("background-color: #2c3e50; border-radius: 5px;")
        main_layout.addWidget(alert_panel)
        
        self.tabs.addTab(tab_radar, "📡 Radar Terminals")

    def _build_vision_tab(self):
        tab_vision = QWidget()
        vision_layout = QHBoxLayout(tab_vision)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0,0,0,0)
        
        self.lbl_video = QLabel("Waiting for camera feed...")
        self.lbl_video.setAlignment(Qt.AlignCenter)
        self.lbl_video.setStyleSheet("background-color: black; color: white; font-size: 20px;")
        self.lbl_video.setMinimumSize(320, 240)
        self.lbl_video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        self.btn_cam_record = QPushButton("⏺️ Start Camera Recording")
        self.btn_cam_record.setStyleSheet("background-color: #7f8c8d; color: white; font-size: 16px; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.btn_cam_record.clicked.connect(self.toggle_cam_recording)
        
        left_layout.addWidget(self.lbl_video, stretch=1)
        left_layout.addWidget(self.btn_cam_record)
        vision_layout.addWidget(left_panel, stretch=3)
        
        tiles_container = QWidget()
        tiles_layout = QVBoxLayout(tiles_container)
        
        self.lbl_speed_sign = QLabel("N/A")
        self.lbl_speed_sign.setAlignment(Qt.AlignCenter)
        self.lbl_speed_sign.setStyleSheet("background-color: white; color: black; border: 4px solid red; border-radius: 40px; font-size: 30px; font-weight: bold; margin: 5px;")
        
        self.lbl_control_sign = QLabel("No Signs")
        self.lbl_control_sign.setAlignment(Qt.AlignCenter)
        self.lbl_control_sign.setStyleSheet("background-color: #34495e; color: white; font-size: 20px; font-weight: bold; border-radius: 10px; margin: 5px;")

        self.lbl_hazard_sign = QLabel("Road Clear")
        self.lbl_hazard_sign.setAlignment(Qt.AlignCenter)
        self.lbl_hazard_sign.setStyleSheet("background-color: #27ae60; color: white; font-size: 20px; font-weight: bold; border-radius: 10px; margin: 5px;")
        
        self.lbl_vru_sign = QLabel("Clear")
        self.lbl_vru_sign.setAlignment(Qt.AlignCenter)
        self.lbl_vru_sign.setStyleSheet("background-color: #34495e; color: white; font-size: 20px; font-weight: bold; border-radius: 10px; margin: 5px;")
        
        tiles_layout.addWidget(QLabel("<b>Speed Limit</b>"), alignment=Qt.AlignCenter)
        tiles_layout.addWidget(self.lbl_speed_sign, stretch=1)
        tiles_layout.addWidget(QLabel("<b>Traffic Control</b>"), alignment=Qt.AlignCenter)
        tiles_layout.addWidget(self.lbl_control_sign, stretch=1)
        tiles_layout.addWidget(QLabel("<b>Road Hazards</b>"), alignment=Qt.AlignCenter)
        tiles_layout.addWidget(self.lbl_hazard_sign, stretch=1)
        tiles_layout.addWidget(QLabel("<b>Pedestrians / Bikes</b>"), alignment=Qt.AlignCenter)
        tiles_layout.addWidget(self.lbl_vru_sign, stretch=1)
        
        vision_layout.addWidget(tiles_container, stretch=1)
        self.tabs.addTab(tab_vision, "📷 AI Vision Detections")

    def _build_gps_tab(self):
        tab_gps = QWidget()
        tab_gps.setStyleSheet("background-color: #2c3e50;")
        gps_layout = QHBoxLayout(tab_gps)
        
        left_panel = QWidget()
        left_panel.setFixedWidth(450)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)

        lbl_style = "color: #ecf0f1; font-size: 14px;"
        val_style = "color: #f1c40f; font-size: 16px; font-weight: bold;"

        self.lbl_gps_status = QLabel("STATUS: INITIALIZING")
        self.lbl_gps_status.setStyleSheet(val_style)
        self.lbl_gps_status.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_status)

        self.lbl_gps_limit = QLabel("LIMIT: Not Available")
        self.lbl_gps_limit.setStyleSheet("background-color: #c0392b; color: white; font-size: 20px; font-weight: bold; padding: 10px; border-radius: 5px;")
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

        lbl_odo_title = QLabel("TOTAL DISTANCE (ODOMETER):")
        lbl_odo_title.setStyleSheet(lbl_style)
        lbl_odo_title.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(lbl_odo_title)

        self.lbl_gps_odo = QLabel("0.0 meters")
        self.lbl_gps_odo.setStyleSheet("color: #3498db; font-size: 18px; font-weight: bold;")
        self.lbl_gps_odo.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_odo)

        self.lbl_gps_coords = QLabel("Waiting for fix...")
        self.lbl_gps_coords.setStyleSheet(lbl_style)
        self.lbl_gps_coords.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.lbl_gps_coords)

        gps_ctrl_frame = QWidget()
        gps_ctrl_layout = QHBoxLayout(gps_ctrl_frame)
        gps_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_track = QPushButton("⏺️ Start Tracking Session")
        self.btn_track.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.btn_track.clicked.connect(self.toggle_tracking)
        
        btn_reset_view = QPushButton("🎯 Reset View (Follow)")
        btn_reset_view.setStyleSheet("background-color: #7f8c8d; color: white; padding: 10px; border-radius: 5px;")
        btn_reset_view.clicked.connect(lambda: setattr(self.map_view, 'auto_follow', True))
        
        gps_ctrl_layout.addWidget(self.btn_track)
        gps_ctrl_layout.addWidget(btn_reset_view)
        left_layout.addWidget(gps_ctrl_frame)

        self.gps_console = QTextEdit()
        self.gps_console.setReadOnly(True)
        self.gps_console.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace; font-size: 12px; border: none;")
        left_layout.addWidget(self.gps_console)

        gps_layout.addWidget(left_panel)
        self.map_view = NativeMapWidget(self.project_root)
        gps_layout.addWidget(self.map_view, stretch=1)
        self.tabs.addTab(tab_gps, "📍 GPS Dashboard")

    def _build_ups_tab(self):
        tab_ups = QWidget()
        tab_ups.setStyleSheet("background-color: #2c3e50;")
        main_layout = QVBoxLayout(tab_ups)

        top_layout = QHBoxLayout()
        
        self.lbl_big_power = QLabel("0.00 W\nIdle")
        self.lbl_big_power.setAlignment(Qt.AlignCenter)
        self.lbl_big_power.setStyleSheet("background-color: #34495e; color: white; font-size: 28px; font-weight: bold; border-radius: 10px; padding: 20px;")
        
        self.lbl_big_wh = QLabel("0.000 Wh\nUsed (Session)")
        self.lbl_big_wh.setAlignment(Qt.AlignCenter)
        self.lbl_big_wh.setStyleSheet("background-color: #34495e; color: white; font-size: 28px; font-weight: bold; border-radius: 10px; padding: 20px;")
        
        self.lbl_big_time = QLabel("-- min\nRemaining")
        self.lbl_big_time.setAlignment(Qt.AlignCenter)
        self.lbl_big_time.setStyleSheet("background-color: #34495e; color: white; font-size: 28px; font-weight: bold; border-radius: 10px; padding: 20px;")
        
        top_layout.addWidget(self.lbl_big_power)
        top_layout.addWidget(self.lbl_big_wh)
        top_layout.addWidget(self.lbl_big_time)
        main_layout.addLayout(top_layout, stretch=1)

        bottom_layout = QHBoxLayout()
        
        left = QVBoxLayout()
        val_style = "color: #f1c40f; font-size: 20px; font-weight: bold;"
        lbl_style = "color: white; font-size: 14px;"
        
        group_bat = QGroupBox("Battery Status")
        group_bat.setStyleSheet("QGroupBox { color: white; font-weight: bold; border: 1px solid gray; border-radius: 5px; margin-top: 10px;} QGroupBox::title { subcontrol-origin: margin; left: 10px; }")
        gl_bat = QGridLayout(group_bat)
        
        self.lbl_ups_pct = QLabel("0%")
        self.lbl_ups_pct.setStyleSheet("color: #2ecc71; font-size: 40px; font-weight: bold;")
        self.lbl_ups_pct.setAlignment(Qt.AlignCenter)
        gl_bat.addWidget(self.lbl_ups_pct, 0, 0, 1, 2)
        
        self.lbl_ups_bat_v = QLabel("0 mV"); self.lbl_ups_bat_v.setStyleSheet(val_style)
        self.lbl_ups_bat_c = QLabel("0 mA"); self.lbl_ups_bat_c.setStyleSheet(val_style)
        self.lbl_ups_cap = QLabel("0 mAh"); self.lbl_ups_cap.setStyleSheet(val_style)
        
        l1=QLabel("Voltage:"); l1.setStyleSheet(lbl_style)
        l2=QLabel("Current:"); l2.setStyleSheet(lbl_style)
        l3=QLabel("Capacity:"); l3.setStyleSheet(lbl_style)
        
        gl_bat.addWidget(l1, 1, 0); gl_bat.addWidget(self.lbl_ups_bat_v, 1, 1)
        gl_bat.addWidget(l2, 2, 0); gl_bat.addWidget(self.lbl_ups_bat_c, 2, 1)
        gl_bat.addWidget(l3, 3, 0); gl_bat.addWidget(self.lbl_ups_cap, 3, 1)
        left.addWidget(group_bat)
        bottom_layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        
        group_vbus = QGroupBox("VBUS (Input Power)")
        group_vbus.setStyleSheet("QGroupBox { color: white; font-weight: bold; border: 1px solid gray; border-radius: 5px; margin-top: 10px;} QGroupBox::title { subcontrol-origin: margin; left: 10px; }")
        gl_vbus = QGridLayout(group_vbus)
        self.lbl_ups_vbus_v = QLabel("0 mV"); self.lbl_ups_vbus_v.setStyleSheet(val_style)
        self.lbl_ups_vbus_p = QLabel("0 mW"); self.lbl_ups_vbus_p.setStyleSheet(val_style)
        l5=QLabel("Voltage:"); l5.setStyleSheet(lbl_style)
        l6=QLabel("Power:"); l6.setStyleSheet(lbl_style)
        gl_vbus.addWidget(l5, 0, 0); gl_vbus.addWidget(self.lbl_ups_vbus_v, 0, 1)
        gl_vbus.addWidget(l6, 1, 0); gl_vbus.addWidget(self.lbl_ups_vbus_p, 1, 1)
        right.addWidget(group_vbus)

        group_cells = QGroupBox("Cell Voltages (mV)")
        group_cells.setStyleSheet("QGroupBox { color: white; font-weight: bold; border: 1px solid gray; border-radius: 5px; margin-top: 10px;} QGroupBox::title { subcontrol-origin: margin; left: 10px; }")
        gl_cells = QHBoxLayout(group_cells)
        self.lbl_c1 = QLabel("0"); self.lbl_c1.setStyleSheet(val_style); self.lbl_c1.setAlignment(Qt.AlignCenter)
        self.lbl_c2 = QLabel("0"); self.lbl_c2.setStyleSheet(val_style); self.lbl_c2.setAlignment(Qt.AlignCenter)
        self.lbl_c3 = QLabel("0"); self.lbl_c3.setStyleSheet(val_style); self.lbl_c3.setAlignment(Qt.AlignCenter)
        self.lbl_c4 = QLabel("0"); self.lbl_c4.setStyleSheet(val_style); self.lbl_c4.setAlignment(Qt.AlignCenter)
        gl_cells.addWidget(self.lbl_c1); gl_cells.addWidget(self.lbl_c2)
        gl_cells.addWidget(self.lbl_c3); gl_cells.addWidget(self.lbl_c4)
        right.addWidget(group_cells)
        
        self.btn_ups_record = QPushButton("⏺️ Start Power Recording")
        self.btn_ups_record.setStyleSheet("background-color: #8e44ad; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px; margin-top: 20px;")
        self.btn_ups_record.clicked.connect(self.toggle_ups_recording)
        right.addWidget(self.btn_ups_record)
        
        bottom_layout.addLayout(right, stretch=1)
        main_layout.addLayout(bottom_layout, stretch=2)
        
        self.tabs.addTab(tab_ups, "🔋 UPS Dashboard")

    def toggle_cam_recording(self):
        self.is_cam_recording = not self.is_cam_recording
        if self.is_cam_recording:
            self.btn_cam_record.setText("⏹️ Stop Recording")
            self.btn_cam_record.setStyleSheet("background-color: #e74c3c; color: white; font-size: 16px; font-weight: bold; padding: 10px; border-radius: 5px;")
            open(self.cam_record_flag, 'a').close()
        else:
            self.btn_cam_record.setText("⏺️ Start Recording")
            self.btn_cam_record.setStyleSheet("background-color: #7f8c8d; color: white; font-size: 16px; font-weight: bold; padding: 10px; border-radius: 5px;")
            if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
    
    def toggle_tracking(self):
        # Manage its own state, not the camera's state
        self.is_tracking = not self.is_tracking
        
        if self.is_tracking:
            self.btn_track.setText("⏹️ Stop Tracking Session")
            self.btn_track.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
            # Create the RAM flag to tell gps_headless.py to start plotting
            open(self.track_record_flag, 'a').close()
        else:
            self.btn_track.setText("⏺️ Start Tracking Session")
            self.btn_track.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
            # Delete the RAM flag, triggering the backend to save the image
            if os.path.exists(self.track_record_flag): 
                os.remove(self.track_record_flag)

    def toggle_ups_recording(self):
        self.is_ups_recording = not self.is_ups_recording
        if self.is_ups_recording:
            self.btn_ups_record.setText("⏹️ Stop Power Recording")
            self.btn_ups_record.setStyleSheet("background-color: #e74c3c; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px; margin-top: 20px;")
            open(self.ups_record_flag, 'a').close()
        else:
            self.btn_ups_record.setText("⏺️ Start Power Recording")
            self.btn_ups_record.setStyleSheet("background-color: #8e44ad; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px; margin-top: 20px;")
            if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)

    def append_log(self, name, text):
        if name == "UPS_Monitor":
            pass 
        elif name == "GPS":
            self.gps_console.append(text)
            self.gps_console.verticalScrollBar().setValue(self.gps_console.verticalScrollBar().maximum())
        elif name in self.terminals:
            self.terminals[name].append(text)
            self.terminals[name].verticalScrollBar().setValue(self.terminals[name].verticalScrollBar().maximum())
            
            # Parse radar data for alerts (LD2451_Front only)
            if name == "LD2451_Front":
                if "Target" in text and "Distance=" in text:
                    self._parse_radar_alert(text)

    def _parse_radar_alert(self, log_text):
        """Parse radar log text to extract distance and speed, then determine alert level"""
        try:
            # Extract distance and speed from lines like:
            # "  🎯 Target 1: Distance=12 m | Speed=25 km/h  | Angle=-5°"
            import re
            match = re.search(r'Distance=(\d+)', log_text)
            speed_match = re.search(r'Speed=(\d+)', log_text)
            
            if match and speed_match:
                distance = int(match.group(1))
                speed = int(speed_match.group(1))
                
                # Use same thresholds as LED2.py
                AEB_DIST_M = 3.0
                FCW_DIST_M = 8.0
                FAST_SPEED_KMH = 5.0
                MID_SPEED_KMH = 4.0
                
                # Determine alert level
                alert_type = "SAFE"
                if distance <= AEB_DIST_M and speed >= FAST_SPEED_KMH:
                    alert_type = "AEB"
                elif distance <= FCW_DIST_M or speed >= MID_SPEED_KMH:
                    alert_type = "FCW"
                
                self.signals.new_alert.emit(alert_type, {'distance': distance, 'speed': speed})
        except Exception:
            pass

    def update_video(self, img_bytes):
        image = QImage.fromData(img_bytes)
        if not image.isNull():
            self.lbl_video.setPixmap(QPixmap.fromImage(image).scaled(
                self.lbl_video.width(), self.lbl_video.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

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
            self.lbl_hazard_sign.setStyleSheet("background-color: #e67e22; color: white; font-size: 24px; font-weight: bold; border-radius: 10px; margin: 5px;")
        else:
            self.lbl_hazard_sign.setText("Road Clear")
            self.lbl_hazard_sign.setStyleSheet("background-color: #27ae60; color: white; font-size: 20px; font-weight: bold; border-radius: 10px; margin: 5px;")

        if control_texts:
            self.lbl_control_sign.setText("\n".join(set(control_texts)))
            if "RED LIGHT" in control_texts or "STOP SIGN" in control_texts:
                self.lbl_control_sign.setStyleSheet("background-color: #c0392b; color: white; font-size: 24px; font-weight: bold; border-radius: 10px; margin: 5px;")
            elif "YELLOW LIGHT" in control_texts or "GIVE WAY" in control_texts:
                self.lbl_control_sign.setStyleSheet("background-color: #f39c12; color: white; font-size: 24px; font-weight: bold; border-radius: 10px; margin: 5px;")
            else:
                self.lbl_control_sign.setStyleSheet("background-color: #2980b9; color: white; font-size: 24px; font-weight: bold; border-radius: 10px; margin: 5px;")
        else:
            self.lbl_control_sign.setText("No Signs")
            self.lbl_control_sign.setStyleSheet("background-color: #34495e; color: white; font-size: 20px; font-weight: bold; border-radius: 10px; margin: 5px;")

        if vru_texts:
            self.lbl_vru_sign.setText("\n".join(set(vru_texts)))
            self.lbl_vru_sign.setStyleSheet("background-color: #f1c40f; color: black; font-size: 24px; font-weight: bold; border-radius: 10px; margin: 5px;")
        else:
            self.lbl_vru_sign.setText("Clear")
            self.lbl_vru_sign.setStyleSheet("background-color: #34495e; color: white; font-size: 20px; font-weight: bold; border-radius: 10px; margin: 5px;")

    def update_gps(self, data):
        self.lbl_gps_status.setText(f"STATUS: {data.get('status', 'SEARCHING')} | Sats: {data.get('sats', 0)}")
        self.lbl_gps_limit.setText(f"LIMIT: {data.get('limit', 'Not Available')}")
        self.lbl_gps_mod_speed.setText(f"Module: {data.get('speed', 0.0):.1f} km/h")
        self.lbl_gps_calc_speed.setText(f"Calc: {data.get('calc_speed', 0.0):.1f} km/h")
        self.lbl_gps_coords.setText(f"Lat: {data.get('lat', 0):.6f} | Lon: {data.get('lon', 0):.6f}")
        dist = data.get('odo', 0)
        self.lbl_gps_odo.setText(f"{dist:.1f} meters" if dist < 1000 else f"{dist/1000.0:.3f} km")
        self.map_view.updatePos(data.get('lat', 0), data.get('lon', 0))

        try:
            with open("/dev/shm/aras_gps_data.json", "w") as f:
                json.dump({
                    "speed": data.get('speed', 0.0),
                    "lat": data.get('lat', 0.0),
                    "lon": data.get('lon', 0.0),
                    "status": data.get('status', 'SEARCHING'),
                    "area": data.get('area', 'Unknown Area') 
                }, f)
                
        except Exception:
            pass
        
    def update_ups(self, data):
        power_w = data.get("bat_power_w", 0)
        
        if power_w > 0:
            self.lbl_big_power.setText(f"+{power_w:.2f} W\nCharging")
            self.lbl_big_power.setStyleSheet("background-color: #27ae60; color: white; font-size: 28px; font-weight: bold; border-radius: 10px; padding: 15px;")
        elif power_w < 0:
            self.lbl_big_power.setText(f"{abs(power_w):.2f} W\nDischarging")
            self.lbl_big_power.setStyleSheet("background-color: #e74c3c; color: white; font-size: 28px; font-weight: bold; border-radius: 10px; padding: 15px;")
        else:
            self.lbl_big_power.setText(f"0.00 W\nIdle")
            self.lbl_big_power.setStyleSheet("background-color: #34495e; color: white; font-size: 28px; font-weight: bold; border-radius: 10px; padding: 15px;")
            
        self.lbl_big_wh.setText(f"{data.get('session_used_wh', 0):.4f} Wh\nUsed (Session)")
        self.lbl_big_time.setText(f"{data.get('time_rem', '--').replace(' in ', ' ')}\nStatus")
        
        self.lbl_ups_pct.setText(f"{data.get('bat_pct', 0)}%")
        if data.get('bat_pct', 0) <= 20: self.lbl_ups_pct.setStyleSheet("color: #e74c3c; font-size: 40px; font-weight: bold;")
        else: self.lbl_ups_pct.setStyleSheet("color: #2ecc71; font-size: 40px; font-weight: bold;")
        
        self.lbl_ups_bat_v.setText(f"{data.get('bat_v', 0)} mV")
        self.lbl_ups_bat_c.setText(f"{data.get('bat_c', 0)} mA")
        self.lbl_ups_cap.setText(f"{data.get('bat_cap', 0)} mAh")
        
        self.lbl_ups_vbus_v.setText(f"{data.get('vbus_v', 0)} mV")
        self.lbl_ups_vbus_p.setText(f"{data.get('vbus_p', 0)} mW")
        
        self.lbl_c1.setText(str(data.get("V1", 0)))
        self.lbl_c2.setText(str(data.get("V2", 0)))
        self.lbl_c3.setText(str(data.get("V3", 0)))
        self.lbl_c4.setText(str(data.get("V4", 0)))

    def update_alert(self, alert_type, data):
        """Update the collision alert display (FCW, AEB, or SAFE)"""
        distance = data.get('distance', 0)
        speed = data.get('speed', 0)
        
        self.lbl_alert_distance.setText(f"Distance: {distance} m")
        self.lbl_alert_speed.setText(f"Speed: {speed} km/h")
        
        # Cancel any existing timeout timer
        if self.alert_timeout_timer is not None:
            self.alert_timeout_timer.cancel()
            self.alert_timeout_timer = None
        
        if alert_type == "AEB":
            self.lbl_current_alert.setText("🚨 AEB")
            self.lbl_current_alert.setStyleSheet("background-color: #c0392b; color: white; font-size: 12pt; font-weight: bold; border-radius: 5px; padding: 10px;")
            self.signals.play_audio.emit("AEB")
            # Set timeout to return to SAFE after 8 seconds
            self.alert_timeout_timer = threading.Timer(8.0, self._reset_alert_to_safe)
            self.alert_timeout_timer.start()
        elif alert_type == "FCW":
            self.lbl_current_alert.setText("⚠️ FCW")
            self.lbl_current_alert.setStyleSheet("background-color: #f39c12; color: white; font-size: 12pt; font-weight: bold; border-radius: 5px; padding: 10px;")
            self.signals.play_audio.emit("FCW")
            # Set timeout to return to SAFE after 8 seconds
            self.alert_timeout_timer = threading.Timer(8.0, self._reset_alert_to_safe)
            self.alert_timeout_timer.start()
        else:  # SAFE
            self.lbl_current_alert.setText("✅ SAFE")
            self.lbl_current_alert.setStyleSheet("background-color: #27ae60; color: white; font-size: 12pt; font-weight: bold; border-radius: 5px; padding: 10px;")
            self.signals.play_audio.emit("SAFE")

    def _reset_alert_to_safe(self):
        """Reset alert display to SAFE after timeout"""
        self.lbl_current_alert.setText("✅ SAFE")
        self.lbl_current_alert.setStyleSheet("background-color: #27ae60; color: white; font-size: 12pt; font-weight: bold; border-radius: 5px; padding: 10px;")
        self.lbl_alert_distance.setText("Distance: -- m")
        self.lbl_alert_speed.setText("Speed: -- km/h")
        self.alert_timeout_timer = None

    def closeEvent(self, event):
        # Cancel alert timeout timer if active
        if self.alert_timeout_timer is not None:
            self.alert_timeout_timer.cancel()
            self.alert_timeout_timer = None
        
        if os.path.exists("/dev/shm/aras_gps_data.json"): os.remove("/dev/shm/aras_gps_data.json")
        if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
        if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)
        # Ensure the tracking flag is deleted on exit
        if os.path.exists(self.track_record_flag): os.remove(self.track_record_flag)
        
        for m in self.modules: m.stop()
        event.accept()

if __name__ == "__main__":
    sync_system_time()
    app = QApplication(sys.argv)
    project_root = os.path.dirname(os.path.abspath(__file__))
    window = LauncherMainWindow(build_modules(project_root), project_root)
    window.showFullScreen()
    sys.exit(app.exec_())