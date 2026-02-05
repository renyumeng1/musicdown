import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from ui.mainui import QQMusicDownloaderGUI
from utils.app_paths import get_resource_path

if __name__ == "__main__":
    # Work around popup positioning issues on some HiDPI / multi-screen setups.
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    theme_path = get_resource_path("ui", "theme.qss")
    if theme_path.exists():
        theme_text = theme_path.read_text(encoding="utf-8")
        ui_dir = theme_path.parent.as_posix()
        theme_text = theme_text.replace('url("icons/', f'url("{ui_dir}/icons/')
        app.setStyleSheet(theme_text)

    window = QQMusicDownloaderGUI()
    window.show()
    sys.exit(app.exec())
