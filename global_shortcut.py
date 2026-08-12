import sys
import time
import ctypes

from ui.qt import QObject, Signal


def accessibility_trusted():
    """Return macOS Accessibility trust for the current responsibility chain."""
    if sys.platform != "darwin":
        return True
    try:
        framework = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        framework.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(framework.AXIsProcessTrusted())
    except Exception:
        return False


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
    activated = Signal()

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
            print(
                f"[Shortcut] Accessibility trusted: {accessibility_trusted()}",
                flush=True,
            )
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


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("event_class", ctypes.c_uint32), ("event_kind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("identifier", ctypes.c_uint32)]


def _fourcc(value):
    return int.from_bytes(value.encode("ascii"), "big")


class MacCarbonHotkeyShortcut(QObject):
    """Permission-free macOS global hotkey: Control + S."""

    activated = Signal()

    _KEY_CODE_S = 1
    _CONTROL_KEY = 1 << 12
    _OPTION_KEY = 1 << 11
    _EVENT_CLASS_KEYBOARD = _fourcc("keyb")
    _EVENT_HOTKEY_PRESSED = 6
    _SIGNATURE = _fourcc("RTON")

    def __init__(self, enabled=True, parent=None):
        super().__init__(parent)
        self.enabled = bool(enabled)
        self._carbon = None
        self._handler_callback = None
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()

    @property
    def available(self):
        return sys.platform == "darwin"

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def set_interval(self, _interval_seconds):
        """Compatibility no-op for the retired Double Option setting."""

    def start(self):
        if not self.available or self._hotkey_ref.value:
            return self.available
        try:
            carbon = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/Carbon.framework/Carbon"
            )
            handler_type = ctypes.CFUNCTYPE(
                ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
            )

            def handle_hotkey(_next_handler, _event, _user_data):
                if self.enabled:
                    print("[Shortcut] Activated Control + S", flush=True)
                    self.activated.emit()
                return 0

            self._handler_callback = handler_type(handle_hotkey)
            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            target = carbon.GetApplicationEventTarget()
            event_spec = _EventTypeSpec(
                self._EVENT_CLASS_KEYBOARD, self._EVENT_HOTKEY_PRESSED
            )
            install_status = carbon.InstallEventHandler(
                ctypes.c_void_p(target),
                self._handler_callback,
                1,
                ctypes.byref(event_spec),
                None,
                ctypes.byref(self._handler_ref),
            )
            if install_status != 0:
                raise OSError(f"InstallEventHandler failed: {install_status}")

            hotkey_id = _EventHotKeyID(self._SIGNATURE, 1)
            register_status = carbon.RegisterEventHotKey(
                self._KEY_CODE_S,
                self._CONTROL_KEY,
                hotkey_id,
                ctypes.c_void_p(target),
                0,
                ctypes.byref(self._hotkey_ref),
            )
            if register_status != 0:
                carbon.RemoveEventHandler(self._handler_ref)
                self._handler_ref = ctypes.c_void_p()
                raise OSError(f"RegisterEventHotKey failed: {register_status}")
            self._carbon = carbon
            print("[Shortcut] Registered Control + S via Carbon", flush=True)
            return True
        except Exception as exc:
            print(f"[Shortcut] Could not register native global hotkey: {exc}", flush=True)
            self.stop()
            return False

    def stop(self):
        carbon = self._carbon
        if carbon is not None:
            if self._hotkey_ref.value:
                carbon.UnregisterEventHotKey(self._hotkey_ref)
            if self._handler_ref.value:
                carbon.RemoveEventHandler(self._handler_ref)
        self._hotkey_ref = ctypes.c_void_p()
        self._handler_ref = ctypes.c_void_p()
        self._handler_callback = None
        self._carbon = None
