import os
import sys
import threading
import subprocess
import time
import base64
import json
import math
import re
from dataclasses import dataclass, field
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QPushButton, QWidget, 
    QStackedWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, 
    QGridLayout, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QEvent, QTimer
from PyQt5.QtGui import QFont, QPixmap, QImage, QPainter, QColor

# --- UI CONSTANTS FOR 4.3" PORTRAIT ---
SCREEN_W = 480
SCREEN_H = 800
BG_DARK = "#0f172a"
NAV_HEIGHT = 80


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
        self.marker_lat, self.marker_lon = 2.94941, 101.87505
        self.view_lat, self.view_lon = 2.94941, 101.87505
        self.auto_follow = True

    def updatePos(self, lat, lon):
        if lat != 0:
            self.marker_lat, self.marker_lon = lat, lon
            if self.auto_follow: 
                self.view_lat, self.view_lon = lat, lon
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e272e"))
        painter.setPen(Qt.white)
        painter.drawText(self.rect(), Qt.AlignCenter, "Map Loading...")
        painter.setBrush(Qt.red)
        painter.drawEllipse(int(self.width()/2)-8, int(self.height()/2)-8, 16, 16)        


class LogSignal(QObject):
    new_log = pyqtSignal(str, str)
    new_frame = pyqtSignal(bytes)
    new_detection = pyqtSignal(str)
    new_gps = pyqtSignal(dict)
    new_ups = pyqtSignal(dict)
    new_alert = pyqtSignal(str, dict)
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
        if self.config.startup_delay > 0: 
            time.sleep(self.config.startup_delay)
        script_path = os.path.join(self.project_root, self.config.script_relative_path)
        cwd = os.path.join(self.project_root, self.config.cwd_relative) if self.config.cwd_relative else self.project_root
        
        if self.config.python_executable:
            cmd = self.config.python_executable.split()
            cmd.append("-u") 
        else:
            cmd = ["python3", "-u"]
            
        cmd.append(script_path)

        self.process = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, bufsize=1, env=os.environ.copy(), close_fds=True 
        )

        for line in iter(self.process.stdout.readline, ''):
            if not line: break
            line_str = line.strip()
            
            if "__AUDIO_TRIGGER__:" in line_str:
                alert_type = line_str.split("__AUDIO_TRIGGER__:")[1].strip()
                self.log_signal.play_audio.emit(alert_type)
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


class ARASMasterPortrait(QMainWindow):
    def __init__(self, modules: List[ModuleRunner], project_root: str):
        super().__init__()
        self.modules = modules
        self.project_root = project_root
        self.signals = LogSignal()
        
        self.aeb_audio_enabled = True
        self.fcw_audio_enabled = True
        self.is_cam_recording = False
        self.is_tracking = False
        self.is_ups_recording = False
        
        self.cam_record_flag = os.path.join(self.project_root, "1_TrafficSign", ".record_flag")
        self.ups_record_flag = os.path.join(self.project_root, "4_UPS_HAT_E", ".ups_record_flag")
        self.track_record_flag = "/dev/shm/aras_tracking.flag"
        
        if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
        if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)
        if os.path.exists(self.track_record_flag): os.remove(self.track_record_flag)
        
        subprocess.run(["sudo", "pkill", "-9", "-f", "integrated.py"], stderr=subprocess.DEVNULL)
        
        self.aeb_path = os.path.join(self.project_root, "Asset", "aeb.wav")
        self.fcw_path = os.path.join(self.project_root, "Asset", "fcw.wav")
        self.audio_proc_aeb = None
        self.audio_proc_fcw = None
        self.alert_timeout_timer = None
        
        self.init_ui()
        self.setup_connections()
        
        for m in self.modules:
            m.log_signal = self.signals
            m.start()

    def init_ui(self):
        self.setFixedSize(SCREEN_W, SCREEN_H)
        self.setStyleSheet(f"background-color: {BG_DARK};")
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.layout = QVBoxLayout(main_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 1. Global Alert Banner
        self.alert_bar = QLabel("✅ SYSTEM SAFE")
        self.alert_bar.setFixedHeight(65)
        self.alert_bar.setAlignment(Qt.AlignCenter)
        self.alert_bar.setStyleSheet("background: #10b981; color: white; font-size: 24px; font-weight: bold;")
        self.layout.addWidget(self.alert_bar)

        # 2. Stacked Pages
        self.stack = QStackedWidget()
        self.stack.addWidget(self.init_vision_page())
        self.stack.addWidget(self.init_radar_page())
        self.stack.addWidget(self.init_gps_page())
        self.stack.addWidget(self.init_ups_page())
        self.stack.addWidget(self.init_audio_page())
        self.layout.addWidget(self.stack)

        # 3. Bottom Navigation
        nav_frame = QFrame()
        nav_frame.setFixedHeight(NAV_HEIGHT)
        nav_frame.setStyleSheet("background: #1e293b; border-top: 2px solid #334155;")
        nav_layout = QHBoxLayout(nav_frame)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        
        self.nav_btns = []
        tabs = [("📷", "VIS"), ("📡", "RAD"), ("📍", "MAP"), ("🔋", "PWR"), ("🔊", "AUD")]
        for i, (icon, txt) in enumerate(tabs):
            btn = QPushButton(f"{icon}\n{txt}")
            btn.setCheckable(True)
            btn.setFixedHeight(NAV_HEIGHT)
            btn.setStyleSheet("QPushButton{background:transparent; color:#94a3b8; font-size: 14px; font-weight:bold; border:none;} QPushButton:checked{color:#38bdf8; background:#334155;}")
            btn.clicked.connect(lambda _, idx=i: self.set_tab(idx))
            nav_layout.addWidget(btn)
            self.nav_btns.append(btn)
        
        self.nav_btns[1].setChecked(True)
        self.stack.setCurrentIndex(1)
        self.layout.addWidget(nav_frame)

    def set_tab(self, idx):
        for i, b in enumerate(self.nav_btns):
            b.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)

    # --- RADAR PAGE ---
    def init_radar_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        for name in ["Front", "Back"]:
            group = QGroupBox(f"LD24{name[-2:]}_{name} Terminal")
            group.setStyleSheet("QGroupBox { color: white; font-weight: bold; font-size: 14px; }")
            l = QVBoxLayout(group)
            
            recent = QLabel(f"{name.upper()}: No Target")
            color = "#38bdf8" if name == "Front" else "#f472b6"
            recent.setStyleSheet(f"background: #1e293b; color: {color}; font-weight: bold; font-size: 16px; padding: 10px; border-radius: 5px;")
            setattr(self, f"recent_{name.lower()}", recent)
            
            term = QTextEdit()
            term.setReadOnly(True)
            term.setStyleSheet("background: black; color: #00ff00; font-family: monospace; font-size: 12px; border: none; padding: 5px;")
            setattr(self, f"term_{name.lower()}", term)
            
            l.addWidget(recent)
            l.addWidget(term)
            layout.addWidget(group, stretch=1)
            
        return page

    # --- VISION PAGE ---
    def init_vision_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # Maximize video feed size
        self.lbl_video = QLabel("Waiting for camera...")
        self.lbl_video.setAlignment(Qt.AlignCenter)
        self.lbl_video.setStyleSheet("background: black; color: white; font-size: 16px; border-radius: 10px;")
        self.lbl_video.setMinimumHeight(350)
        self.lbl_video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.lbl_video, stretch=3)
        
        # Detection Overlays Grid
        info_overlay = QHBoxLayout()
        info_overlay.setSpacing(10)
        
        self.lbl_speed_limit = QLabel("--")
        self.lbl_speed_limit.setFixedSize(100, 100)
        self.lbl_speed_limit.setStyleSheet("background: white; color: black; border: 6px solid #e74c3c; border-radius: 50px; font-size: 36px; font-weight: bold;")
        self.lbl_speed_limit.setAlignment(Qt.AlignCenter)
        info_overlay.addWidget(self.lbl_speed_limit)
        
        self.lbl_road_hazard = QLabel("ROAD\nCLEAR")
        self.lbl_road_hazard.setStyleSheet("background: #27ae60; color: white; border-radius: 10px; font-size: 20px; font-weight: bold;")
        self.lbl_road_hazard.setAlignment(Qt.AlignCenter)
        info_overlay.addWidget(self.lbl_road_hazard, stretch=1)

        layout.addLayout(info_overlay, stretch=1)

        self.btn_cam_record = QPushButton("⏺️ REC VIDEO")
        self.btn_cam_record.setStyleSheet("background-color: #475569; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
        self.btn_cam_record.clicked.connect(self.toggle_cam_recording)
        layout.addWidget(self.btn_cam_record)
        
        return page

    # --- GPS PAGE ---
    def init_gps_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        
        self.lbl_gps_status = QLabel("STATUS: INITIALIZING")
        self.lbl_gps_status.setStyleSheet("color: #f1c40f; font-size: 14px; font-weight: bold;")
        self.lbl_gps_status.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.lbl_gps_status)

        self.lbl_gps_mod_speed = QLabel("0.0\nkm/h")
        self.lbl_gps_mod_speed.setStyleSheet("color: #38bdf8; font-size: 50px; font-weight: bold;")
        self.lbl_gps_mod_speed.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.lbl_gps_mod_speed)

        self.lbl_gps_odo = QLabel("Distance: 0.0 m")
        self.lbl_gps_odo.setStyleSheet("color: #ecf0f1; font-size: 16px; font-weight: bold;")
        self.lbl_gps_odo.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.lbl_gps_odo)

        gps_ctrl = QHBoxLayout()
        self.btn_track = QPushButton("⏺️ Start Tracking")
        self.btn_track.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px; border-radius: 5px; font-size: 14px;")
        self.btn_track.clicked.connect(self.toggle_tracking)
        
        btn_reset = QPushButton("🎯 Follow Me")
        btn_reset.setStyleSheet("background-color: #7f8c8d; color: white; padding: 10px; border-radius: 5px; font-size: 14px;")
        btn_reset.clicked.connect(lambda: setattr(self.map_view, 'auto_follow', True))
        
        gps_ctrl.addWidget(self.btn_track)
        gps_ctrl.addWidget(btn_reset)
        info_layout.addLayout(gps_ctrl)

        layout.addLayout(info_layout)
        self.map_view = NativeMapWidget(self.project_root)
        layout.addWidget(self.map_view, stretch=1)
        return page

    # --- UPS PAGE ---
    def init_ups_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Top Big Stats
        top_layout = QHBoxLayout()
        self.lbl_big_power = QLabel("0.0W")
        self.lbl_big_power.setAlignment(Qt.AlignCenter)
        self.lbl_big_power.setStyleSheet("background-color: #1e293b; color: #f1c40f; font-size: 36px; font-weight: bold; border-radius: 10px;")
        
        self.lbl_ups_pct = QLabel("0%")
        self.lbl_ups_pct.setAlignment(Qt.AlignCenter)
        self.lbl_ups_pct.setStyleSheet("background-color: #1e293b; color: #2ecc71; font-size: 36px; font-weight: bold; border-radius: 10px;")
        
        top_layout.addWidget(self.lbl_big_power, stretch=1)
        top_layout.addWidget(self.lbl_ups_pct, stretch=1)
        layout.addLayout(top_layout, stretch=1)

        # Secondary Stats Grid
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        self.lbl_big_wh = QLabel("0.0Wh")
        self.lbl_ups_bat_v = QLabel("0mV")
        self.lbl_ups_bat_c = QLabel("0mA")
        self.lbl_ups_cap = QLabel("0mAh")
        
        for idx, (title, lbl) in enumerate([("Session Used:", self.lbl_big_wh), ("Voltage:", self.lbl_ups_bat_v), 
                                            ("Current:", self.lbl_ups_bat_c), ("Capacity:", self.lbl_ups_cap)]):
            t_lbl = QLabel(title)
            t_lbl.setStyleSheet("color: #94a3b8; font-size: 16px;")
            lbl.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
            grid_layout.addWidget(t_lbl, idx, 0)
            grid_layout.addWidget(lbl, idx, 1)
            
        layout.addLayout(grid_layout, stretch=1)

        # Cells
        cells_layout = QHBoxLayout()
        self.lbl_c1 = QLabel("0")
        self.lbl_c2 = QLabel("0")
        self.lbl_c3 = QLabel("0")
        self.lbl_c4 = QLabel("0")
        for c in [self.lbl_c1, self.lbl_c2, self.lbl_c3, self.lbl_c4]:
            c.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
            c.setAlignment(Qt.AlignCenter)
            cells_layout.addWidget(c)
        layout.addLayout(cells_layout, stretch=1)

        self.btn_ups_record = QPushButton("⏺️ RECORD POWER")
        self.btn_ups_record.setStyleSheet("background-color: #8e44ad; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
        self.btn_ups_record.clicked.connect(self.toggle_ups_recording)
        layout.addWidget(self.btn_ups_record)
        
        return page

    # --- AUDIO PAGE ---
    def init_audio_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        title = QLabel("Audio Alerts")
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.btn_aeb_toggle = QPushButton("🚨 AEB AUDIO: ON")
        self.btn_aeb_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; padding: 25px; border-radius: 10px;")
        self.btn_aeb_toggle.clicked.connect(self.toggle_aeb)
        layout.addWidget(self.btn_aeb_toggle)

        self.btn_fcw_toggle = QPushButton("⚠️ FCW AUDIO: ON")
        self.btn_fcw_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; padding: 25px; border-radius: 10px;")
        self.btn_fcw_toggle.clicked.connect(self.toggle_fcw)
        layout.addWidget(self.btn_fcw_toggle)

        layout.addStretch()
        return page

    # --- CONNECTIONS & SIGNAL HANDLERS ---
    def setup_connections(self):
        self.signals.new_frame.connect(self.update_video)
        self.signals.new_log.connect(self.update_terminals)
        self.signals.new_detection.connect(self.update_detections)
        self.signals.new_gps.connect(self.update_gps)
        self.signals.new_ups.connect(self.update_ups)
        self.signals.new_alert.connect(self.update_alert)
        self.signals.play_audio.connect(self.handle_audio_trigger)

    def handle_audio_trigger(self, trigger_type):
        aeb_busy = self.audio_proc_aeb is not None and self.audio_proc_aeb.poll() is None
        fcw_busy = self.audio_proc_fcw is not None and self.audio_proc_fcw.poll() is None

        if trigger_type == "AEB" and self.aeb_audio_enabled:
            if fcw_busy: 
                self.audio_proc_fcw.terminate()
            if not aeb_busy and os.path.exists(self.aeb_path):
                self.audio_proc_aeb = subprocess.Popen(['aplay', '-q', self.aeb_path], stderr=subprocess.DEVNULL)
        elif trigger_type == "FCW" and self.fcw_audio_enabled:
            if not aeb_busy and not fcw_busy and os.path.exists(self.fcw_path):
                self.audio_proc_fcw = subprocess.Popen(['aplay', '-q', self.fcw_path], stderr=subprocess.DEVNULL)

    def update_video(self, img_bytes):
        image = QImage.fromData(img_bytes)
        if not image.isNull():
            self.lbl_video.setPixmap(QPixmap.fromImage(image).scaled(
                self.lbl_video.width(), self.lbl_video.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def update_terminals(self, name, text):
        if name == "LD2451_Front":
            self.term_front.append(text)
            self.term_front.verticalScrollBar().setValue(self.term_front.verticalScrollBar().maximum())
            if "Target" in text:
                self.recent_front.setText(text.strip())
                self._parse_radar_alert(text)
        elif name == "LD2417_Back":
            self.term_back.append(text)
            self.term_back.verticalScrollBar().setValue(self.term_back.verticalScrollBar().maximum())
            if "Target" in text:
                self.recent_back.setText(text.strip())

    def _parse_radar_alert(self, log_text):
        try:
            match = re.search(r'Distance=(\d+)', log_text)
            speed_match = re.search(r'Speed=(\d+)', log_text)
            
            if match and speed_match:
                distance = int(match.group(1))
                speed = int(speed_match.group(1))
                
                AEB_DIST_M = 3.0
                FCW_DIST_M = 8.0
                FAST_SPEED_KMH = 5.0
                MID_SPEED_KMH = 4.0
                
                alert_type = "SAFE"
                if distance <= AEB_DIST_M and speed >= FAST_SPEED_KMH:
                    alert_type = "AEB"
                elif distance <= FCW_DIST_M or speed >= MID_SPEED_KMH:
                    alert_type = "FCW"
                
                self.signals.new_alert.emit(alert_type, {'distance': distance, 'speed': speed})
        except Exception:
            pass

    def update_detections(self, detection_string):
        """Processes sign and hazard logic into big UI icons for the Vision Tab"""
        signs = detection_string.split(",")
        hazards = []
        for s in signs:
            if s.startswith("SL_"): 
                self.lbl_speed_limit.setText(s.replace("SL_", ""))
            elif s in ["Pothole", "Manhole", "Bump sign", "Bumps"]:
                hazards.append(s.upper().replace(" SIGN", ""))
            elif s in ["Pedestrian", "Two_Wheeler", "Motorcycles only"]:
                hazards.append("VRU ALERT")
            elif s in ["Stop", "red-traffic-lights"]:
                hazards.append("STOP")
        
        if hazards:
            self.lbl_road_hazard.setText("\n".join(set(hazards)))
            self.lbl_road_hazard.setStyleSheet("background: #e74c3c; color: white; border-radius: 10px; font-size: 20px; font-weight: bold;")
        else:
            self.lbl_road_hazard.setText("ROAD\nCLEAR")
            self.lbl_road_hazard.setStyleSheet("background: #27ae60; color: white; border-radius: 10px; font-size: 20px; font-weight: bold;")

    def update_gps(self, data):
        self.lbl_gps_status.setText(f"STATUS: {data.get('status', 'SEARCHING')} | S:{data.get('sats', 0)}")
        self.lbl_gps_mod_speed.setText(f"{data.get('speed', 0.0):.1f}\nkm/h")
        dist = data.get('odo', 0)
        self.lbl_gps_odo.setText(f"Distance: {dist:.1f}m" if dist < 1000 else f"Distance: {dist/1000.0:.2f}km")
        self.map_view.updatePos(data.get('lat', 0), data.get('lon', 0))

        try:
            with open("/dev/shm/aras_gps_data.json", "w") as f:
                json.dump({
                    "speed": data.get('speed', 0.0),
                    "lat": data.get('lat', 0.0),
                    "lon": data.get('lon', 0.0),
                    "status": data.get('status', 'SEARCHING')
                }, f)
        except Exception:
            pass

    def update_ups(self, data):
        power_w = data.get("bat_power_w", 0)
        if power_w > 0:
            self.lbl_big_power.setText(f"+{power_w:.1f}W\nCharge")
            self.lbl_big_power.setStyleSheet("background-color: #1e293b; color: #2ecc71; font-size: 28px; font-weight: bold; border-radius: 10px;")
        elif power_w < 0:
            self.lbl_big_power.setText(f"{abs(power_w):.1f}W\nDischg")
            self.lbl_big_power.setStyleSheet("background-color: #1e293b; color: #e74c3c; font-size: 28px; font-weight: bold; border-radius: 10px;")
        else:
            self.lbl_big_power.setText("0.0W\nIdle")
            self.lbl_big_power.setStyleSheet("background-color: #1e293b; color: #f1c40f; font-size: 28px; font-weight: bold; border-radius: 10px;")
            
        self.lbl_big_wh.setText(f"{data.get('session_used_wh', 0):.2f}Wh")
        
        pct = data.get('bat_pct', 0)
        self.lbl_ups_pct.setText(f"{pct}%")
        if pct <= 20: 
            self.lbl_ups_pct.setStyleSheet("background-color: #1e293b; color: #e74c3c; font-size: 40px; font-weight: bold; border-radius: 10px;")
        else: 
            self.lbl_ups_pct.setStyleSheet("background-color: #1e293b; color: #2ecc71; font-size: 40px; font-weight: bold; border-radius: 10px;")
        
        self.lbl_ups_bat_v.setText(f"{data.get('bat_v', 0)}mV")
        self.lbl_ups_bat_c.setText(f"{data.get('bat_c', 0)}mA")
        self.lbl_ups_cap.setText(f"{data.get('bat_cap', 0)}mAh")
        
        self.lbl_c1.setText(str(data.get("V1", 0)))
        self.lbl_c2.setText(str(data.get("V2", 0)))
        self.lbl_c3.setText(str(data.get("V3", 0)))
        self.lbl_c4.setText(str(data.get("V4", 0)))

    def update_alert(self, alert_type, data):
        if self.alert_timeout_timer is not None:
            self.alert_timeout_timer.cancel()
            self.alert_timeout_timer = None
        
        if alert_type == "AEB":
            self.alert_bar.setText("🚨 AEB ACTIVATED")
            self.alert_bar.setStyleSheet("background: #dc2626; color: white; font-size: 24px; font-weight: bold;")
            self.signals.play_audio.emit("AEB")
            self.alert_timeout_timer = threading.Timer(8.0, self._reset_alert_to_safe)
            self.alert_timeout_timer.start()
        elif alert_type == "FCW":
            self.alert_bar.setText("⚠️ FCW WARNING")
            self.alert_bar.setStyleSheet("background: #ea580c; color: white; font-size: 24px; font-weight: bold;")
            self.signals.play_audio.emit("FCW")
            self.alert_timeout_timer = threading.Timer(8.0, self._reset_alert_to_safe)
            self.alert_timeout_timer.start()
        else:
            self.alert_bar.setText("✅ SYSTEM SAFE")
            self.alert_bar.setStyleSheet("background: #10b981; color: white; font-size: 24px; font-weight: bold;")
            self.signals.play_audio.emit("SAFE")

    def _reset_alert_to_safe(self):
        self.alert_bar.setText("✅ SYSTEM SAFE")
        self.alert_bar.setStyleSheet("background: #10b981; color: white; font-size: 24px; font-weight: bold;")
        self.alert_timeout_timer = None

    # --- TOGGLES ---
    def toggle_cam_recording(self):
        self.is_cam_recording = not self.is_cam_recording
        if self.is_cam_recording:
            self.btn_cam_record.setText("⏹️ STOP VIDEO")
            self.btn_cam_record.setStyleSheet("background-color: #e74c3c; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
            open(self.cam_record_flag, 'a').close()
        else:
            self.btn_cam_record.setText("⏺️ REC VIDEO")
            self.btn_cam_record.setStyleSheet("background-color: #475569; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
            if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
    
    def toggle_tracking(self):
        self.is_tracking = not self.is_tracking
        if self.is_tracking:
            self.btn_track.setText("⏹️ Stop Track")
            self.btn_track.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px; border-radius: 5px; font-size: 14px;")
            open(self.track_record_flag, 'a').close()
        else:
            self.btn_track.setText("⏺️ Start Track")
            self.btn_track.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px; border-radius: 5px; font-size: 14px;")
            if os.path.exists(self.track_record_flag): os.remove(self.track_record_flag)

    def toggle_ups_recording(self):
        self.is_ups_recording = not self.is_ups_recording
        if self.is_ups_recording:
            self.btn_ups_record.setText("⏹️ STOP POWER")
            self.btn_ups_record.setStyleSheet("background-color: #e74c3c; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
            open(self.ups_record_flag, 'a').close()
        else:
            self.btn_ups_record.setText("⏺️ RECORD POWER")
            self.btn_ups_record.setStyleSheet("background-color: #8e44ad; color: white; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 5px;")
            if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)

    def toggle_aeb(self):
        self.aeb_audio_enabled = not self.aeb_audio_enabled
        if self.aeb_audio_enabled:
            self.btn_aeb_toggle.setText("🚨 AEB AUDIO: ON")
            self.btn_aeb_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; padding: 25px; border-radius: 10px;")
        else:
            self.btn_aeb_toggle.setText("🔇 AEB AUDIO: OFF")
            self.btn_aeb_toggle.setStyleSheet("background-color: #e74c3c; color: white; font-size: 18px; font-weight: bold; padding: 25px; border-radius: 10px;")

    def toggle_fcw(self):
        self.fcw_audio_enabled = not self.fcw_audio_enabled
        if self.fcw_audio_enabled:
            self.btn_fcw_toggle.setText("⚠️ FCW AUDIO: ON")
            self.btn_fcw_toggle.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; padding: 25px; border-radius: 10px;")
        else:
            self.btn_fcw_toggle.setText("🔇 FCW AUDIO: OFF")
            self.btn_fcw_toggle.setStyleSheet("background-color: #e74c3c; color: white; font-size: 18px; font-weight: bold; padding: 25px; border-radius: 10px;")

    def closeEvent(self, event):
        if self.alert_timeout_timer is not None:
            self.alert_timeout_timer.cancel()
        
        if os.path.exists("/dev/shm/aras_gps_data.json"): os.remove("/dev/shm/aras_gps_data.json")
        if os.path.exists(self.cam_record_flag): os.remove(self.cam_record_flag)
        if os.path.exists(self.ups_record_flag): os.remove(self.ups_record_flag)
        if os.path.exists(self.track_record_flag): os.remove(self.track_record_flag)
        
        for m in self.modules: m.stop()
        event.accept()

if __name__ == "__main__":
    sync_system_time()
    app = QApplication(sys.argv)
    project_root = os.path.dirname(os.path.abspath(__file__))
    window = ARASMasterPortrait(build_modules(project_root), project_root)
    window.showFullScreen()
    sys.exit(app.exec_())