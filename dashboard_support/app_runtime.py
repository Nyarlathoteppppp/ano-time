import sys
import time

from ui.qt import QtCore, QtNetwork, QtWidgets


QTimer = QtCore.QTimer
QLocalServer = QtNetwork.QLocalServer
QLocalSocket = QtNetwork.QLocalSocket
QApplication = QtWidgets.QApplication
QMessageBox = QtWidgets.QMessageBox


INSTANCE_SERVER_NAME = "com.realtime-ton.dashboard"


def notify_existing_instance(command=b"activate"):
    """Send a command to the running Dashboard process."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)
    if not socket.waitForConnected(250):
        return False
    socket.write(command)
    socket.waitForBytesWritten(250)
    socket.disconnectFromServer()
    return True


def start_instance_server(on_activate, on_quit, on_toggle=None):
    """Own the process-wide singleton socket, recovering stale socket files."""
    server = QLocalServer()
    if not server.listen(INSTANCE_SERVER_NAME):
        if notify_existing_instance():
            return None
        QLocalServer.removeServer(INSTANCE_SERVER_NAME)
        if not server.listen(INSTANCE_SERVER_NAME):
            return None

    def accept_connections():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.waitForReadyRead(100)
            command = bytes(connection.readAll()).strip()
            if command == b"quit":
                on_quit()
            elif command == b"toggle" and on_toggle is not None:
                on_toggle()
            else:
                on_activate()
            connection.disconnectFromServer()
            connection.deleteLater()

    server.newConnection.connect(accept_connections)
    return server


def run_dashboard(dashboard_factory, config):
    def exception_hook(exctype, value, traceback_obj):
        import traceback

        traceback_str = "".join(traceback.format_tb(traceback_obj))
        error_msg = f"Unhandled Exception: {value}\n\n{traceback_str}"
        print(error_msg)
        if QApplication.instance():
            QMessageBox.critical(None, "Crash", error_msg)
        sys.exit(1)

    sys.excepthook = exception_hook
    app = QApplication(sys.argv)
    from app_identity import apply_app_identity

    apply_app_identity(app)
    app.setQuitOnLastWindowClosed(False)
    if "--quit-existing" in sys.argv:
        return 0 if notify_existing_instance(b"quit") else 1
    if notify_existing_instance():
        return 0

    window = dashboard_factory()

    def activate_dashboard():
        from runtime_log import log_stage

        started = time.perf_counter()
        previous_state = "minimized" if window.isMinimized() else "visible"
        window.showNormal()
        window.raise_()
        window.activateWindow()
        QTimer.singleShot(
            0,
            lambda: log_stage(
                "dashboard_restore",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                previous_state=previous_state,
                session_state=window._session_state,
            ),
        )

    # Keep this local alive for the entire event loop. Dropping the final
    # Python reference can destroy the native server while the app is running.
    instance_server = start_instance_server(
        activate_dashboard,
        window.request_full_quit,
        window.on_global_shortcut,
    )
    if instance_server is None:
        notify_existing_instance()
        return 0
    from runtime_log import begin_runtime_session

    begin_runtime_session(reset=True, enabled=config.diagnostics_enabled)
    window.show()
    return app.exec()
