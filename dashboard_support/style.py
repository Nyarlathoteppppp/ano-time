STYLESHEET = """
QWidget {
    background: transparent;
    color: #cdd6f4;
    font-family: 'Helvetica Neue', Arial, sans-serif;
}
QWidget#DashboardRoot {
    background-color: rgba(255, 184, 211, 128);
}
QWidget#DashboardRoot[fullscreenFallback="true"] {
    background-color: rgba(28, 30, 39, 252);
}
QTabWidget::pane {
    border: 1px solid rgba(255, 214, 229, 72);
    background: rgba(255, 207, 224, 28);
    border-radius: 12px;
}
QTabBar::tab {
    background: rgba(255, 220, 232, 28);
    color: #a6adc8;
    padding: 9px 15px;
    min-height: 56px;
    font-size: 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: rgba(247, 168, 201, 220);
    color: #10131c;
    font-weight: bold;
}
QLabel {
    font-size: 14px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: rgba(255, 224, 235, 30);
    border: 1px solid rgba(255, 207, 225, 70);
    border-radius: 7px;
    padding: 6px;
    color: #cdd6f4;
    selection-background-color: #585b70;
}
QComboBox QAbstractItemView {
    background-color: rgba(28, 32, 44, 245);
    border: 1px solid rgba(255, 255, 255, 45);
    color: #cdd6f4;
    selection-background-color: rgba(137, 180, 250, 190);
    selection-color: #10131c;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 4px 10px;
}
QPushButton {
    background-color: rgba(247, 168, 201, 210);
    color: #10131c;
    border: 1px solid rgba(255, 255, 255, 30);
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: rgba(255, 193, 218, 235);
}
QPushButton#StopButton {
    background-color: #f38ba8;
}
QPushButton#StopButton:hover {
    background-color: #eba0ac;
}
QGroupBox {
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #fab387;
}
"""
