import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from ui.mainui import QQMusicDownloaderGUI
from utils.app_paths import get_resource_path
from utils.logger import logger

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
        try:
            theme_text = theme_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read theme file: %s (%s)", theme_path, exc)
        else:
            try:
                icons_url_prefix = (theme_path.parent / "icons").resolve().as_posix()
            except Exception:
                icons_url_prefix = (theme_path.parent / "icons").as_posix()
            theme_text = theme_text.replace('url("icons/', f'url("{icons_url_prefix}/')
            app.setStyleSheet(theme_text)
    else:
        logger.warning(
            "Theme file not found: %s (packaging must include ui/theme.qss and ui/icons/*)",
            theme_path,
        )

    window = QQMusicDownloaderGUI()
    window.show()
    sys.exit(app.exec())
