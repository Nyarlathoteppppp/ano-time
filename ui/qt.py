"""The sole Qt binding boundary for AnoTime's PySide6 runtime.

All application and test code imports Qt through this module. Do not add a
PyQt6 fallback: loading both bindings in one macOS interpreter is unsafe.
"""

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets


QT_BINDING = "PySide6"

Signal = QtCore.Signal
Slot = QtCore.Slot
Property = QtCore.Property

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
