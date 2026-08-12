"""The only Qt binding import boundary during the PySide6 migration.

This migration worktree deliberately still maps to PyQt6 so it can exercise
small source batches against the stable application.  It never imports both
bindings.  Once every active UI dependency has crossed this boundary, this
file is switched atomically to PySide6 and PyQt6 is removed from that release.
"""

from PyQt6 import QtCore, QtGui, QtNetwork, QtWidgets


QT_BINDING = "PyQt6"

Signal = QtCore.pyqtSignal
Slot = QtCore.pyqtSlot
Property = QtCore.pyqtProperty

QObject = QtCore.QObject
QThread = QtCore.QThread
QTimer = QtCore.QTimer
QIcon = QtGui.QIcon


__all__ = [
    "QT_BINDING",
    "Property",
    "QIcon",
    "QObject",
    "QThread",
    "QTimer",
    "QtCore",
    "QtGui",
    "QtNetwork",
    "QtWidgets",
    "Signal",
    "Slot",
]
