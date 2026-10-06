# Declarative NixOS-Native InkyPi Architecture Design

- **Author:** Nicho (Pair Programming with Antigravity)
- **Date:** 2026-10-06
- **Status:** Approved / Spec Review
- **Target Systems:**
  - InkyPi Core Repository (Python 3.11+, Flask, Pillow)
  - `glacio` (AMD Ryzen 7 7840HS, NixOS 26.11 Flake, hostapd virtual AP `ap0`)
  - Remote PhotoFrame Clients (Seeed XIAO EE02 / Spectra 6)

---

## 1. Executive Summary

This specification defines the architecture for transforming the InkyPi e-paper server into a fully declarative, NixOS-native application. Currently, InkyPi relies on imperative file mutations within its working directory (writing to `src/config/device.json` and `.env`), assumes hardcoded relative paths for generated assets (`src/static/images/current_image.png`), and hardcodes its plugin directory to `src/plugins/`.

To make InkyPi clean and reproducible under NixOS:
1. **Clean Path Separation:** Separate immutable configuration (stored in `/nix/store/...`), reproducible code and plugins (stored in `/nix/store/...`), and mutable runtime state (stored in `/var/lib/inkypi`).
2. **Declarative Mode:** InkyPi accepts a `--declarative` flag. When enabled, configuration mutation endpoints are protected/disabled, a notification banner indicates declarative management in the Web UI, and active runtime controls (preview, manual refresh, next-refresh countdown, battery/photoframe telemetry) remain fully operational.
3. **Dynamic Plugin & Blueprint Support:** External plugins can be supplied via an external search path (`INKYPI_PLUGIN_PATH`), and plugins with web routes (such as community plugin managers or custom dashboards) are automatically registered with Flask via a generic `register_plugin_blueprints` hook.
4. **First-Class Nix Flake & Module:** InkyPi exposes a `flake.nix` providing `packages.default` and `nixosModules.default` (`services.inkypi`), supporting declarative `settings = { ... }`, `extraPlugins = [ ... ]`, `extraPythonPackages = ps: [ ... ]`, and secret injection via `environmentFile` (agenix).

---

## 2. Constraints & Principles

1. **Nix Store Immutability:** `/nix/store` paths are strictly read-only. InkyPi must never attempt to write to its package root, source directory, or static folder when running under NixOS.
2. **Backwards Compatibility:** Standalone developer workflows (`python src/inkypi.py --dev`) on non-NixOS machines must continue to work without requiring external flags or breaking existing developer scripts.
3. **Secret Security (agenix):** InkyPi must not require a plain `.env` file on disk. Injected environment variables from systemd's `EnvironmentFile` must take precedence.
4. **Third-Party Plugin Isolation:** Third-party plugins must not require modifying the core InkyPi codebase or copying files into `src/plugins/`.
5. **No Broken Web UI:** Users visiting the web interface should have a crystal-clear understanding that configuration is declarative, without crashing or misleading "Save" operations that reset on reboot.

---

## 3. Core Python Architecture & Path Resolution

### 3.1 CLI Arguments & Environment Overrides (`src/inkypi.py`)

InkyPi's argument parser is extended to support declarative execution and runtime path overrides:

| Flag | Environment Variable | Default | Description |
|---|---|---|---|
| `--config-file <path>` | `INKYPI_CONFIG` | `src/config/device.json` (or `device_dev.json` if `--dev`) | Absolute path to the device JSON configuration. |
| `--state-dir <path>` | `INKYPI_STATE_DIR` | `<repo_root>/src` | Directory for mutable runtime assets (`current_image.png`, plugin cache, saved images). |
| `--plugin-path <paths>` | `INKYPI_PLUGIN_PATH` | `""` | Colon-separated list of additional directories containing plugins. |
| `--declarative` | `INKYPI_DECLARATIVE` | `False` | Enables declarative mode (read-only configuration UI + API protection). |
| `--port <int>` | `PORT` | `80` (or `8080` if `--dev`) | Listening port. |
| `--host <str>` | `HOST` | `"0.0.0.0"` | Listening host address. |

### 3.2 Configuration Manager (`src/config.py`)

* **Initialization:**
  * `Config.config_file` is initialized from the CLI `--config-file` or `INKYPI_CONFIG`.
  * `Config.state_dir` is initialized from the CLI `--state-dir` or `INKYPI_STATE_DIR`.
  * `Config.current_image_file = os.path.join(self.state_dir, "images", "current_image.png")`.
  * `Config.plugin_image_dir = os.path.join(self.state_dir, "images", "plugins")`.
  * `Config.declarative_mode = bool(args.declarative or os.getenv("INKYPI_DECLARATIVE"))`.
  * Ensures runtime state directories exist on boot:
    ```python
    os.makedirs(os.path.dirname(self.current_image_file), exist_ok=True)
    os.makedirs(self.plugin_image_dir, exist_ok=True)
    ```
* **Write Protection:**
  * When `declarative_mode` is True:
    ```python
    def write_config(self):
        if self.declarative_mode:
            logger.debug("Declarative mode active: skipping disk write to config_file")
            return
        # Standard file write logic
    ```
* **Secrets Precedence:**
  * `Config.load_env_key(key)` checks `os.getenv(key)` first. If present, returns it immediately without touching `.env`. If absent, falls back to `dotenv.load_dotenv()` for legacy local development.

### 3.3 Dynamic Plugin & Blueprint Discovery (`src/plugins/plugin_registry.py`)

* **Multi-Directory Plugin Search:**
  * `load_plugins()` searches both the built-in `src/plugins/` directory and any directories defined in `INKYPI_PLUGIN_PATH` (split on `:`).
  * Plugin discovery merges metadata: `plugin-info.json` is read from any discovered plugin folder.
* **Generic Blueprint Registration:**
  * A function `register_plugin_blueprints(app)` is exposed in `plugin_registry.py`:
    ```python
    def register_plugin_blueprints(app):
        for plugin_id, plugin_instance in PLUGIN_CLASSES.items():
            try:
                if hasattr(plugin_instance, "get_blueprint"):
                    bp = plugin_instance.get_blueprint()
                    if bp:
                        app.register_blueprint(bp)
                        logger.info(f"Registered custom blueprint for plugin '{plugin_id}'")
            except Exception as e:
                logger.warning(f"Failed to register blueprint for plugin '{plugin_id}': {e}")
    ```
  * `src/inkypi.py` calls `register_plugin_blueprints(app)` immediately after registering core blueprints, before `waitress.serve()` starts.

### 3.4 Static File & Current Image Serving

* When `--state-dir` is passed, `current_image.png` resides outside `src/static/images/`.
* `src/blueprints/main.py` and `src/blueprints/photoframe.py`:
  * Route requests for `/static/images/current_image.png` to `Config.current_image_file` using Flask's `send_from_directory` with `Config.state_dir / "images"`.
  * Fallback to default startup image in `src/static/images/default.png` if `current_image.png` has not yet been rendered.

---

## 4. Declarative Web UI & Control Behavior

### 4.1 UI Indicators
* A Flask context processor injects `is_declarative = Config.declarative_mode` into all Jinja2 templates.
* In `src/templates/settings.html`, `src/templates/playlist.html`, `src/templates/plugin.html`, and `src/templates/apikeys.html`:
  * A clear notice is displayed:
    ```html
    {% if is_declarative %}
    <div class="alert alert-info">
      <strong>Declarative Mode:</strong> Configuration is managed via NixOS. Settings on this page are read-only.
    </div>
    {% endif %}
    ```
  * Mutation buttons (Save Settings, Add to Playlist, Delete Playlist, Save API Keys) are hidden or rendered disabled when `is_declarative` is True.

### 4.2 API Mutation Protection
* In `src/blueprints/settings.py`, `src/blueprints/playlist.py`, `src/blueprints/plugin.py`, and `src/blueprints/apikeys.py`:
  * Mutation routes (e.g. `POST /settings/save`, `POST /playlist/add`, `POST /api-keys/save`) check `current_app.config["DECLARATIVE_MODE"]`.
  * If enabled, requests return:
    ```json
    HTTP 403 Forbidden
    {
      "success": false,
      "error": "InkyPi is running in declarative mode. Modify configuration via NixOS."
    }
    ```

### 4.3 Active Controls
* **Homepage (`/`):** Displays live image preview, current plugin name, next refresh countdown.
* **Manual Refresh (`POST /api/refresh`):** Completely functional. Triggers `refresh_task.trigger_refresh()`, renders the next image, updates `current_image.png`, and notifies or logs the refresh.
* **Status Dashboard (`GET /api/status`, `GET /api/photoframe/status`):** Reports remote photoframe battery level, voltage, last seen timestamp, RSSI, and image hash in real time.

---

## 5. Nix Flake & Module Architecture

### 5.1 Repository Flake (`flake.nix`)

The InkyPi repository includes a `flake.nix` exposing:
1. `packages.${system}.default`:
   * Builds InkyPi using `pkgs.python3Packages.buildPythonApplication`.
   * Bundles all runtime Python libraries (`flask`, `pillow`, `waitress`, `pytz`, `recurring-ical-events`, `icalendar`, `feedparser`, `astral`, `numpy`, `psutil`, `python-dotenv`, `requests`).
   * Installs application source into `$out/lib/inkypi` with an executable wrapper `bin/inkypi`.
2. `nixosModules.default`:
   * NixOS module defining `services.inkypi`.

### 5.2 Module Options Schema (`services.inkypi`)

```nix
options.services.inkypi = {
  enable = lib.mkEnableOption "InkyPi E-Paper Image Server";

  package = lib.mkOption {
    type = lib.types.package;
    default = self.packages.${pkgs.system}.default;
    description = "InkyPi package to use.";
  };

  port = lib.mkOption {
    type = lib.types.port;
    default = 8085;
    description = "Port to listen on.";
  };

  host = lib.mkOption {
    type = lib.types.str;
    default = "0.0.0.0";
    description = "Host address to bind to.";
  };

  stateDir = lib.mkOption {
    type = lib.types.str;
    default = "/var/lib/inkypi";
    description = "State directory for rendered images and runtime cache.";
  };

  user = lib.mkOption {
    type = lib.types.str;
    default = "inkypi";
    description = "User to run InkyPi service as.";
  };

  group = lib.mkOption {
    type = lib.types.str;
    default = "inkypi";
    description = "Group to run InkyPi service as.";
  };

  environmentFile = lib.mkOption {
    type = lib.types.nullOr lib.types.path;
    default = null;
    description = "Path to environment file (agenix/sops-nix) containing secrets & API keys.";
  };

  extraPlugins = lib.mkOption {
    type = lib.types.listOf lib.types.path;
    default = [ ];
    description = "List of paths or derivations containing external InkyPi plugins.";
  };

  extraPythonPackages = lib.mkOption {
    type = lib.types.functionTo (lib.types.listOf lib.types.package);
    default = ps: [ ];
    description = "Function returning extra Python packages required by community plugins.";
  };

  settings = lib.mkOption {
    type = lib.types.attrsOf lib.types.anything;
    default = { };
    description = "Declarative InkyPi device configuration matching device.json schema.";
  };
};
```

### 5.3 Systemd Service Generation

The module generates:
1. **Device Config in Store:**
   ```nix
   configFile = pkgs.writeText "inkypi-device.json" (builtins.toJSON cfg.settings);
   ```
2. **Composite Python Environment:**
   ```nix
   pythonEnv = pkgs.python3.withPackages (ps: 
     (cfg.package.requiredPythonModules ps) ++ (cfg.extraPythonPackages ps)
   );
   ```
3. **Plugin Path Composition:**
   Combines `cfg.extraPlugins` into a colon-separated string passed via `--plugin-path`.
4. **Service Definition:**
   ```nix
   systemd.services.inkypi = {
     description = "InkyPi E-Paper Image Server";
     after = [ "network.target" ];
     wantedBy = [ "multi-user.target" ];

     serviceConfig = {
       Type = "simple";
       User = cfg.user;
       Group = cfg.group;
       StateDirectory = "inkypi";
       EnvironmentFile = lib.optional (cfg.environmentFile != null) cfg.environmentFile;
       ExecStart = "${cfg.package}/bin/inkypi "
         + "--config-file ${configFile} "
         + "--state-dir ${cfg.stateDir} "
         + "--port ${toString cfg.port} "
         + "--host ${cfg.host} "
         + "--declarative "
         + (lib.optionalString (cfg.extraPlugins != [ ]) "--plugin-path ${lib.concatStringsSep ":" cfg.extraPlugins}");
       Restart = "always";
       RestartSec = "5s";
     };
   };
   ```

---

## 6. Integration on Host `glacio`

### 6.1 Flake Inputs (`/etc/nixos/flake.nix`)

```nix
inputs = {
  ...
  inkypi.url = "github:npontious/InkyPi";
  inkypi.inputs.nixpkgs.follows = "nixpkgs";
};

outputs = { self, nixpkgs, inkypi, ... }@inputs: {
  nixosConfigurations.glacio = nixpkgs.lib.nixosSystem {
    specialArgs = { inherit inkypi ...; };
    ...
  };
};
```

### 6.2 Host Module (`/etc/nixos/modules/inkypi.nix`)

Cleanly imports the flake's NixOS module and exposes it under `mySystem.services.inkypi`:

```nix
{ config, lib, pkgs, inkypi, ... }:

let
  cfg = config.mySystem.services.inkypi;
in
{
  imports = [ inkypi.nixosModules.default ];

  options.mySystem.services.inkypi = {
    enable = lib.mkEnableOption "InkyPi E-Paper Service";
    port = lib.mkOption { type = lib.types.port; default = 8085; };
    settings = lib.mkOption { type = lib.types.attrsOf lib.types.anything; default = { }; };
    extraPlugins = lib.mkOption { type = lib.types.listOf lib.types.path; default = [ ]; };
    extraPythonPackages = lib.mkOption { default = ps: [ ]; };
    environmentFile = lib.mkOption { type = lib.types.nullOr lib.types.path; default = null; };
  };

  config = lib.mkIf cfg.enable {
    services.inkypi = {
      enable = true;
      port = cfg.port;
      settings = cfg.settings;
      extraPlugins = cfg.extraPlugins;
      extraPythonPackages = cfg.extraPythonPackages;
      environmentFile = cfg.environmentFile;
    };
  };
}
```

### 6.3 Host Configuration (`/etc/nixos/hosts/glacio/configuration.nix`)

```nix
mySystem.services.inkypi = {
  enable = true;
  port = 8085;
  settings = {
    device_name = "Glacio PhotoFrame";
    display_type = "photoframe";
    model = "waveshare_13_3";
    resolution = [ 1600 1200 ];
    orientation = 0;
    playlist_config = {
      playlists = [
        {
          name = "Default";
          plugins = [
            {
              id = "wpotd";
              refresh_settings = { interval = 60; unit = "minutes"; };
            }
          ];
        }
      ];
    };
  };
};
```

---

## 7. Testing & Verification Plan

### 7.1 Python Unit & Functional Tests (pytest)
* `tests/test_config.py`:
  * Test `--config-file` loads arbitrary paths.
  * Test `--state-dir` properly sets image save locations.
  * Test `write_config()` is a no-op when `declarative_mode=True`.
  * Test `load_env_key()` returns `os.environ` variables without reading `.env`.
* `tests/test_plugin_registry.py`:
  * Test multi-path plugin scanning with mock external directories.
  * Test `register_plugin_blueprints()` registers custom routes from plugin classes implementing `get_blueprint()`.
* `tests/test_declarative_web.py`:
  * Test `POST /settings/save`, `POST /playlist/add`, `POST /api-keys/save` return HTTP 403 when `--declarative` is set.
  * Test `GET /` (home), `POST /api/refresh` (manual trigger), and `GET /api/photoframe/status` succeed with HTTP 200.

### 7.2 Nix Flake Verification
* Run `nix flake check` in the repository.
* Run `nix build .#default` to verify package compilation and dependency closure.
* Test CLI invocation: `result/bin/inkypi --help`.

### 7.3 Live End-to-End Verification on `glacio`
* Run `nixos-rebuild switch --flake /etc/nixos#glacio`.
* Verify `systemctl status inkypi` reports active running from `/nix/store`.
* Inspect `curl -s http://localhost:8085/api/photoframe/status` to confirm status reporting.
* Verify `curl -s http://localhost:8085/api/photoframe/image` returns rendered image.
* Verify Web UI at `http://100.85.234.127:8085` displays the declarative banner with working manual refresh controls.
