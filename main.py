#!/usr/bin/env python3
"""
VaultPass - GUI менеджер паролей для HashiCorp Vault
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VaultPass")
    app.setOrganizationName("VaultPass")
    # Устанавливаем иконку
    icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.setWindowTitle("VaultPass - Менеджер паролей")
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()