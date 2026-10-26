{
  description = "VaultPass application";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos";
  };

  outputs = { self, nixpkgs, ... }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.callPackage ./vaultpass.nix {};
        }
      );

      # Окружение для разработки (для nix develop / nix-shell)
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = import ./shell.nix { inherit pkgs; };
        }
      );
    };
}
