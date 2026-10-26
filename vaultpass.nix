{ pkgs ? import <nixpkgs> {} }:

pkgs.python3Packages.buildPythonApplication {
  pname = "vaultpass";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  # Зависимости Python, нужные во время работы приложения
  propagatedBuildInputs = with pkgs.python3Packages; [
    pyside6
    hvac
    cryptography
    keyring
    secretstorage
  ];

  # Инструменты сборки (здесь теперь явно указан setuptools для изощренной сборки колеса)
  nativeBuildInputs = with pkgs; [
    gcc
    pkg-config
    qt6.wrapQtAppsHook
    python3Packages.setuptools
  ];

  # Системные библиотеки
  buildInputs = with pkgs; [
    qt6.qtbase
    gcr_4
    gnome-keyring
  ];

  LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
}
