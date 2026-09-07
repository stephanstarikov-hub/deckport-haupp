from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QLabel, QPushButton

STYLE = """
QWidget { background: #101b2b; color: #e7f0fa; font-family: 'DejaVu Sans'; font-size: 13px; }
QMainWindow, QDialog { background: #101b2b; }
QLabel#eyebrow { color: #66dcc0; font-size: 12px; font-weight: bold; }
QLabel#title { font-size: 30px; font-weight: bold; }
QLabel#muted { color: #a8b8ca; }
QLabel#status { color: #66dcc0; font-size: 23px; font-weight: bold; padding: 14px 0; }
QFrame#card { background: #18273b; border-radius: 14px; padding: 12px; }
QPushButton { background: #243950; border: 1px solid #36526b; border-radius: 8px; padding: 10px 16px; }
QPushButton:hover { background: #314e69; }
QPushButton:focus { border: 2px solid #76c7ff; }
QPushButton:disabled { color: #8393a4; background: #1b293a; border-color: #263a51; }
QPushButton#primary { background: #66dcc0; color: #0b2330; font-size: 16px; font-weight: bold; padding: 16px; border: none; }
QPushButton#primary:hover { background: #95edd6; }
QPushButton#primary:disabled { background: #355c60; color: #9ab8ba; }
QLineEdit, QComboBox, QListWidget, QTableWidget, QPlainTextEdit { background: #152337; border: 1px solid #304962; border-radius: 7px; padding: 8px; selection-background-color: #306688; }
QHeaderView::section { background: #20334a; padding: 9px; border: none; color: #b8cada; }
QTabWidget::pane { border: none; padding: 10px 0; }
QTabBar::tab { padding: 12px 20px; background: #16263a; }
QTabBar::tab:selected { color: #66dcc0; border-bottom: 3px solid #66dcc0; }
QProgressBar { background: #20344b; border: none; border-radius: 6px; height: 14px; text-align: center; }
QProgressBar::chunk { background: #66dcc0; border-radius: 6px; }
QCheckBox { padding: 6px; }
QMenu { background: #182a40; border: 1px solid #3a5670; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #2d5977; }
"""


def label(text, role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget
