{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    gcc
    python3
    pkg-config
    gnome-keyring
    qt6.wrapQtAppsHook
  ];

  buildInputs = with pkgs; [
    gcr

    (python3.withPackages (ps: with ps; [
      pyside6
      hvac
      cryptography
      keyring
      secretstorage
      pyinstaller
    ]))
  ];

  LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
}
