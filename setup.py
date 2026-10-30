from setuptools import find_packages, setup

setup(
    name="vaultpass",
    version="0.2.0",
    description="GUI-менеджер паролей для HashiCorp Vault",
    py_modules=[
        "main",
        "vault_client",
        "config_manager",
        "resource_utils",
        "logging_setup",
    ],
    packages=find_packages(include=["ui", "ui.*"]),
    include_package_data=True,
    data_files=[
        (
            "share/vaultpass",
            ["resources/icon.png", "resources/vaultpass_logo.png"],
        )
    ],
    entry_points={
        "gui_scripts": [
            "vaultpass = main:main",
        ]
    },
    install_requires=[
        "PySide6>=6.5.0",
        "hvac>=1.2.0",
        "cryptography>=41.0.0",
        "keyring>=24.0.0",
    ],
    python_requires=">=3.9",
)
