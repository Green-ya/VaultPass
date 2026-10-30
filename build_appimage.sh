#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Устанавливаем зависимости
pip install -r requirements.txt

# Собираем исполняемый файл (spec уже включает ui и resources)
pyinstaller --noconfirm vaultpass.spec

# Проверяем, что локальные модули действительно попали в архив
python - << 'PY'
import sys

from PyInstaller.archive.readers import CArchiveReader

archive = CArchiveReader("dist/vaultpass")
pyz = archive.open_embedded_archive("PYZ.pyz")
required = {"config_manager", "logging_setup", "resource_utils", "vault_client", "ui.main_window"}
missing = required - set(pyz.toc)
if missing:
    sys.exit(f"В сборке отсутствуют модули: {sorted(missing)}")
print("Проверка сборки: локальные модули на месте")
PY

# Готовим AppDir
rm -rf AppDir
mkdir -p AppDir/usr/bin
cp dist/vaultpass AppDir/usr/bin/vaultpass
cp resources/icon.png AppDir/vaultpass.png
cp resources/icon.png AppDir/icon.png

cat > AppDir/vaultpass.desktop << 'EOF'
[Desktop Entry]
Name=VaultPass
Comment=GUI-менеджер паролей для HashiCorp Vault
Exec=vaultpass
Icon=vaultpass
Type=Application
Terminal=false
Categories=Utility;Security;
EOF

cat > AppDir/AppRun << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/vaultpass" "$@"
EOF
chmod +x AppDir/AppRun

# Скачиваем appimagetool, если его нет локально (в репозитории он не хранится)
if [ ! -x appimagetool-x86_64.AppImage ]; then
    echo "Скачиваем appimagetool…"
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    if command -v wget >/dev/null 2>&1; then
        wget -c -O appimagetool-x86_64.AppImage "$URL"
    else
        curl -L -o appimagetool-x86_64.AppImage "$URL"
    fi
fi

chmod +x appimagetool-x86_64.AppImage

# Собираем во временный файл и заменяем атомарно: это позволяет
# пересобирать AppImage, даже если его текущая версия уже запущена.
OUTPUT="VaultPass-x86_64.AppImage"
TMP_OUTPUT="${OUTPUT}.new"
rm -f "$TMP_OUTPUT"
# appimagetool — сам AppImage: без прав на FUSE (частый случай в контейнерах и
# песочницах) монтирование падает. Тогда запускаем его в режиме распаковки.
if ! ARCH=x86_64 ./appimagetool-x86_64.AppImage AppDir "$TMP_OUTPUT"; then
    echo "Прямой запуск appimagetool не удался, пробуем APPIMAGE_EXTRACT_AND_RUN=1…"
    rm -f "$TMP_OUTPUT"
    APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 ./appimagetool-x86_64.AppImage AppDir "$TMP_OUTPUT"
fi
mv -f "$TMP_OUTPUT" "$OUTPUT"
