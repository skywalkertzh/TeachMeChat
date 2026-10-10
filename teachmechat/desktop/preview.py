"""Synthetic desktop preview; never opens user settings or contacts."""
import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication
from .theme import apply_theme
from .window import MainWindow
from ..runtime import configure_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=860)
    parser.add_argument("--settings", action="store_true")
    parser.add_argument("--analysis", action="store_true")
    parser.add_argument("--generating", action="store_true")
    arguments = parser.parse_args()
    runtime = configure_runtime()
    application = QApplication.instance() or QApplication([])
    apply_theme(application)
    window = MainWindow(runtime, demo=True)
    window.resize(arguments.width, arguments.height)
    if arguments.analysis:
        window.tabs.setCurrentIndex(1)
    if arguments.generating:
        window._show_robot("generating", "正在生成建议…")
    window.show()
    application.processEvents()
    widget = window
    if arguments.settings:
        from .dialogs import SettingsDialog
        from ..models import ProviderConfig
        preview_config = ProviderConfig(provider="openai", model="gpt-5.1", api_key="synthetic-preview", reasoning="medium")
        widget = SettingsDialog(preview_config, None, window.options, Path(r"C:\TeachMeChat"), window)
        widget.show()
        application.processEvents()
    output = Path(arguments.output)
    if str(output).startswith(("\\\\", "//")) or not output.is_absolute():
        raise ValueError("Preview output must be a local absolute path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(output))
    widget.close()
    window.close()
    application.processEvents()


if __name__ == "__main__":
    main()
