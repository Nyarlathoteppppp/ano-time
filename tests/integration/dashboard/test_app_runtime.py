"""Contract tests for Dashboard single-instance runtime plumbing."""

import unittest
from unittest.mock import patch

from dashboard_support import app_runtime


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self):
        assert self.callback is not None
        self.callback()


class _Socket:
    def __init__(self, connected=True):
        self.connected = connected
        self.writes = []
        self.disconnected = False

    def connectToServer(self, _name):
        pass

    def waitForConnected(self, _timeout):
        return self.connected

    def write(self, payload):
        self.writes.append(payload)

    def waitForBytesWritten(self, _timeout):
        return True

    def disconnectFromServer(self):
        self.disconnected = True


class _Connection:
    def __init__(self, command):
        self.command = command
        self.disconnected = False
        self.deleted = False

    def waitForReadyRead(self, _timeout):
        return True

    def readAll(self):
        return self.command

    def disconnectFromServer(self):
        self.disconnected = True

    def deleteLater(self):
        self.deleted = True


class _Server:
    removed = []

    def __init__(self, listens):
        self.listens = list(listens)
        self.connections = []
        self.newConnection = _Signal()

    def listen(self, _name):
        return self.listens.pop(0)

    @classmethod
    def removeServer(cls, name):
        cls.removed.append(name)

    def hasPendingConnections(self):
        return bool(self.connections)

    def nextPendingConnection(self):
        return self.connections.pop(0)


class _LocalServerFactory:
    """Callable fake preserving QLocalServer's static removeServer API."""

    def __init__(self, server):
        self.server = server

    def __call__(self):
        return self.server

    @staticmethod
    def removeServer(name):
        _Server.removeServer(name)


class AppRuntimeTests(unittest.TestCase):
    def test_notify_existing_instance_sends_command_and_disconnects(self):
        socket = _Socket()
        with patch.object(app_runtime, "QLocalSocket", return_value=socket):
            self.assertTrue(app_runtime.notify_existing_instance(b"toggle"))

        self.assertEqual(socket.writes, [b"toggle"])
        self.assertTrue(socket.disconnected)

    def test_notify_existing_instance_returns_false_without_server(self):
        socket = _Socket(connected=False)
        with patch.object(app_runtime, "QLocalSocket", return_value=socket):
            self.assertFalse(app_runtime.notify_existing_instance())
        self.assertEqual(socket.writes, [])

    def test_stale_server_is_removed_only_when_no_live_instance_answers(self):
        _Server.removed.clear()
        server = _Server([False, True])
        with (
            patch.object(app_runtime, "QLocalServer", _LocalServerFactory(server)),
            patch.object(app_runtime, "notify_existing_instance", return_value=False),
        ):
            result = app_runtime.start_instance_server(lambda: None, lambda: None)

        self.assertIs(result, server)
        self.assertEqual(_Server.removed, [app_runtime.INSTANCE_SERVER_NAME])

    def test_server_dispatches_activate_quit_and_toggle_commands(self):
        server = _Server([True])
        events = []
        with patch.object(app_runtime, "QLocalServer", return_value=server):
            app_runtime.start_instance_server(
                lambda: events.append("activate"),
                lambda: events.append("quit"),
                lambda: events.append("toggle"),
            )

        for command in (b"activate", b"quit", b"toggle"):
            connection = _Connection(command)
            server.connections.append(connection)
            server.newConnection.emit()
            self.assertTrue(connection.disconnected)
            self.assertTrue(connection.deleted)

        self.assertEqual(events, ["activate", "quit", "toggle"])


if __name__ == "__main__":
    unittest.main()
