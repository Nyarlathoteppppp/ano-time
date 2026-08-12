from ui.qt import QtCore, QtWidgets


Qt = QtCore.Qt
QApplication = QtWidgets.QApplication
QComboBox = QtWidgets.QComboBox


class ReadableComboBox(QComboBox):
    """Combo box whose popup fits its longest item without clipping."""

    def addItem(self, text, userData=None):
        super().addItem(text, userData)
        self.setItemData(
            self.count() - 1, str(text), Qt.ItemDataRole.ToolTipRole
        )

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def showPopup(self):
        metrics = self.fontMetrics()
        content_width = max(
            [metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())]
            or [self.width()]
        ) + 56
        screen = self.screen() or QApplication.primaryScreen()
        screen_limit = int(screen.availableGeometry().width() * 0.72) if screen else 760
        self.view().setMinimumWidth(
            max(self.width(), min(content_width, screen_limit, 760))
        )
        super().showPopup()
