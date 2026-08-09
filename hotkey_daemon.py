"""Resident macOS global-hotkey agent for Realtime Translator."""

import configparser
import os
import subprocess
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication

from global_shortcut import MacCarbonHotkeyShortcut


ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.ini")
APP_PATH = os.path.expanduser("~/Desktop/Realtime Translator.app")
INSTANCE_SERVER_NAME = "com.realtime-ton.dashboard"


def shortcut_enabled():
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH)
    return parser.getboolean("shortcut", "enabled", fallback=True)


def send_dashboard_command(command=b"toggle"):
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)
    if not socket.waitForConnected(200):
        return False
    socket.write(command)
    sent = socket.waitForBytesWritten(200)
    socket.disconnectFromServer()
    return bool(sent)


class HotkeyAgent:
    def __init__(self):
        self._retries = 0
        self._launch_pending = False
        self.hotkey = MacCarbonHotkeyShortcut(enabled=True)
        self.hotkey.activated.connect(self.activate)

    def start(self):
        if not self.hotkey.start():
            raise RuntimeError("Unable to register Control + S")
        print("[Hotkey Agent] Ready", flush=True)

    def activate(self):
        if not shortcut_enabled():
            return
        if send_dashboard_command():
            print("[Hotkey Agent] Sent toggle", flush=True)
            return
        if self._launch_pending:
            print("[Hotkey Agent] Dashboard launch already pending", flush=True)
            return
        print("[Hotkey Agent] Dashboard absent; opening app", flush=True)
        self._launch_pending = True
        subprocess.Popen(
            ["/usr/bin/open", APP_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._retries = 0
        QTimer.singleShot(350, self._retry_toggle)

    def _retry_toggle(self):
        if send_dashboard_command():
            self._launch_pending = False
            print("[Hotkey Agent] Opened dashboard and sent toggle", flush=True)
            return
        self._retries += 1
        if self._retries < 12:
            QTimer.singleShot(350, self._retry_toggle)
        else:
            self._launch_pending = False
            print("[Hotkey Agent] Dashboard did not become ready", flush=True)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception as exc:
        print(f"[Hotkey Agent] Unable to hide Dock icon: {exc}", flush=True)
    agent = HotkeyAgent()
    agent.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
