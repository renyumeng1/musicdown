import sys
import platform
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QFont
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

    # ── 全局字体：Windows 上使用最接近 macOS 的字体栈 ──
    if platform.system() == "Windows":
        # Windows 11 提供 Segoe UI Variable；Win10 回退 Microsoft YaHei UI
        for candidate in ("Segoe UI Variable", "Microsoft YaHei UI", "Segoe UI"):
            test_font = QFont(candidate)
            if test_font.exactMatch() or test_font.family().lower().startswith(
                candidate.lower()[:6]
            ):
                break
        font = QFont(candidate, 10)  # 10pt ≈ macOS 13px, 比默认 9pt 更舒适
        font.setHintingPreference(
            QFont.HintingPreference.PreferNoHinting
        )  # 减少 hinting 更接近 macOS 渲染
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(font)
    else:
        # macOS / Linux 使用系统默认即可
        font = app.font()
        font.setPointSize(13)
        app.setFont(font)

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
