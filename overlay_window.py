from PyQt6.QtWidgets import (QApplication, QWidget, QTextEdit, QVBoxLayout,
                             QHBoxLayout, QScrollArea, QLabel, QFrame,
                             QSizePolicy, QLayout, QMenu)
from PyQt6.QtCore import Qt, QPoint, QRect, QSettings, QTimer, pyqtSignal

from ctypes import CDLL, c_int32, c_void_p
import html
import time

from subtitle_revision import SubtitleRevisionPlanner

_CORE_GRAPHICS = CDLL(
    "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
)
_CORE_GRAPHICS.CGShieldingWindowLevel.restype = c_int32
FULLSCREEN_OVERLAY_LEVEL = int(_CORE_GRAPHICS.CGShieldingWindowLevel()) + 1
MAX_VISIBLE_TRANSCRIPT_ITEMS = 40
# Keep the subtitle panel readable over video without turning it into an opaque
# black block. 179/255 is roughly 70% opaque (30% transparent).
GLASS_PANEL_BACKGROUND = "rgba(0, 0, 0, 179)"


def clamp_window_rect(rect, available_rects, minimum_width=320,
                      minimum_height=140):
    """Keep a restored window usable after displays are disconnected."""
    original = QRect(rect)
    screens = [QRect(bounds) for bounds in available_rects if bounds.isValid()]
    if not screens:
        return original

    target = next(
        (bounds for bounds in screens if bounds.contains(original.center())),
        None,
    )
    if target is None:
        target = max(
            screens,
            key=lambda bounds: original.intersected(bounds).width()
            * original.intersected(bounds).height(),
        )
        if original.intersected(target).isEmpty():
            target = screens[0]

    width = min(max(original.width(), int(minimum_width)), target.width())
    height = min(max(original.height(), int(minimum_height)), target.height())
    max_x = target.x() + target.width() - width
    max_y = target.y() + target.height() - height
    x = min(max(original.x(), target.x()), max_x)
    y = min(max(original.y(), target.y()), max_y)
    return QRect(x, y, width, height)

# macOS: Make window visible on all desktops (Spaces)
try:
    from AppKit import (
        NSPanel,
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
    )
    import objc
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

class LogItem(QFrame):
    """A widget representing a single chunk of transcription/translation"""
    def __init__(self, chunk_id, timestamp, original_text, translated_text="",
                 finalized=False, committed_prefix_length=0):
        super().__init__()
        self.chunk_id = chunk_id
        self.finalized = bool(finalized)
        
        # Style
        self.setStyleSheet("background-color: transparent;")
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 15)
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
        self._translated_text = str(translated_text or "")
        self._committed_prefix_length = self._clamp_committed_prefix(
            committed_prefix_length,
            self._translated_text,
        )
        self._revision = SubtitleRevisionPlanner.plan("", self._translated_text)
        self._revision_highlight_timer = QTimer(self)
        self._revision_highlight_timer.setSingleShot(True)
        self._revision_highlight_timer.setInterval(180)
        self._revision_highlight_timer.timeout.connect(
            self._clear_revision_highlight
        )
        self.translated_label = QLabel()
        self.translated_label.setTextFormat(Qt.TextFormat.RichText)
        self.translated_label.setWordWrap(True)
        self.translated_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.translated_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.translated_label.setStyleSheet("color: #ffffff; font-family: Arial; font-size: 20px; font-weight: bold;")
        self._render_translation()
        self.layout.addWidget(self.translated_label)
        
    @staticmethod
    def _clamp_committed_prefix(length, text):
        return max(0, min(int(length or 0), len(text)))

    def _render_translation(self):
        if not self._translated_text:
            self.translated_label.clear()
            self.translated_label.hide()
            return
        self.translated_label.show()
        offset = 0
        rendered = []
        for span in self._revision.spans:
            span_end = offset + len(span.text)
            stable_length = max(
                0,
                min(span_end, self._committed_prefix_length) - offset,
            )
            if stable_length:
                rendered.append(
                    '<span style="color:#ffffff">'
                    f'{html.escape(span.text[:stable_length])}</span>'
                )
            remainder = span.text[stable_length:]
            if remainder:
                if span.changed:
                    rendered.append(
                        '<span style="color:#ffffff;font-weight:700">'
                        f'{html.escape(remainder)}</span>'
                    )
                else:
                    rendered.append(
                        '<span style="color:#d7dbe5">'
                        f'{html.escape(remainder)}</span>'
                    )
            offset = span_end
        self.translated_label.setText("".join(rendered))

    def _clear_revision_highlight(self):
        self._revision = SubtitleRevisionPlanner.plan(
            self._translated_text,
            self._translated_text,
        )
        self._render_translation()

    def update_translated(self, text, committed_prefix_length=0):
        text = str(text or "")
        committed_prefix_length = self._clamp_committed_prefix(
            committed_prefix_length,
            text,
        )
        if (
            text == self._translated_text
            and committed_prefix_length == self._committed_prefix_length
        ):
            return False
        previous_height = self.translated_label.height()
        self._revision = SubtitleRevisionPlanner.plan(
            self._translated_text,
            text,
        )
        self._translated_text = text
        self._committed_prefix_length = committed_prefix_length
        self._render_translation()
        if any(span.changed for span in self._revision.spans):
            self._revision_highlight_timer.start()
        available_width = max(1, self.width())
        next_height = max(
            self.translated_label.fontMetrics().height(),
            self.translated_label.heightForWidth(available_width),
        )
        if next_height != previous_height:
            self.refresh_layout()
            return True
        self.translated_label.update()
        return False

    def update_original(self, text):
        if text == self.original_label.text():
            return False
        previous_height = self.original_label.height()
        self.original_label.setText(text)
        available_width = max(1, self.width())
        next_height = max(
            self.original_label.fontMetrics().height(),
            self.original_label.heightForWidth(available_width),
        )
        if next_height != previous_height:
            self.refresh_layout()
            return True
        self.original_label.update()
        return False

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

    def __init__(self, parent, edges):
        super().__init__(parent)
        self.parent_window = parent
        self.edges = edges
        self._start_global = None
        self._start_geometry = None
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


class GlassSurface(QFrame):
    """Glass subtitle surface; double-click can request the native notch."""
    mode_switch_requested = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mode_switch_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
        # The physical notch is rendered exclusively by NativeNotchOverlay.
        self.display_mode = "glass"
        self.video_overlay = bool(video_overlay)
        self._glass_geometry = None
        self._settings = QSettings("RealtimeTon", "RealtimeTranslator")
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_glass_geometry)
        self._content_reflow_timer = QTimer(self)
        self._content_reflow_timer.setSingleShot(True)
        self._content_reflow_timer.timeout.connect(self._reflow_content)
        self._follow_scroll_tail = True
        self._programmatic_scroll = False
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(1000)
        self._topmost_timer.timeout.connect(
            self._maintain_topmost
        )
        self._last_native_visibility = None
        
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
        super().closeEvent(event)
    
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

    def _maintain_topmost(self):
        """Reassert fullscreen behavior only when macOS changed native state."""
        if not HAS_APPKIT or not self.isVisible():
            return
        try:
            ns_view = objc.objc_object(c_void_p=c_void_p(int(self.winId())))
            ns_window = ns_view.window()
            behavior = int(ns_window.collectionBehavior())
            required = (
                NSWindowCollectionBehaviorCanJoinAllApplications
                | NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorIgnoresCycle
            )
            needs_repair = (
                int(ns_window.level()) != FULLSCREEN_OVERLAY_LEVEL
                or behavior & required != required
                or not bool(ns_window.isVisible())
                or not bool(ns_window.isOnActiveSpace())
            )
            if needs_repair:
                self._set_all_spaces(log_ready=False)
        except Exception:
            self._set_all_spaces(log_ready=False)

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

        # Resize borders preserve any-edge/corner resizing without assigning a
        # custom QCursor.  Qt 6.11's custom cursor conversion can crash on
        # macOS 26 when this window is entered after a mode switch.
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
        self.container = GlassSurface()
        self.container.setObjectName("glassPanel")
        if self.allow_notch_switch:
            self.container.mode_switch_requested.connect(self.notch_requested.emit)
        self._set_glass_style()
        self.container_layout = QVBoxLayout()
        self.container_layout.setContentsMargins(10, 10, 10, 10)
        self.container_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        # Allocate alignment to top so items stack from top
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.container.setLayout(self.container_layout)
        
        self.scroll_area.setWidget(self.container)
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.actionTriggered.connect(self._on_scroll_action)
        scrollbar.sliderMoved.connect(self._on_scroll_position_changed)
        scrollbar.rangeChanged.connect(self._on_scroll_range_changed)
        self.root_layout.addWidget(self.scroll_area)
        
        # Bottom control bar: stopping and resizing remain available.  Lecture
        # transcripts are written automatically by SessionTranscriptRecorder,
        # so a second manual Save action would only duplicate records.
        self.control_bar = QWidget()
        grip_layout = QHBoxLayout(self.control_bar)
        grip_layout.setContentsMargins(0, 0, 0, 0)
        from PyQt6.QtWidgets import QPushButton
        
        # Stop Button
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setToolTip("退出翻译并返回控制中心")
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
            self._clamp_glass_geometry()
        self._glass_geometry = self.geometry()
        
        # Data storage: list of (chunk_id, widget) inclusive
        self.items = [] # Sorted by chunk_id
        
        # History for saving (list of dicts)
        self.transcript_data = {} # chunk_id -> {timestamp, original, translated}
        
        # State
        self.is_moving = False
        
        # Enable mouse tracking for cursor update without click
        self.setMouseTracking(True)
        self._configure_glass_mode(initial=True)

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

    def _clamp_glass_geometry(self):
        screens = [screen.availableGeometry() for screen in QApplication.screens()]
        clamped = clamp_window_rect(
            self.geometry(),
            screens,
            self.minimumWidth(),
            self.minimumHeight(),
        )
        if clamped != self.geometry():
            self.setGeometry(clamped)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "resize_borders"):
            self._layout_resize_borders()
            self._schedule_geometry_save()
        if hasattr(self, "_content_reflow_timer"):
            self._schedule_content_reflow()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "_geometry_save_timer"):
            self._schedule_geometry_save()

    def _set_glass_style(self):
        self.container.setStyleSheet(f"""
            QFrame#glassPanel {{
                background-color: {GLASS_PANEL_BACKGROUND};
                border: none;
                border-radius: 20px;
            }}
        """)

    def _configure_glass_mode(self, initial=False):
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

    def _on_scroll_position_changed(self, value):
        if self._programmatic_scroll:
            return
        scrollbar = self.scroll_area.verticalScrollBar()
        self._follow_scroll_tail = value >= max(0, scrollbar.maximum() - 24)

    def _on_scroll_action(self, _action):
        # actionTriggered arrives before Qt applies the new scrollbar value.
        QTimer.singleShot(
            0,
            lambda: self._on_scroll_position_changed(
                self.scroll_area.verticalScrollBar().value()
            ),
        )

    def _on_scroll_range_changed(self, _minimum, _maximum):
        # A long draft can become much shorter when the final model replaces it.
        # Keep tail-following users attached to valid content after that reflow,
        # but leave manually reviewed history exactly where it is.
        if self._follow_scroll_tail:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _apply_item_visibility(self):
        if not self.items:
            return
        latest_id = max(cid for cid, _ in self.items)
        visibility_changed = False
        for cid, widget in self.items:
            should_show = self.display_mode == "glass" or cid == latest_id
            if widget.isHidden() == should_show:
                widget.setVisible(should_show)
                visibility_changed = True
        if visibility_changed:
            self._schedule_content_reflow()

    def _trim_visible_items(self):
        """Bound live Qt widgets without removing full transcript records."""
        while len(self.items) > MAX_VISIBLE_TRANSCRIPT_ITEMS:
            _, stale_widget = self.items.pop(0)
            self.container_layout.removeWidget(stale_widget)
            stale_widget.deleteLater()

    def update_event(self, event):
        self.update_text(
            event.segment_id,
            event.original_text,
            event.translated_text,
            event.legacy_state,
            event.committed_prefix_length,
        )

    def update_text(
        self,
        chunk_id,
        original_text,
        translated_text,
        state="partial",
        committed_prefix_length=0,
    ):
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
                'committed_prefix_length': max(
                    0,
                    min(int(committed_prefix_length or 0), len(translated_text or "")),
                ),
            }
        else:
            self.transcript_data[chunk_id]['finalized'] = (
                self.transcript_data[chunk_id].get('finalized', False) or finalized
            )
            if original_text:
                self.transcript_data[chunk_id]['original'] = original_text
            if translated_text:
                self.transcript_data[chunk_id]['translated'] = translated_text
                self.transcript_data[chunk_id]['committed_prefix_length'] = max(
                    0,
                    min(int(committed_prefix_length or 0), len(translated_text)),
                )
        
        # Check if widget exists
        existing_widget = None
        for cid, widget in self.items:
            if cid == chunk_id:
                existing_widget = widget
                break
        
        if existing_widget:
            # Update existing
            layout_changed = False
            if original_text:
                layout_changed = (
                    existing_widget.update_original(original_text) or layout_changed
                )
            
            if translated_text:
                layout_changed = (
                    existing_widget.update_translated(
                        translated_text,
                        committed_prefix_length,
                    ) or layout_changed
                )
            existing_widget.set_finalized(finalized)
            if layout_changed:
                self._schedule_content_reflow()
                
        else:
            # Do not resurrect an old delayed final after it was trimmed from
            # the visible 40-row projection.  It remains in transcript_data
            # (or the outer record store) for export.
            if (
                len(self.items) >= MAX_VISIBLE_TRANSCRIPT_ITEMS
                and chunk_id < self.items[0][0]
            ):
                self._apply_item_visibility()
                return
            # Insert new widget in order
            timestamp = self.transcript_data[chunk_id]['timestamp']
            new_widget = LogItem(
                chunk_id,
                timestamp,
                original_text,
                translated_text,
                finalized=self.transcript_data[chunk_id]['finalized'],
                committed_prefix_length=self.transcript_data[chunk_id].get(
                    'committed_prefix_length', 0
                ),
            )
            
            # Find insertion point
            insert_idx = len(self.items)
            for i, (cid, w) in enumerate(self.items):
                if cid > chunk_id:
                    insert_idx = i
                    break
            
            self.items.insert(insert_idx, (chunk_id, new_widget))
            self.container_layout.insertWidget(insert_idx, new_widget)
            # Bound the live widget tree during multi-hour classes. Complete
            # records are persisted independently by SessionTranscriptRecorder.
            self._trim_visible_items()

            # Scroll to bottom
            QTimer.singleShot(10, self._scroll_to_bottom)

        self._apply_item_visibility()

    def _scroll_to_bottom(self):
        if not self._follow_scroll_tail:
            return
        sb = self.scroll_area.verticalScrollBar()
        self._programmatic_scroll = True
        try:
            sb.setValue(sb.maximum())
        finally:
            self._programmatic_scroll = False

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.allow_notch_switch and self.display_mode == "glass":
            switch_action = menu.addAction("切换到物理刘海")
            switch_action.triggered.connect(self.notch_requested.emit)
            menu.addSeparator()
        stop_action = menu.addAction("退出翻译")
        stop_action.triggered.connect(self.stop_requested.emit)
        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        if (
            self.allow_notch_switch
            and self.display_mode == "glass"
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.notch_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # Window Moving Logic (Resize is handled by ResizeHandle widget)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_moving = True
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        # Handle dragging
        if self.is_moving:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()
            
    def mouseReleaseEvent(self, event):
        self.is_moving = False

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
