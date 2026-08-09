import sys
import time

from PyQt6.QtCore import QObject, pyqtSignal


class DoubleModifierDetector:
    """Recognize two clean presses of one modifier without consuming keys."""

    def __init__(self, interval_seconds=0.32, cooldown_seconds=0.6, clock=None):
        self.interval_seconds = interval_seconds
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        self._down = False
        self._clean = False
        self._last_release = None
        self._last_activation = float("-inf")

    def set_interval(self, interval_seconds):
        self.interval_seconds = float(interval_seconds)
        self.reset()

    def reset(self):
        self._down = False
        self._clean = False
        self._last_release = None

    def key_down(self):
        if self._down:
            self._clean = False

    def modifier_changed(self, pressed, other_modifiers=False, now=None):
        now = self._clock() if now is None else now
        if pressed:
            if not self._down:
                self._down = True
                self._clean = not other_modifiers
            elif other_modifiers:
                self._clean = False
            return False

        if not self._down:
            return False
        clean_release = self._clean and not other_modifiers
        self._down = False
        self._clean = False
        if not clean_release:
            self._last_release = None
            return False
        if now - self._last_activation < self.cooldown_seconds:
            self._last_release = None
            return False
        if (
            self._last_release is not None
            and now - self._last_release <= self.interval_seconds
        ):
            self._last_release = None
            self._last_activation = now
            return True
        self._last_release = now
        return False


class MacDoubleOptionShortcut(QObject):
    activated = pyqtSignal()

    def __init__(self, enabled=True, interval_seconds=0.32, parent=None):
        super().__init__(parent)
        self.enabled = bool(enabled)
        self.detector = DoubleModifierDetector(interval_seconds=interval_seconds)
        self._global_monitor = None
        self._local_monitor = None
        self._global_handler = None
        self._local_handler = None

    @property
    def available(self):
        return sys.platform == "darwin"

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.detector.reset()

    def set_interval(self, interval_seconds):
        self.detector.set_interval(interval_seconds)

    def start(self):
        if not self.available or self._global_monitor is not None:
            return self.available
        try:
            from AppKit import (
                NSEvent,
                NSEventMaskFlagsChanged,
                NSEventMaskKeyDown,
            )

            mask = NSEventMaskFlagsChanged | NSEventMaskKeyDown
            self._global_handler = lambda event: self._handle_event(event)
            self._local_handler = lambda event: self._handle_local_event(event)
            self._global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, self._global_handler
            )
            self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, self._local_handler
            )
            return self._global_monitor is not None
        except Exception as exc:
            print(f"[Shortcut] Could not install Double Option monitor: {exc}")
            self.stop()
            return False

    def stop(self):
        if not self.available:
            return
        try:
            from AppKit import NSEvent

            for monitor in (self._global_monitor, self._local_monitor):
                if monitor is not None:
                    NSEvent.removeMonitor_(monitor)
        except Exception:
            pass
        self._global_monitor = None
        self._local_monitor = None
        self._global_handler = None
        self._local_handler = None
        self.detector.reset()

    def _handle_local_event(self, event):
        self._handle_event(event)
        return event

    def _handle_event(self, event):
        if not self.enabled:
            return
        try:
            from AppKit import (
                NSEventModifierFlagCapsLock,
                NSEventModifierFlagDeviceIndependentFlagsMask,
                NSEventModifierFlagOption,
                NSEventTypeFlagsChanged,
                NSEventTypeKeyDown,
            )

            event_type = event.type()
            if event_type == NSEventTypeKeyDown:
                self.detector.key_down()
                return
            if event_type != NSEventTypeFlagsChanged:
                return
            flags = int(event.modifierFlags()) & int(
                NSEventModifierFlagDeviceIndependentFlagsMask
            )
            pressed = bool(flags & int(NSEventModifierFlagOption))
            ignored = int(NSEventModifierFlagOption) | int(NSEventModifierFlagCapsLock)
            other_modifiers = bool(flags & ~ignored)
            if self.detector.modifier_changed(pressed, other_modifiers):
                self.activated.emit()
        except Exception as exc:
            print(f"[Shortcut] Event handling failed: {exc}")

