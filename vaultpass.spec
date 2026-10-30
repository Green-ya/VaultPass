# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = os.path.abspath(SPECPATH)

datas = [(os.path.join(PROJECT_ROOT, 'resources'), 'resources')]
binaries = []
hiddenimports = [
    # Локальные модули: без pathex PyInstaller их не видит при сборке
    # через консольный скрипт (cwd не попадает в module search paths).
    'config_manager',
    'logging_setup',
    'resource_utils',
    'vault_client',
    'ui',
    'ui.dialogs',
    'ui.main_window',
    'ui.search_dialog',
]

for package in ('cryptography', 'hvac', 'keyring', 'secretstorage'):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
    except Exception:
        # secretstorage — необязательный backend для keyring
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='vaultpass',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
