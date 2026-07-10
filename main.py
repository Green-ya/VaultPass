#!/usr/bin/env python3
"""
VaultPass - GUI менеджер паролей для HashiCorp Vault
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.main_window import MainWindow  # <-- БЕЗ src.

def get_resource_path(relative_path):
    """Получить путь к ресурсу, работает и для dev, и для сборки PyInstaller"""
    try:
        # PyInstaller создаёт временную папку _MEIxxxxx
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VaultPass")
    app.setOrganizationName("VaultPass")
    
    # Устанавливаем иконку приложения
    icon_path = get_resource_path("resources/icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    window = MainWindow()
    window.setWindowTitle("VaultPass - Менеджер паролей")
    
    # Устанавливаем иконку окна
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()