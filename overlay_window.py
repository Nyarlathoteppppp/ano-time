from PyQt6.QtWidgets import (QApplication, QWidget, QTextEdit, QVBoxLayout,
                             QSizeGrip, QHBoxLayout, QScrollArea, QLabel, QFrame,
                             QSizePolicy, QLayout)
from PyQt6.QtCore import Qt, QPoint, QRect, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QPainter, QPainterPath

from ctypes import CDLL, c_int32, c_void_p
import time

_CORE_GRAPHICS = CDLL(
    "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
)
_CORE_GRAPHICS.CGShieldingWindowLevel.restype = c_int32
FULLSCREEN_OVERLAY_LEVEL = int(_CORE_GRAPHICS.CGShieldingWindowLevel()) + 1

# macOS: Make window visible on all desktops (Spaces)
try:
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSScreen,
        NSPanel,
        NSScreenSaverWindowLevel,
        NSViewHeightSizable,
        NSViewWidthSizable,
        NSVisualEffectBlendingModeBehindWindow,
        NSVisualEffectMaterialHUDWindow,
        NSVisualEffectStateActive,
        NSVisualEffectView,
        NSWindowBelow,
        NSWindowCollectionBehaviorAuxiliary,
        NSWindowCollectionBehaviorCanJoinAllApplications,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowCollectionBehaviorFullScreenNone,
        NSWindowCollectionBehaviorFullScreenPrimary,
        NSWindowCollectionBehaviorIgnoresCycle,
        NSWindowCollectionBehaviorMoveToActiveSpace,
        NSWindowCollectionBehaviorPrimary,
        NSWindowCollectionBehaviorStationary,
        NSWindowStyleMaskBorderless,
    )
    import objc
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

class LogItem(QFrame):
    """A widget representing a single chunk of transcription/translation"""
    def __init__(self, chunk_id, timestamp, original_text, translated_text="",
                 finalized=False):
        super().__init__()
        self.chunk_id = chunk_id
        self.finalized = bool(finalized)
        
        # Style
        self.setStyleSheet("background-color: transparent;")
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 15) # Bottom margin
        self.layout.setSpacing(2)
        self.setLayout(self.layout)
        
        # Original Text Label
        self.original_label = QLabel(original_text)
        self.original_label.setWordWrap(True)
        self.original_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.original_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._apply_original_style()
        self.layout.addWidget(self.original_label)
        
        # Translated Text Label
        self.translated_label = QLabel(translated_text if translated_text else "...")
        self.translated_label.setWordWrap(True)
        self.translated_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.translated_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.translated_label.setStyleSheet("color: #ffffff; font-family: Arial; font-size: 20px; font-weight: bold;")
        self.layout.addWidget(self.translated_label)
        
    def update_translated(self, text):
        self.translated_label.setText(text)
        self.refresh_layout()

    def update_original(self, text):
        self.original_label.setText(text)
        self.refresh_layout()

    def refresh_layout(self):
        """Recompute wrapped-label heights after text or width changes."""
        margins = self.layout.contentsMargins()
        available_width = max(
            1,
            self.width() - margins.left() - margins.right(),
        )
        original_height = max(
            self.original_label.fontMetrics().height(),
            self.original_label.heightForWidth(available_width),
        )
        translated_height = max(
            self.translated_label.fontMetrics().height(),
            self.translated_label.heightForWidth(available_width),
        )
        self.original_label.setFixedHeight(original_height)
        self.translated_label.setFixedHeight(translated_height)

        spacing = max(0, self.layout.spacing())
        total_height = (
            margins.top() + margins.bottom()
            + original_height + translated_height + spacing
        )
        self.setFixedHeight(total_height)
        self.original_label.updateGeometry()
        self.translated_label.updateGeometry()
        self.layout.invalidate()
        self.updateGeometry()

    def set_finalized(self, finalized):
        # ASR state is monotonic: remote/late updates cannot make final text provisional.
        self.finalized = self.finalized or bool(finalized)
        self._apply_original_style()

    def _apply_original_style(self):
        if self.finalized:
            color = "rgba(245, 247, 252, 245)"
            weight = 600
        else:
            color = "rgba(225, 230, 240, 190)"
            weight = 500
        self.original_label.setStyleSheet(
            f"color: {color}; font-family: Arial; font-size: 15px; "
            f"font-weight: {weight};"
        )

class DragHandle(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setText("⠿  Drag subtitles")
        self.setStyleSheet(
            "color: rgba(255,255,255,150); font-size: 12px; "
            "padding: 5px 8px; background: transparent;"
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.start_pos = None
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()
            event.accept()
            
    def mouseMoveEvent(self, event):
        if self.start_pos:
            current = event.globalPosition().toPoint()
            delta = current - self.start_pos
            self.parent_window.move(
                self.parent_window.x() + delta.x(),
                self.parent_window.y() + delta.y(),
            )
            self.start_pos = current
            event.accept()
            
    def mouseReleaseEvent(self, event):
        self.start_pos = None


class ResizeBorder(QWidget):
    """Invisible resize target for one edge or corner of a frameless window."""

    CURSORS = {
        "left": Qt.CursorShape.SizeHorCursor,
        "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor,
        "bottom": Qt.CursorShape.SizeVerCursor,
        "top_left": Qt.CursorShape.SizeFDiagCursor,
        "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        "top_right": Qt.CursorShape.SizeBDiagCursor,
        "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, parent, edges):
        super().__init__(parent)
        self.parent_window = parent
        self.edges = edges
        self._start_global = None
        self._start_geometry = None
        self.setCursor(self.CURSORS[edges])
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_global = event.globalPosition().toPoint()
            self._start_geometry = self.parent_window.geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._start_global is None or self._start_geometry is None:
            return
        self._resize_from_global(event.globalPosition().toPoint())
        event.accept()

    def _resize_from_global(self, current):
        delta = current - self._start_global
        start = self._start_geometry
        minimum = self.parent_window.minimumSize()
        left, top, right, bottom = (
            start.left(), start.top(), start.right(), start.bottom()
        )

        if "left" in self.edges:
            left = min(start.left() + delta.x(), right - minimum.width() + 1)
        if "right" in self.edges:
            right = max(start.right() + delta.x(), left + minimum.width() - 1)
        if "top" in self.edges:
            top = min(start.top() + delta.y(), bottom - minimum.height() + 1)
        if "bottom" in self.edges:
            bottom = max(start.bottom() + delta.y(), top + minimum.height() - 1)

        self.parent_window.setGeometry(QRect(QPoint(left, top), QPoint(right, bottom)))

    def mouseReleaseEvent(self, event):
        self._start_global = None
        self._start_geometry = None
        event.accept()


class NotchSurface(QFrame):
    """Transparent surface that grows downward from the physical display notch."""
    mode_switch_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.notch_mode = False
        self.notch_width = 185
        self.notch_height = 32

    def set_notch_geometry(self, enabled, width=185, height=32):
        self.notch_mode = enabled
        self.notch_width = max(1, int(width))
        self.notch_height = max(1, int(height))
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self.notch_mode and event.button() == Qt.MouseButton.LeftButton:
            self.mode_switch_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.notch_mode:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 248))

        center_x = self.width() / 2
        neck_left = center_x - self.notch_width / 2
        path = QPainterPath()
        path.addRect(neck_left, 0, self.notch_width, self.notch_height + 8)
        path.addRoundedRect(0, self.notch_height - 5,
                            self.width(), self.height() - self.notch_height + 5,
                            25, 25)
        painter.drawPath(path)

class OverlayWindow(QWidget):
    stop_requested = pyqtSignal()
    notch_requested = pyqtSignal()

    def __init__(self, display_duration=None, window_width=400, window_height=None,
                 display_mode="glass", allow_notch_switch=False,
                 video_overlay=False):
        super().__init__()
        # display_duration is not really used in log mode, but kept for compatibility
        self.window_width = window_width
        self.allow_notch_switch = allow_notch_switch
        
        # Default height to full screen height if not specified
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        self.window_height = window_height if window_height else screen_geometry.height()
        self.display_mode = display_mode if display_mode in ("glass", "notch") else "glass"
        self.video_overlay = bool(video_overlay)
        self._glass_geometry = None
        self._settings = QSettings("RealtimeTon", "RealtimeTranslator")
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_glass_geometry)
        self._content_reflow_timer = QTimer(self)
        self._content_reflow_timer.setSingleShot(True)
        self._content_reflow_timer.timeout.connect(self._reflow_content)
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(1000)
        self._topmost_timer.timeout.connect(
            lambda: self._set_all_spaces(log_ready=False)
        )
        self._last_native_visibility = None
        self._native_blur_window = None
        self._native_blur_view = None
        
        self.initUI()
        self.oldPos = self.pos()

    def showEvent(self, event):
        """Called when window is shown - set all-spaces behavior here"""
        super().showEvent(event)
        if HAS_APPKIT:
            self._set_all_spaces(log_ready=True)
            # Qt and macOS can both update the native window during a Space/full-
            # screen transition. Reassert the panel behavior after those updates.
            QTimer.singleShot(0, self._set_all_spaces)
            QTimer.singleShot(300, self._set_all_spaces)
            self._topmost_timer.start()

    def hideEvent(self, event):
        self._topmost_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._topmost_timer.stop()
        if self._native_blur_window is not None:
            self._native_blur_window.close()
            self._native_blur_window = None
            self._native_blur_view = None
        super().closeEvent(event)

    def _install_native_blur(self, ns_window):
        """Put an AppKit vibrancy panel behind microphone-mode glass."""
        if self._native_blur_window is not None or self.video_overlay:
            return
        blur_window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ns_window.frame(), NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered, False,
        )
        blur_window.setOpaque_(False)
        blur_window.setBackgroundColor_(NSColor.clearColor())
        blur_window.setHasShadow_(False)
        blur_window.setIgnoresMouseEvents_(True)
        blur_window.setHidesOnDeactivate_(False)
        blur_window.setCanHide_(False)
        blur_window.setCollectionBehavior_(ns_window.collectionBehavior())
        blur_window.setLevel_(NSScreenSaverWindowLevel)

        effect = NSVisualEffectView.alloc().initWithFrame_(
            blur_window.contentView().bounds()
        )
        effect.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(20.0)
        effect.layer().setMasksToBounds_(True)
        effect.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                1.0, 0.58, 0.75, 0.16
            ).CGColor()
        )
        blur_window.contentView().addSubview_(effect)
        ns_window.addChildWindow_ordered_(blur_window, NSWindowBelow)
        self._native_blur_window = blur_window
        self._native_blur_view = effect
        print("[Overlay] Native macOS HUD blur installed", flush=True)

    def _sync_native_blur(self, ns_window):
        if self._native_blur_window is None:
            return
        self._native_blur_window.setFrame_display_(ns_window.frame(), True)
        if self.display_mode == "glass" and self.isVisible():
            self._native_blur_window.orderFrontRegardless()
            ns_window.orderFrontRegardless()
        else:
            self._native_blur_window.orderOut_(None)
    
    def _set_all_spaces(self, log_ready=False):
        """Make window appear on all macOS Spaces/Desktops"""
        try:
            # Get the native NSWindow from Qt's winId
            win_id = int(self.winId())
            ns_view = objc.objc_object(c_void_p=c_void_p(win_id))
            ns_window = ns_view.window()
            current_behavior = int(ns_window.collectionBehavior())
            current_behavior &= ~NSWindowCollectionBehaviorStationary
            current_behavior &= ~NSWindowCollectionBehaviorMoveToActiveSpace
            # Qt adds the legacy FullScreenAuxiliary role to QNSPanel. On modern
            # macOS that role can override CanJoinAllApplications during a
            # browser's separate full-screen Space, so keep exactly one modern
            # Stage Manager/full-screen role.
            current_behavior &= ~NSWindowCollectionBehaviorPrimary
            current_behavior &= ~NSWindowCollectionBehaviorAuxiliary
            current_behavior &= ~NSWindowCollectionBehaviorFullScreenPrimary
            current_behavior &= ~NSWindowCollectionBehaviorFullScreenAuxiliary
            current_behavior &= ~NSWindowCollectionBehaviorFullScreenNone
            ns_window.setCollectionBehavior_(
                current_behavior |
                NSWindowCollectionBehaviorCanJoinAllApplications |
                NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorIgnoresCycle
            )
            ns_window.setHidesOnDeactivate_(False)
            ns_window.setCanHide_(False)
            if ns_window.isKindOfClass_(NSPanel):
                ns_window.setFloatingPanel_(True)
                ns_window.setBecomesKeyOnlyIfNeeded_(True)
            # Place subtitles above the CoreGraphics display shield. This is
            # intentionally stronger than normal always-on-top/screen-saver
            # levels so browser-native video full screen cannot cover them.
            ns_window.setCanBecomeVisibleWithoutLogin_(False)
            ns_window.setLevel_(FULLSCREEN_OVERLAY_LEVEL)
            if self.display_mode == "glass" and not self.video_overlay:
                self._install_native_blur(ns_window)
            self._sync_native_blur(ns_window)
            ns_window.orderFrontRegardless()
            native_visibility = (
                bool(ns_window.isVisible()),
                bool(ns_window.isOnActiveSpace()),
                int(ns_window.occlusionState()),
            )
            if log_ready:
                print(
                    "[Overlay] Full-screen auxiliary panel ready "
                    f"(class={ns_window.className()}, "
                    f"level={int(ns_window.level())}, "
                    f"behavior={int(ns_window.collectionBehavior())})",
                    flush=True,
                )
            if native_visibility != self._last_native_visibility:
                self._last_native_visibility = native_visibility
                print(
                    "[Overlay] Native visibility "
                    f"(visible={native_visibility[0]}, "
                    f"active_space={native_visibility[1]}, "
                    f"occlusion={native_visibility[2]})",
                    flush=True,
                )
        except Exception as e:
            print(f"Could not set all-spaces behavior: {e}")

    def initUI(self):
        # Window flags for transparency and staying on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Force creation of the native NSWindow before the first show so its
        # collection behavior is in place when a browser is already full-screen.
        if HAS_APPKIT:
            self.winId()
            self._set_all_spaces()
        self.setMinimumSize(320, 140)

        # Frameless Qt windows otherwise expose only the bottom-right QSizeGrip.
        self.resize_borders = {
            name: ResizeBorder(self, name)
            for name in (
                "left", "right", "top", "bottom",
                "top_left", "top_right", "bottom_left", "bottom_right",
            )
        }
        
        # Layout
        self.root_layout = QVBoxLayout()
        self.root_layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(self.root_layout)

        # Compact drag surface; video mode keeps the content background clear.
        self.drag_handle = DragHandle(self)
        if self.video_overlay:
            self.drag_handle.setText("⠿  Move")
            self.drag_handle.setFixedHeight(24)
        self.drag_handle.setToolTip("Drag subtitle window")
        self.root_layout.addWidget(self.drag_handle)
        
        # SCROLL AREA
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # Transparent scroll area
        self.scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; }
            QScrollBar:vertical { width: 0px; }
        """)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Container for LogItems
        self.container = NotchSurface()
        self.container.setObjectName("glassPanel")
        self.container.mode_switch_requested.connect(self.toggle_display_mode)
        self._set_glass_style()
        self.container_layout = QVBoxLayout()
        self.container_layout.setContentsMargins(10, 10, 10, 10)
        self.container_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        # Allocate alignment to top so items stack from top
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.container.setLayout(self.container_layout)
        
        self.scroll_area.setWidget(self.container)
        self.root_layout.addWidget(self.scroll_area)
        
        # Bottom Control Bar (Resize Grip + Save Button)
        self.control_bar = QWidget()
        grip_layout = QHBoxLayout(self.control_bar)
        grip_layout.setContentsMargins(0, 0, 0, 0)
        
        # Save Button
        from PyQt6.QtWidgets import QPushButton, QStyle 
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setFixedWidth(80)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 50);
                color: white;
                border-radius: 5px;
                padding: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 100);
            }
        """)
        self.save_btn.clicked.connect(self._save_transcript)
        
        grip_layout.addWidget(self.save_btn)
        
        # Stop Button
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setToolTip("退出翻译并返回控制中心")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFixedSize(30, 30)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(243, 139, 168, 150);
                color: white;
                border-radius: 15px;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(243, 139, 168, 200);
            }
        """)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        grip_layout.addWidget(self.stop_btn)

        self.mode_btn = QPushButton()
        self.mode_btn.setToolTip("Switch between glass and notch subtitle modes")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.setFixedHeight(30)
        self.mode_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(247, 168, 201, 105);
                color: white;
                border-radius: 7px;
                padding: 4px 10px;
                border: none;
            }
            QPushButton:hover { background-color: rgba(255, 193, 218, 165); }
        """)
        self.mode_btn.clicked.connect(self.notch_requested.emit)
        grip_layout.addWidget(self.mode_btn)
        
        grip_layout.addStretch()
        
        # Native corner grip works reliably with frameless Qt windows.
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(26, 26)
        self.size_grip.setToolTip("Resize here, or drag any window edge/corner")
        self.size_grip.setStyleSheet("background: rgba(255,255,255,35); border-radius: 6px;")
        grip_layout.addWidget(self.size_grip)
        
        self.root_layout.addWidget(self.control_bar)
        
        # Set initial window size
        self.resize(self.window_width, self.window_height)
        
        # Position: Right side of screen, full height
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - self.window_width - 20 # 20px padding from right
        y = screen.y()
        self.move(x, y)
        saved_geometry = self._settings.value("glass/geometry")
        if self.display_mode == "glass" and saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        self._glass_geometry = self.geometry()
        
        # Data storage: list of (chunk_id, widget) inclusive
        self.items = [] # Sorted by chunk_id
        
        # History for saving (list of dicts)
        self.transcript_data = {} # chunk_id -> {timestamp, original, translated}
        
        # State
        self.is_moving = False
        
        # Enable mouse tracking for cursor update without click
        self.setMouseTracking(True)
        self.set_display_mode(self.display_mode, initial=True)

    def _layout_resize_borders(self):
        edge = 8
        corner = 16
        width, height = self.width(), self.height()
        geometries = {
            "left": (0, corner, edge, max(0, height - 2 * corner)),
            "right": (width - edge, corner, edge, max(0, height - 2 * corner)),
            "top": (corner, 0, max(0, width - 2 * corner), edge),
            "bottom": (corner, height - edge, max(0, width - 2 * corner), edge),
            "top_left": (0, 0, corner, corner),
            "top_right": (width - corner, 0, corner, corner),
            "bottom_left": (0, height - corner, corner, corner),
            "bottom_right": (width - corner, height - corner, corner, corner),
        }
        for name, handle in self.resize_borders.items():
            handle.setGeometry(*geometries[name])
            handle.raise_()

    def _schedule_geometry_save(self):
        if self.display_mode == "glass" and self.isVisible():
            self._geometry_save_timer.start(350)

    def _save_glass_geometry(self):
        if self.display_mode == "glass":
            self._settings.setValue("glass/geometry", self.saveGeometry())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "resize_borders"):
            self._layout_resize_borders()
            self._schedule_geometry_save()
        if hasattr(self, "_content_reflow_timer"):
            self._schedule_content_reflow()
        if HAS_APPKIT and self._native_blur_window is not None:
            self._set_all_spaces()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "_geometry_save_timer"):
            self._schedule_geometry_save()
        if HAS_APPKIT and self._native_blur_window is not None:
            self._set_all_spaces()

    def _set_glass_style(self):
        self.container.set_notch_geometry(False)
        # The native blur/transparent top-level window is the only surface.
        # Keeping this inner frame clear avoids a visible frame-within-frame.
        self.container.setStyleSheet("""
            QFrame#glassPanel {
                background-color: transparent;
                border: none;
            }
        """)

    def _set_notch_style(self):
        self.container.setStyleSheet("""
            QFrame#glassPanel {
                background-color: transparent;
                border: none;
            }
        """)

    def _physical_notch_metrics(self):
        """Return the built-in display camera-housing width and top inset in points."""
        if not HAS_APPKIT:
            return None
        try:
            candidates = []
            for ns_screen in NSScreen.screens():
                inset = float(ns_screen.safeAreaInsets().top)
                left = ns_screen.auxiliaryTopLeftArea()
                right = ns_screen.auxiliaryTopRightArea()
                if inset <= 0 or left is None or right is None:
                    continue
                left_edge = float(left.origin.x + left.size.width)
                right_edge = float(right.origin.x)
                width = right_edge - left_edge
                if width > 0:
                    candidates.append((inset, width, str(ns_screen.localizedName())))
            if not candidates:
                return None
            inset, width, name = max(candidates, key=lambda item: item[0])
            print(f"[Overlay] Physical notch detected on {name}: {width:.0f}x{inset:.0f} pt")
            return int(round(width)), int(round(inset))
        except Exception as exc:
            print(f"[Overlay] Could not read physical notch geometry: {exc}")
            return None

    def toggle_display_mode(self):
        self.set_display_mode("notch" if self.display_mode == "glass" else "glass")

    def set_display_mode(self, mode, initial=False):
        mode = mode if mode in ("glass", "notch") else "glass"
        if not initial and self.display_mode == "glass":
            self._glass_geometry = self.geometry()
        self.display_mode = mode

        if mode == "notch":
            self._set_notch_style()
            self.drag_handle.hide()
            self.control_bar.hide()
            self.root_layout.setContentsMargins(0, 0, 0, 0)
            metrics = self._physical_notch_metrics()
            notch_width, notch_height = metrics if metrics else (185, 32)
            self.container.set_notch_geometry(True, notch_width, notch_height)
            self.container.setToolTip("Double-click to return to glass subtitle mode")
            self.container_layout.setContentsMargins(18, notch_height + 9, 18, 12)
            screen = QApplication.primaryScreen().geometry()
            width = min(max(680, notch_width + 420), screen.width() - 32)
            height = max(148, notch_height + 108)
            self.resize(width, height)
            self.move(screen.x() + (screen.width() - width) // 2, screen.y())
            for handle in self.resize_borders.values():
                handle.hide()
        else:
            self._set_glass_style()
            self.drag_handle.show()
            self.control_bar.show()
            if self.video_overlay:
                self.root_layout.setContentsMargins(0, 0, 0, 0)
                self.container_layout.setContentsMargins(8, 2, 8, 4)
                self.drag_handle.setText("⠿  Move")
            else:
                self.root_layout.setContentsMargins(10, 10, 10, 10)
                self.container_layout.setContentsMargins(10, 10, 10, 10)
                self.drag_handle.setText("⠿  Drag subtitles")
            self.mode_btn.setText("◒ Physical Notch")
            self.mode_btn.setVisible(self.allow_notch_switch)
            if not initial and self._glass_geometry is not None:
                self.setGeometry(self._glass_geometry)
            for handle in self.resize_borders.values():
                handle.show()
                handle.raise_()

        self._apply_item_visibility()
        self._schedule_content_reflow()
        if HAS_APPKIT and self.isVisible():
            self._set_all_spaces()

    def _schedule_content_reflow(self):
        # Coalesce rapid ASR partials while still refreshing on the next event loop.
        self._content_reflow_timer.start(0)

    def _reflow_content(self):
        for _, widget in self.items:
            if widget.isVisible():
                widget.refresh_layout()
        self.container_layout.invalidate()
        self.container_layout.activate()
        self.container.updateGeometry()
        self.scroll_area.widget().updateGeometry()
        self._scroll_to_bottom()
        # The scroll range is finalized one layout pass later on macOS/Qt.
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _apply_item_visibility(self):
        if not self.items:
            return
        latest_id = max(cid for cid, _ in self.items)
        for cid, widget in self.items:
            widget.setVisible(self.display_mode == "glass" or cid == latest_id)
        self._schedule_content_reflow()

    def update_text(self, chunk_id, original_text, translated_text, state="partial"):
        """Append new text or update existing text"""
        finalized = state == "final"
        existing_data = self.transcript_data.get(chunk_id)
        if existing_data and existing_data.get('finalized', False) and not finalized:
            return
        # Update data store
        if chunk_id not in self.transcript_data:
            self.transcript_data[chunk_id] = {
                'timestamp': time.strftime("%H:%M:%S"),
                'original': original_text,
                'translated': translated_text,
                'finalized': finalized,
            }
        else:
            self.transcript_data[chunk_id]['finalized'] = (
                self.transcript_data[chunk_id].get('finalized', False) or finalized
            )
            if original_text:
                self.transcript_data[chunk_id]['original'] = original_text
            if translated_text:
                self.transcript_data[chunk_id]['translated'] = translated_text
        
        # Check if widget exists
        existing_widget = None
        for cid, widget in self.items:
            if cid == chunk_id:
                existing_widget = widget
                break
        
        if existing_widget:
            # Update existing
            if original_text:
                existing_widget.update_original(original_text)
            
            if translated_text:
                existing_widget.update_translated(translated_text)
            existing_widget.set_finalized(finalized)
                
        else:
            # Insert new widget in order
            timestamp = self.transcript_data[chunk_id]['timestamp']
            new_widget = LogItem(
                chunk_id,
                timestamp,
                original_text,
                translated_text,
                finalized=self.transcript_data[chunk_id]['finalized'],
            )
            
            # Find insertion point
            insert_idx = len(self.items)
            for i, (cid, w) in enumerate(self.items):
                if cid > chunk_id:
                    insert_idx = i
                    break
            
            self.items.insert(insert_idx, (chunk_id, new_widget))
            self.container_layout.insertWidget(insert_idx, new_widget)
            # Bound the live widget tree during multi-hour classes. Full history
            # remains in transcript_data and is still exported by Save.
            while len(self.items) > 200:
                _, stale_widget = self.items.pop(0)
                self.container_layout.removeWidget(stale_widget)
                stale_widget.deleteLater()

            # Scroll to bottom
            QTimer.singleShot(10, self._scroll_to_bottom)

        self._apply_item_visibility()

    def _scroll_to_bottom(self):
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _save_transcript(self):
        """Save history to file"""
        import os
        if not self.transcript_data:
            print("[Overlay] Nothing to save.")
            return

        os.makedirs("transcripts", exist_ok=True)
        filename = f"transcripts/transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        
        # Sort by chunk_id
        sorted_ids = sorted(self.transcript_data.keys())
        
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"Transcript saved at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*50 + "\n\n")
                for cid in sorted_ids:
                    data = self.transcript_data[cid]
                    f.write(f"[{data['timestamp']}] (ID: {cid})\nOriginal: {data['original']}\nTranslation: {data['translated']}\n{'-'*30}\n")
            
            print(f"[Overlay] Saved to {filename}")
            # Visual feedback on button
            original_text = self.save_btn.text()
            self.save_btn.setText("Saved!")
            QTimer.singleShot(2000, lambda: self.save_btn.setText(original_text))
            
        except Exception as e:
            print(f"[Overlay] Error saving transcript: {e}")



    # Window Moving Logic (Resize is handled by ResizeHandle widget)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_moving = True
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        # Update cursor shape based on position (reset to arrow)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        
        # Handle dragging
        if self.is_moving:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()
            
    def mouseReleaseEvent(self, event):
        self.is_moving = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = OverlayWindow()
    window.show()
    # Test update
    window.update_text(1, "Hello world", "")
    QTimer.singleShot(1000, lambda: window.update_text(1, "Hello world", "你好，世界"))
    window.update_text(2, "Sequence test", "")
    sys.exit(app.exec())
