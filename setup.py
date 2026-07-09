from setuptools import setup

setup(
    name="vault-manager",
    version="1.0.0",
    packages=['src', 'src.ui'],
    entry_points={
        'gui_scripts': [
            'vault-manager = src.main:main'
        ]
    },
    install_requires=[
        'PySide6>=6.5.0',
        'hvac>=1.2.0',
        'cryptography>=41.0.0'
    ]
)