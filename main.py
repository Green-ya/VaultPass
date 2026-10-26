#!/usr/bin/env python3
"""
VaultPass - GUI менеджер паролей для HashiCorp Vault
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from resource_utils import get_resource_path
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VaultPass")
    # Не задаём display name: некоторые оконные менеджеры добавляют его
    # к заголовку окна, из-за чего VaultPass появлялся дважды.
    app.setApplicationDisplayName("")
    app.setOrganizationName("VaultPass")
    app.setDesktopFileName("vaultpass")

    icon_path = get_resource_path("resources/icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()

    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
