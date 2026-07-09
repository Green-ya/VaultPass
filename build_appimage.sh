#!/bin/bash

# Устанавливаем зависимости
pip install -r requirements.txt

# Собираем с помощью pyinstaller
pyinstaller --name="vault-manager" \
            --windowed \
            --onefile \
            --add-data "src/ui:src/ui" \
            --hidden-import "hvac" \
            --hidden-import "cryptography" \
            src/main.py

# Скачиваем linuxdeploy и appimagetool
# wget -c "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
# wget -c "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
chmod +x linuxdeploy-x86_64.AppImage appimagetool-x86_64.AppImage

# Создаём AppDir
mkdir -p AppDir/usr/bin
cp dist/vault-manager AppDir/usr/bin/
cp resources/icon.png AppDir/
cat > AppDir/vault-manager.desktop << EOF
[Desktop Entry]
Name=Vault Manager
Comment=GUI for HashiCorp Vault
Exec=vault-manager
Icon=icon
Type=Application
Categories=Utility;
EOF

# Собираем AppImage
./linuxdeploy-x86_64.AppImage --appdir AppDir --output appimage
./appimagetool-x86_64.AppImage AppDir