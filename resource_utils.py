import os
import sys


def get_resource_path(relative_path: str) -> str:
    """Ищет ресурс в dev-режиме, в сборке PyInstaller и при установке пакета."""
    filename = os.path.basename(relative_path)
    here = os.path.dirname(os.path.abspath(__file__))

    candidates = []

    # PyInstaller распаковывает данные во временный каталог _MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, relative_path))

    # Запуск из репозитория
    candidates.append(os.path.join(here, relative_path))
    candidates.append(os.path.join(os.path.dirname(here), relative_path))

    # Установленный пакет (data_files -> share/vaultpass)
    candidates.append(os.path.join(sys.prefix, "share", "vaultpass", filename))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return candidates[0] if candidates else relative_path
