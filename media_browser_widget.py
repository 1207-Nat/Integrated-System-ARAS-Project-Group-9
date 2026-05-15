# media_browser_widget.py
import os
import subprocess
import threading
import cv2
import json
import shutil
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, 
                             QTreeView, QPushButton, QSlider, QMessageBox, 
                             QAbstractItemView, QHeaderView, QFileSystemModel, QSizePolicy,
                             QPinchGesture, QStyle) # Added QStyle
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QPoint, QEvent, QPointF # Added QPointF
from PyQt5.QtGui import QPixmap, QImage, QFont, QPainter
import time # Ensure time is imported for our throttle

# --- CUSTOM RESPONSIVE TOUCH SLIDER ---
class JumpSlider(QSlider):
    def mousePressEvent(self, event):
        # Let Qt process the click first so it knows the mouse is down
        super().mousePressEvent(event)
        
        if event.button() == Qt.LeftButton:
            # Instantly teleport the slider handle to the exact pixel you touched
            val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), event.x(), self.width())
            self.setValue(val)
            self.sliderMoved.emit(val)
        
# --- CUSTOM CLICKABLE LABEL FOR VIDEO TAPPING, ZOOMING & SWIPING ---
class ClickableLabel(QLabel):
    clicked = pyqtSignal()
    double_clicked = pyqtSignal()
    swiped_left = pyqtSignal()   
    swiped_right = pyqtSignal()  

    def __init__(self, text=""):
        super().__init__(text)
        self._original_pixmap = None 
        
        # --- ZOOM & PAN VARIABLES ---
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0.0, 0.0) # Converted to Float for precise zooming math
        self.last_mouse_pos = None
        self.swipe_start_pos = None 
        self.is_dragging = False
        
        self.grabGesture(Qt.PinchGesture)

    def set_raw_image(self, pixmap):
        self._original_pixmap = pixmap
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0.0, 0.0)
        super().setPixmap(QPixmap()) 
        self.update() 

    def clear_image(self):
        self._original_pixmap = None
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0.0, 0.0)
        self.update()

    def event(self, event):
        if event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        pinch = event.gesture(Qt.PinchGesture)
        if pinch:
            if pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
                scale_change = pinch.scaleFactor()
                new_zoom = self.zoom_factor * scale_change
                new_zoom = max(1.0, min(new_zoom, 10.0)) 
                
                # Actual applied scale (handles minimum/maximum clamping correctly)
                actual_scale = new_zoom / self.zoom_factor
                self.zoom_factor = new_zoom
                
                if self.zoom_factor == 1.0:
                    self.pan_offset = QPointF(0.0, 0.0)
                else:
                    # MATH LOGIC: Offset the pan based on the exact finger location!
                    local_pinch_center = self.mapFromGlobal(pinch.centerPoint().toPoint())
                    dx = local_pinch_center.x() - self.width() / 2.0
                    dy = local_pinch_center.y() - self.height() / 2.0
                    
                    new_x = self.pan_offset.x() * actual_scale + dx * (1.0 - actual_scale)
                    new_y = self.pan_offset.y() * actual_scale + dy * (1.0 - actual_scale)
                    self.pan_offset = QPointF(new_x, new_y)

                self.update()
            return True
        return False

    def paintEvent(self, event):
        if self._original_pixmap and not self._original_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            
            base_size = self._original_pixmap.size()
            base_size.scale(self.size(), Qt.KeepAspectRatio)
            
            scaled_w = base_size.width() * self.zoom_factor
            scaled_h = base_size.height() * self.zoom_factor
            
            draw_x = (self.width() - scaled_w) / 2 + self.pan_offset.x()
            draw_y = (self.height() - scaled_h) / 2 + self.pan_offset.y()
            
            painter.drawPixmap(int(draw_x), int(draw_y), int(scaled_w), int(scaled_h), self._original_pixmap)
        else:
            super().paintEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.pos()
            self.swipe_start_pos = event.pos() 
            self.is_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos and self._original_pixmap and self.zoom_factor > 1.0:
            delta = event.pos() - self.last_mouse_pos
            self.pan_offset += QPointF(float(delta.x()), float(delta.y()))
            self.last_mouse_pos = event.pos()
            self.is_dragging = True
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.swipe_start_pos:
                delta_x = event.pos().x() - self.swipe_start_pos.x()
                delta_y = event.pos().y() - self.swipe_start_pos.y()
                
                if self.zoom_factor == 1.0:
                    if delta_x < -80 and abs(delta_y) < 150: 
                        self.swiped_left.emit()  
                    elif delta_x > 80 and abs(delta_y) < 150: 
                        self.swiped_right.emit() 
                    elif abs(delta_x) < 15 and abs(delta_y) < 15: 
                        self.clicked.emit()      
                else:
                    if not self.is_dragging:
                        self.clicked.emit()

            self.last_mouse_pos = None
            self.swipe_start_pos = None
            
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

class CheckableFileSystemModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked_files = {} 

    def flags(self, index):
        f = super().flags(index)
        if index.column() == 0:
            f |= Qt.ItemIsUserCheckable
        return f

    def data(self, index, role):
        if role == Qt.CheckStateRole and index.column() == 0:
            filepath = self.filePath(index)
            return self._checked_files.get(filepath, Qt.Unchecked)
        return super().data(index, role)

    def setData(self, index, value, role):
        if role == Qt.CheckStateRole and index.column() == 0:
            filepath = self.filePath(index)
            self._checked_files[filepath] = value
            self.dataChanged.emit(index, index)
            return True
        return super().setData(index, value, role)

    def toggleCheckState(self, index):
        if not index.isValid() or index.column() != 0: return
        filepath = self.filePath(index)
        current_state = self._checked_files.get(filepath, Qt.Unchecked)
        new_state = Qt.Checked if current_state == Qt.Unchecked else Qt.Unchecked
        self.setData(index, new_state, Qt.CheckStateRole)

    def getCheckedFiles(self):
        return [fp for fp, state in self._checked_files.items() if state == Qt.Checked]

class MediaBrowserWidget(QWidget):
    def __init__(self, paths, signals, is_small_screen, trash_dir, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.signals = signals
        self.is_small_screen = is_small_screen
        self.TRASH_DIR = trash_dir
        
        self.media_cap = None
        self.is_playing = False
        self.qrcp_process = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            MediaBrowserWidget { background-color: #121212; color: white; }
            QLabel { color: white; }
        """)
        
        layout = QHBoxLayout(self) 
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.video_timer = QTimer()
        self.video_timer.timeout.connect(self._update_video_frame)

        # 1. Left Nav
        nav = QVBoxLayout()
        self.list_folders = QListWidget()
        self.list_folders.addItems(self.paths.keys())
        
        self.list_folders.setStyleSheet("""
            QListWidget { background: #1e272e; border: 1px solid #34495e; font-size: 11px; font-weight: bold; color: white; border-radius: 4px;} 
            QListWidget::item { height: 35px; padding-left: 5px; color: white; } 
            QListWidget::item:selected { background: #3498db; color: white; }
        """)
        self.list_folders.setFixedWidth(120)
        self.list_folders.currentRowChanged.connect(self._refresh_file_list)
        nav.addWidget(QLabel("📁 Category", styleSheet="font-size: 13px; font-weight: bold; color: #3498db;"))
        nav.addWidget(self.list_folders)

        # 2. Middle: File List
        mid = QVBoxLayout()
        self.btn_select_all = QPushButton("✅ Select All")
        self.btn_select_all.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; padding: 6px; border-radius: 4px; font-size: 11px;")
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        
        self.file_model = CheckableFileSystemModel()
        self.file_model.setRootPath("")
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.file_model)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.sortByColumn(0, Qt.DescendingOrder)
        self.tree_view.setSelectionMode(QAbstractItemView.SingleSelection)
        
        self.tree_view.setStyleSheet("""
            QTreeView { font-size: 11px; background: #1e272e; border: 1px solid #34495e; color: white; border-radius: 4px;} 
            QTreeView::item { height: 30px; color: white; }
            QTreeView::item:selected { background: #3498db; color: white; }
        """)
        
        self.tree_view.header().setStyleSheet("""
            QHeaderView::section {
                background-color: #2c3e50; color: white; font-weight: bold;
                padding: 4px; border: none; border-right: 1px solid #1e272e; font-size: 11px;
            }
        """)
        
        self.tree_view.selectionModel().selectionChanged.connect(self._preview_selected_item)
        self.tree_view.clicked.connect(self._tree_item_clicked_to_toggle_checkbox)
        
        mid.addWidget(QLabel("📄 Files & Folders", styleSheet="font-size: 13px; font-weight: bold; color: #3498db;"))
        mid.addWidget(self.btn_select_all)
        mid.addWidget(self.tree_view)

        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton("🗑️ Trash")
        self.btn_delete.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; height: 30px; border-radius: 4px; font-size: 11px;")
        self.btn_delete.clicked.connect(self._handle_delete_action)
        self.btn_restore = QPushButton("🔄 Restore")
        self.btn_restore.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; height: 30px; border-radius: 4px; font-size: 11px;")
        self.btn_restore.clicked.connect(self._handle_restore_action)
        self.btn_restore.hide()
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_restore)
        mid.addLayout(btn_layout)

        # 3. Right: Playback & QR
        self.rig = QVBoxLayout()
        
        # --- IMPLEMENT CLICKABLE LABEL ---
        self.lbl_preview = ClickableLabel("Select media")
        self.lbl_preview.clicked.connect(self._toggle_playback)
        self.lbl_preview.double_clicked.connect(self._toggle_fullscreen_preview) 
        
        # --- CONNECT NEW SWIPE GESTURES ---
        self.lbl_preview.swiped_left.connect(self._handle_swipe_left)
        self.lbl_preview.swiped_right.connect(self._handle_swipe_right)
        
        self.is_preview_fullscreen = False 
        self.lbl_preview.setMinimumSize(240, 160)
        
        self.lbl_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setStyleSheet("border: 2px solid #34495e; background-color: black; color: white; border-radius: 4px;")
        
        # --- NEW MEDIA PLAYER CONTROLS ---
        self.playback_ctrl_widget = QWidget()
        playback_ctrl = QHBoxLayout(self.playback_ctrl_widget)
        playback_ctrl.setContentsMargins(0, 0, 0, 0)
        playback_ctrl.setSpacing(5)
        
        btn_style = "background: #34495e; color: white; font-size: 14px; border-radius: 4px;"
        
        self.btn_prev = QPushButton("⏮")
        self.btn_prev.setFixedSize(35, 30)
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.clicked.connect(self._prev_media)
        
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(35, 30)
        self.btn_play.setStyleSheet(btn_style)
        self.btn_play.clicked.connect(self._toggle_playback)
        
        self.btn_next = QPushButton("⏭")
        self.btn_next.setFixedSize(35, 30)
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.clicked.connect(self._next_media)
        
        # Change QSlider to JumpSlider
        self.slider_video = JumpSlider(Qt.Horizontal) 
        self.slider_video.sliderMoved.connect(self._seek_video)
        
        self.btn_fs = QPushButton("⛶")
        self.btn_fs.setFixedSize(35, 30)
        self.btn_fs.setStyleSheet(btn_style)
        self.btn_fs.clicked.connect(self._toggle_fullscreen_preview)
        
        playback_ctrl.addWidget(self.btn_prev)
        playback_ctrl.addWidget(self.btn_play)
        playback_ctrl.addWidget(self.btn_next)
        playback_ctrl.addWidget(self.slider_video)
        playback_ctrl.addWidget(self.btn_fs)

        self.qr_widget = QWidget()
        qr_layout = QHBoxLayout(self.qr_widget)
        qr_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_qr = QLabel("QR")
        self.lbl_qr.setFixedSize(100, 100)
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setStyleSheet("border: 2px solid #2ecc71; background-color: white; color: black; border-radius: 4px; font-size: 10px;")
        
        btn_send = QPushButton("📲 Generate\nLink")
        btn_send.setStyleSheet("background: #9b59b6; color: white; font-weight: bold; font-size: 11px; border-radius: 4px; height: 50px;")
        btn_send.clicked.connect(self._transfer_checked_files_to_phone)
        
        qr_layout.addWidget(self.lbl_qr)
        qr_layout.addWidget(btn_send)
        
        self.lbl_preview_title = QLabel("👁️ Media Player (Tap Video to Play/Pause)")
        self.lbl_preview_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #3498db;")
        
        self.rig.addWidget(self.lbl_preview_title)
        self.rig.addWidget(self.lbl_preview, stretch=1)
        self.rig.addWidget(self.playback_ctrl_widget)
        self.rig.addWidget(self.qr_widget)

        # Save the left and middle layout containers so we can hide them
        self.nav_widget = QWidget()
        self.nav_widget.setLayout(nav)
        
        self.mid_widget = QWidget()
        self.mid_widget.setLayout(mid)

        layout.addWidget(self.nav_widget, 1)
        layout.addWidget(self.mid_widget, 3)
        layout.addLayout(self.rig, 3)
        
        # default to Emergency Video folder with latest video
        self.list_folders.setCurrentRow(1)

    # --- ACTIONS ---
    def _refresh_file_list(self, idx):
        cat = self.list_folders.item(idx).text()
        path = self.paths[cat]
        self.tree_view.setRootIndex(self.file_model.index(path))
        self.tree_view.sortByColumn(0, Qt.DescendingOrder)
        self.btn_restore.setVisible(cat == "Recycle Bin")
        self.btn_delete.setText("🔥 Empty Bin" if cat == "Recycle Bin" else "🗑️ Move to Trash")
        self.btn_select_all.setText("✅ Select All")
        self.btn_select_all.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; padding: 6px; border-radius: 4px;")
        self.file_model._checked_files.clear()
        self.tree_view.hideColumn(1) 
        self.tree_view.hideColumn(2) 
        self.tree_view.hideColumn(3) 
              
    def _toggle_select_all(self):
        root_index = self.tree_view.rootIndex()
        row_count = self.file_model.rowCount(root_index)
        if row_count == 0: return

        should_check = self.btn_select_all.text() != "❌ Deselect All"
        for row in range(row_count):
            index = self.file_model.index(row, 0, root_index)
            state = Qt.Checked if should_check else Qt.Unchecked
            self.file_model.setData(index, state, Qt.CheckStateRole)

        if should_check:
            self.btn_select_all.setText("❌ Deselect All")
            self.btn_select_all.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; padding: 6px; border-radius: 4px;")
        else:
            self.btn_select_all.setText("✅ Select All")
            self.btn_select_all.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; padding: 6px; border-radius: 4px;")
        
    def _preview_selected_item(self):
        self.video_timer.stop()
        if self.media_cap: self.media_cap.release()
        indexes = self.tree_view.selectedIndexes()
        if not indexes: return
        file_path = self.file_model.filePath(indexes[0])
        if not os.path.exists(file_path) or os.path.getsize(file_path) < 100: return

        if file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
            # Load the raw, high-res image file
            new_pix = QPixmap(file_path)
            
            # Pass the raw image to our label (it will handle scaling and caching automatically)
            self.lbl_preview.set_raw_image(new_pix)
            
            self.slider_video.setEnabled(False)
            self.btn_play.setEnabled(False)
            
        elif file_path.lower().endswith('.mp4'):
            # Crucial: Clear the static image cache so it doesn't fight the video frames!
            self.lbl_preview.clear_image()
            
            self.media_cap = cv2.VideoCapture(file_path)
            
            # --- CONFIGURE SLIDER FOR VIDEO LENGTH ---
            total_frames = int(self.media_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames > 0:
                self.slider_video.setMaximum(total_frames - 1)
            
            self.slider_video.setValue(0)
            self.slider_video.setEnabled(True)
            self.btn_play.setEnabled(True)
            self.btn_play.setText("▶")
            self.is_playing = False
            
            # Grab the first frame
            self._update_video_frame()

    def _seek_video(self, position):
        if not self.media_cap: return
        
        now = time.time()
        if not hasattr(self, '_last_seek_time'):
            self._last_seek_time = 0
            
        # THROTTLE: Only execute the heavy OpenCV seek ~15 times a second (0.06s). 
        # This keeps the slider glued to your finger without freezing the interface!
        if now - self._last_seek_time > 0.06:
            self._last_seek_time = now
            
            # 1. Perform the heavy seek operation ONCE
            self.media_cap.set(cv2.CAP_PROP_POS_FRAMES, position)
            
            # 2. Read the preview frame
            ret, frame = self.media_cap.read()
            if ret:
                frame = cv2.resize(frame, (self.lbl_preview.width(), self.lbl_preview.height()))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_RGB888)
                self.lbl_preview.setPixmap(QPixmap.fromImage(img))
                
                # Note: cv2.read() automatically advances the video head by 1 frame. 
                # We intentionally DO NOT set it back to the exact position here, 
                # because doing so doubles the lag, and the user will never notice 
                # a 1-frame difference when they press 'Play'.
    
    def _update_video_frame(self):
        if not self.media_cap: return
        ret, frame = self.media_cap.read()
        if ret:
            curr_frame = int(self.media_cap.get(cv2.CAP_PROP_POS_FRAMES))
            self.slider_video.blockSignals(True)
            self.slider_video.setValue(curr_frame)
            self.slider_video.blockSignals(False)
            
            frame = cv2.resize(frame, (self.lbl_preview.width(), self.lbl_preview.height()))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_RGB888)
            self.lbl_preview.setPixmap(QPixmap.fromImage(img))
        else:
            self.video_timer.stop()
            self.btn_play.setText("▶")
            self.is_playing = False
            self.media_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.slider_video.setValue(0)

    def _toggle_playback(self):
        if not self.media_cap: return
        if self.is_playing: self.video_timer.stop()
        else: self.video_timer.start(33)
        self.is_playing = not self.is_playing
        self.btn_play.setText("⏸" if self.is_playing else "▶")

    def _tree_item_clicked_to_toggle_checkbox(self, index):
        if index.isValid():
            self.file_model.toggleCheckState(self.file_model.index(index.row(), 0, index.parent()))

    def _handle_delete_action(self):
        # 1. Get the list of checked files
        files = self.file_model.getCheckedFiles()
        count = len(files)
        
        # If nothing is checked, just exit
        if count == 0:
            return

        # 2. Determine grammar (1 file vs 2 files)
        file_label = "file" if count == 1 else "files"
        
        # 3. Check current category for specific messaging
        current_cat = self.list_folders.currentItem().text()
        is_trash = (current_cat == "Recycle Bin")

        # 4. Construct the dynamic message
        if is_trash:
            msg = f"Are you sure you want to PERMANENTLY delete {count} {file_label}?\nThis action cannot be undone."
        else:
            msg = f"Move {count} selected {file_label} to the Wastebasket?"

        # 5. Show the confirmation box
        reply = QMessageBox.question(
            self, 
            'Confirmation', 
            msg, 
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            for f in files:
                try:
                    if is_trash:
                        # Permanent deletion from disk
                        if os.path.isdir(f):
                            shutil.rmtree(f)
                        else:
                            os.remove(f)
                    else:
                        # Move to the hidden .trash folder
                        dest = os.path.join(self.TRASH_DIR, os.path.basename(f))
                        
                        # Prevent overwriting if a file with the same name exists in trash
                        if os.path.exists(dest):
                            timestamp = datetime.now().strftime("%H%M%S")
                            name, ext = os.path.splitext(os.path.basename(f))
                            dest = os.path.join(self.TRASH_DIR, f"{name}_{timestamp}{ext}")
                        
                        shutil.move(f, dest)
                except Exception as e:
                    print(f"[ERROR] Failed to handle {f}: {e}")

            # 6. Clear checkboxes and refresh the list
            self.file_model._checked_files.clear()
            self._refresh_file_list(self.list_folders.currentRow())
    
    def _handle_restore_action(self):
        files = self.file_model.getCheckedFiles()
        if not files: 
            return

        for f_path in files:
            filename = os.path.basename(f_path)
            restore_dest = None

            # --- INTELLIGENT ROUTING LOGIC ---
            # Match the file prefix to the correct category in self.paths
            if filename.startswith("EMERGENCY_"):
                restore_dest = self.paths["Emergency Video"]
            
            elif filename.startswith("traffic_"):
                restore_dest = self.paths["Regular Video"]
            
            elif filename.startswith("track_map_") or filename.endswith(".png"):
                restore_dest = self.paths["GPS Tracks"]
            
            elif "Session_" in filename or filename.endswith(".csv"):
                restore_dest = self.paths["Power Logs"]
            
            else:
                # Fallback to Regular Video if no match is found
                restore_dest = self.paths["Regular Video"]

            # --- EXECUTE MOVE ---
            try:
                dest_path = os.path.join(restore_dest, filename)
                
                # Check for collisions (if a file with the same name was recreated)
                if os.path.exists(dest_path):
                    timestamp = datetime.now().strftime("%H%M%S")
                    name, ext = os.path.splitext(filename)
                    dest_path = os.path.join(restore_dest, f"{name}_restored_{timestamp}{ext}")

                shutil.move(f_path, dest_path)
                print(f"[RESTORE] {filename} -> {restore_dest}")
                
            except Exception as e:
                print(f"[ERROR] Restore failed for {filename}: {e}")

        # Refresh UI
        self.file_model._checked_files.clear()
        self._refresh_file_list(self.list_folders.currentRow())
    
    def _transfer_checked_files_to_phone(self):
        files = self.file_model.getCheckedFiles()
        if not files: return
        
        self.lbl_qr.setText("Generating...")
        
        # 1. Ruthlessly kill any existing qrcp processes to free port 8080
        subprocess.run(["pkill", "-9", "-f", "qrcp"], stderr=subprocess.DEVNULL)
        
        def run_qrcp():
            # 2. Start the new process and track it
            self.qrcp_process = subprocess.Popen(["qrcp", "--keep-alive"] + files, stdout=subprocess.PIPE, text=True)
            for line in iter(self.qrcp_process.stdout.readline, ''):
                if "http" in line:
                    url = line.strip().split(" ")[-1]
                    self.signals.qr_url_ready.emit(url)
                    break
                    
        threading.Thread(target=run_qrcp, daemon=True).start()
    #internet
#     def _transfer_checked_files_to_phone(self):
#         file_paths = self.file_model.getCheckedFiles()
#         if not file_paths: 
#             self.lbl_qr.setText("No files selected!\nCheck boxes in column 0.")
#             return
# 
#         self.lbl_qr.setText("Generating Public Link...\nPlease wait.")
#         
#         # Safely kill old processes
#         subprocess.run(["pkill", "-f", "qrcp"], stderr=subprocess.DEVNULL) 
#         subprocess.run(["pkill", "-f", "localhost.run"], stderr=subprocess.DEVNULL) 
#         time.sleep(0.5) 
# 
#         try:
#             # 1. Start QRCP normally (it will use your hotspot IP)
#             self.qrcp_process = subprocess.Popen(
#                 ["qrcp", "--keep-alive", "--port", "8080"] + file_paths,
#                 stdout=subprocess.PIPE, 
#                 stderr=subprocess.STDOUT, 
#                 text=True
#             )
# 
#             def process_transfer():
#                 qrcp_path = ""
#                 qrcp_ip_port = ""
#                 
#                 # 2. Read QRCP output to find exactly where it hosted the file
#                 for line in iter(self.qrcp_process.stdout.readline, ''):
#                     print(f"[QRCP LOG] {line.strip()}")
#                     if "http://" in line or "https://" in line:
#                         local_url = line.strip().split(" ")[-1] 
#                         # Extract the IP/Port and the Path (e.g., 172.20.10.13:8080 and /send/xyz)
#                         stripped = local_url.replace("http://", "").replace("https://", "")
#                         parts = stripped.split("/", 1)
#                         qrcp_ip_port = parts[0] 
#                         qrcp_path = "/" + parts[1] if len(parts) > 1 else "/"
#                         break
#                 
#                 if not qrcp_ip_port:
#                     # To trigger a UI update from a background thread safely:
#                     self.signals.qr_url_ready.emit("Error: QRCP failed to start.")
#                     return
# 
#                 # 3. Start the SSH tunnel, mapped EXACTLY to the IP/Port QRCP just generated
#                 print(f"[TUNNEL] Bridging public web to {qrcp_ip_port}...")
#                 self.tunnel_process = subprocess.Popen(
#                     ["ssh", "-R", f"80:{qrcp_ip_port}", "-o", "StrictHostKeyChecking=no", "nokey@localhost.run"],
#                     stdout=subprocess.PIPE, 
#                     stderr=subprocess.STDOUT, 
#                     text=True
#                 )
#                 
#                 import re
#                 tunnel_base = ""
#                 # 4. Grab the secure public domain
#                 for line in iter(self.tunnel_process.stdout.readline, ''):
#                     print(f"[TUNNEL LOG] {line.strip()}") 
#                     match = re.search(r'(https://[a-zA-Z0-9-]+\.lhr\.life)', line)
#                     if match:
#                         tunnel_base = match.group(1)
#                         break
#                 
#                 # 5. Combine them and blast it to the GUI!
#                 if tunnel_base and qrcp_path:
#                     public_url = tunnel_base + qrcp_path
#                     print(f"\n[SUCCESS] Public URL Ready: {public_url}\n")
#                     self.signals.qr_url_ready.emit(public_url)
#                 else:
#                     self.signals.qr_url_ready.emit("Error: Tunnel failed to secure domain.")
# 
#             # Run this architecture in the background so your GUI stays smooth
#             threading.Thread(target=process_transfer, daemon=True).start()
#             
#         except Exception as e:
#             self.lbl_qr.setText(f"Transfer Error:\n{e}")
    def _select_latest_file_on_boot(self):
        root = self.tree_view.rootIndex()
        if self.file_model.rowCount(root) > 0:
            idx = self.file_model.index(0, 0, root)
            self.tree_view.setCurrentIndex(idx)
            self._preview_selected_item()
    
    def display_qr_code(self, url):
        try:
            import qrcode
            img = qrcode.make(url)
            tmp_path = "/tmp/aras_transfer_qr.png"
            img.save(tmp_path)
            
            pix = QPixmap(tmp_path)
            self.lbl_qr.setPixmap(pix.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.lbl_qr.setStyleSheet("border: 2px solid #2ecc71; background-color: white; border-radius: 4px;")
            
        except ImportError:
            self.lbl_qr.setText(f"Install qrcode")
        except Exception as e:
            self.lbl_qr.setText(f"Error")
    
    def _handle_swipe_left(self):
        """Swiping left mimics 'pulling' the next file onto the screen."""
        if self.is_preview_fullscreen:
            self._next_media()

    def _handle_swipe_right(self):
        """Swiping right 'pulls' the previous file back onto the screen."""
        if self.is_preview_fullscreen:
            self._prev_media()
            
    def _toggle_fullscreen_preview(self):
        """Hides the file lists but KEEPS the media controls for fullscreen playback."""
        main_window = self.window()
        
        if not self.is_preview_fullscreen:
            self.is_preview_fullscreen = True
            
            # Hide Media Browser UI (Do NOT hide playback_ctrl_widget)
            self.nav_widget.hide()
            self.mid_widget.hide()
            self.lbl_preview_title.hide()
            self.qr_widget.hide()
            
            # Hide Global UI
            if hasattr(main_window, 'tabs'):
                main_window.tabs.tabBar().hide()
            if hasattr(main_window, 'top_toolbar'):
                main_window.top_toolbar.hide()
                
            self.lbl_preview.setStyleSheet("background-color: black; color: white; border: none;")
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.rig.setContentsMargins(0, 0, 0, 0)
            
            # Change icon to 'Exit Fullscreen'
            self.btn_fs.setText("🗗") 
            
        else:
            self.is_preview_fullscreen = False
            
            # Restore Media Browser UI
            self.nav_widget.show()
            self.mid_widget.show()
            self.lbl_preview_title.show()
            self.qr_widget.show()
            
            # Restore Global UI
            if hasattr(main_window, 'tabs'):
                main_window.tabs.tabBar().show()
            if hasattr(main_window, 'top_toolbar'):
                main_window.top_toolbar.show()
                
            self.lbl_preview.setStyleSheet("border: 2px solid #34495e; background-color: black; color: white; border-radius: 4px;")
            self.layout().setContentsMargins(5, 5, 5, 5)
            
            # Change icon back to 'Enter Fullscreen'
            self.btn_fs.setText("⛶")
    
    def _next_media(self):
        idx = self.tree_view.currentIndex()
        if not idx.isValid(): return
        
        # Calculate the next row index
        new_idx = self.file_model.index(idx.row() + 1, 0, idx.parent())
        if new_idx.isValid():
            # Changing the selection automatically triggers self._preview_selected_item
            self.tree_view.setCurrentIndex(new_idx)

    def _prev_media(self):
        idx = self.tree_view.currentIndex()
        if not idx.isValid(): return
        
        # Calculate the previous row index
        new_idx = self.file_model.index(idx.row() - 1, 0, idx.parent())
        if new_idx.isValid():
            # Changing the selection automatically triggers self._preview_selected_item
            self.tree_view.setCurrentIndex(new_idx)