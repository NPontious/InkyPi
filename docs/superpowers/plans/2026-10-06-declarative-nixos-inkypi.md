# Declarative NixOS-Native InkyPi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform InkyPi into a fully declarative, NixOS-native application by cleanly separating immutable configuration from mutable state, adding external plugin search paths with automatic blueprint registration, protecting declarative web endpoints, and publishing a first-class Nix flake and NixOS module.

**Architecture:** Core Python classes (`Config`, `app_utils`, `plugin_registry`) are extended to accept `--config-file`, `--state-dir`, `--plugin-path`, and `--declarative` CLI flags and environment variables. Mutable runtime assets (`current_image.png`, cache) are redirected to `state-dir` while configuration is read-only from `/nix/store`. InkyPi's `flake.nix` exposes `packages.default` and `nixosModules.default` with typed options (`settings`, `extraPlugins`, `extraPythonPackages`, `environmentFile`).

**Tech Stack:** Python 3.11+ / Python 3.14, Flask, Waitress, Pillow, Nix Flakes, NixOS Modules, systemd, pytest.

**Spec:** [docs/superpowers/specs/2026-10-06-declarative-nixos-inkypi-design.md](file:///home/nicho/Documents/GitHub/InkyPi/docs/superpowers/specs/2026-10-06-declarative-nixos-inkypi-design.md)

## Global Constraints

- Never write to `/nix/store` or the Python package source directory at runtime; all dynamic assets belong in `state_dir`.
- Backwards compatibility must be preserved: running `python src/inkypi.py --dev` without extra flags must continue to function out of the box.
- Secret injection via `os.environ` (from systemd `EnvironmentFile` / agenix) must take precedence over `.env` files without requiring `.env` on disk.
- Web UI in declarative mode must reject mutations with HTTP 403 while keeping manual refresh, live preview, and telemetry active.
- Flake must be self-contained and evaluate cleanly with `nix flake check`.

## Review Focus

1. **State Directory Missing:** If `--state-dir` points to a path where `images/` or `images/plugins/` does not yet exist, InkyPi must create parent directories without crashing.
2. **Read-Only Config Write Attempt:** When `declarative_mode` is active, any internal call to `write_config()` must safely log and return without raising `OSError: [Errno 30] Read-only file system`.
3. **Missing `.env` File with Injected Env Vars:** When running in systemd with `EnvironmentFile`, no `.env` file exists on disk; `load_env_key()` must resolve environment variables directly from `os.environ` without throwing errors.
4. **Third-Party Plugin Isolation:** Third-party plugins located outside `src/plugins/` must import correctly, find their assets, and register blueprints via `register_plugin_blueprints()`.
5. **Mutation Endpoint Protection:** Direct POST/PUT requests to `/settings/save`, `/playlist/add`, and `/api-keys/save` in declarative mode must return HTTP 403 Forbidden with a clear error payload.

---

### Task 1: Core Path & State Separation

**Files:**
- Modify: `src/config.py`
- Modify: `src/utils/app_utils.py`
- Modify: `src/inkypi.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: CLI args `--config-file`, `--state-dir`, `--declarative` and environment variables `INKYPI_CONFIG`, `INKYPI_STATE_DIR`, `INKYPI_DECLARATIVE`.
- Produces: `Config.config_file`, `Config.state_dir`, `Config.current_image_file`, `Config.plugin_image_dir`, `Config.declarative_mode`. Safe no-op `write_config()`.

- [ ] **Step 1: Write failing tests for Config state separation and declarative protection**

Create `tests/test_config.py`:
```python
import os
import json
import pytest
from config import Config


def test_config_custom_paths(tmp_path):
    config_data = {
        "device_name": "Test Frame",
        "display_type": "photoframe",
        "model": "waveshare_13_3",
        "resolution": [1600, 1200],
        "orientation": 0,
        "playlist_config": {"playlists": []},
        "refresh_info": {}
    }
    config_file = tmp_path / "custom_device.json"
    config_file.write_text(json.dumps(config_data))

    state_dir = tmp_path / "state"

    cfg = Config(config_file=str(config_file), state_dir=str(state_dir), declarative_mode=True)

    assert cfg.config_file == str(config_file)
    assert cfg.state_dir == str(state_dir)
    assert cfg.current_image_file == str(state_dir / "images" / "current_image.png")
    assert cfg.plugin_image_dir == str(state_dir / "images" / "plugins")
    assert cfg.declarative_mode is True
    assert (state_dir / "images" / "plugins").is_dir()


def test_config_declarative_write_noop(tmp_path):
    config_data = {
        "device_name": "Test Frame",
        "playlist_config": {"playlists": []},
        "refresh_info": {}
    }
    config_file = tmp_path / "readonly_device.json"
    config_file.write_text(json.dumps(config_data))
    # Make file read-only
    os.chmod(config_file, 0o444)

    state_dir = tmp_path / "state"

    cfg = Config(config_file=str(config_file), state_dir=str(state_dir), declarative_mode=True)
    cfg.update_value("device_name", "Should Not Persist", write=True)

    # Re-read from disk to ensure disk was untouched
    with open(config_file) as f:
        disk_data = json.load(f)
    assert disk_data["device_name"] == "Test Frame"


def test_config_env_key_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_API_KEY", "secret_from_env")
    cfg = Config(state_dir=str(tmp_path))
    assert cfg.load_env_key("TEST_API_KEY") == "secret_from_env"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest tests/test_config.py -v"`
Expected: FAIL (`TypeError: Config.__init__() got unexpected keyword argument` or similar).

- [ ] **Step 3: Implement path separation and declarative mode in `Config` and `inkypi.py`**

In `src/config.py`:
Update `Config.__init__` to accept `config_file=None`, `state_dir=None`, `declarative_mode=None`, falling back to environment variables (`INKYPI_CONFIG`, `INKYPI_STATE_DIR`, `INKYPI_DECLARATIVE`) and class defaults:
```python
class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(BASE_DIR, "config", "device.json")
    state_dir = BASE_DIR
    current_image_file = os.path.join(BASE_DIR, "static", "images", "current_image.png")
    plugin_image_dir = os.path.join(BASE_DIR, "static", "images", "plugins")
    declarative_mode = False

    def __init__(self, config_file=None, state_dir=None, declarative_mode=None):
        if config_file is not None:
            self.config_file = config_file
        elif os.getenv("INKYPI_CONFIG"):
            self.config_file = os.getenv("INKYPI_CONFIG")

        if state_dir is not None:
            self.state_dir = state_dir
        elif os.getenv("INKYPI_STATE_DIR"):
            self.state_dir = os.getenv("INKYPI_STATE_DIR")

        if declarative_mode is not None:
            self.declarative_mode = declarative_mode
        elif os.getenv("INKYPI_DECLARATIVE"):
            self.declarative_mode = os.getenv("INKYPI_DECLARATIVE").lower() in ("1", "true", "yes")

        # Resolve image paths relative to state_dir
        if self.state_dir != self.BASE_DIR:
            self.current_image_file = os.path.join(self.state_dir, "images", "current_image.png")
            self.plugin_image_dir = os.path.join(self.state_dir, "images", "plugins")

        # Ensure state directories exist
        os.makedirs(os.path.dirname(self.current_image_file), exist_ok=True)
        os.makedirs(self.plugin_image_dir, exist_ok=True)

        self.config = self.read_config()
        self.plugins_list = self.read_plugins_list()
        self.playlist_manager = self.load_playlist_manager()
        self.refresh_info = self.load_refresh_info()

    def write_config(self):
        """Updates the cached config from the model objects and writes to the config file."""
        if self.declarative_mode:
            logger.debug("Declarative mode active: skipping disk write to config_file")
            return

        logger.debug(f"Writing device config to {self.config_file}")
        self.update_value("playlist_config", self.playlist_manager.to_dict())
        self.update_value("refresh_info", self.refresh_info.to_dict())
        with open(self.config_file, 'w') as outfile:
            json.dump(self.config, outfile, indent=4)

    def load_env_key(self, key):
        """Loads an environment variable using os.environ first, falling back to dotenv."""
        val = os.getenv(key)
        if val is not None:
            return val
        load_dotenv(override=True)
        return os.getenv(key)
```

In `src/inkypi.py`:
Add CLI parser options:
```python
parser.add_argument('--config-file', type=str, default=None, help='Path to configuration JSON file')
parser.add_argument('--state-dir', type=str, default=None, help='Directory for runtime state and images')
parser.add_argument('--declarative', action='store_true', help='Run in declarative read-only configuration mode')
```
And propagate them to `Config`:
```python
if args.config_file:
    Config.config_file = args.config_file
elif args.dev:
    Config.config_file = os.path.join(Config.BASE_DIR, "config", "device_dev.json")

if args.state_dir:
    Config.state_dir = args.state_dir

if args.declarative:
    Config.declarative_mode = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest tests/test_config.py -v"`
Expected: PASS (3/3 passed).

- [ ] **Step 5: Commit changes**

```bash
git add src/config.py src/inkypi.py tests/test_config.py
git commit -m "feat: add state directory and declarative mode support to Config"
```

---

### Task 2: Dynamic Plugin Discovery & Generic Blueprint Registration

**Files:**
- Modify: `src/plugins/plugin_registry.py`
- Modify: `src/inkypi.py`
- Create: `tests/test_plugin_registry.py`

**Interfaces:**
- Consumes: `INKYPI_PLUGIN_PATH` (colon-separated list) or `--plugin-path`.
- Produces: `load_plugins()` searching extra paths; `register_plugin_blueprints(app)`.

- [ ] **Step 1: Write failing test for external plugin loading and generic blueprint registration**

Create `tests/test_plugin_registry.py`:
```python
import os
import sys
import json
import pytest
from flask import Flask, Blueprint
from plugins.plugin_registry import load_plugins, register_plugin_blueprints, PLUGIN_CLASSES


def test_external_plugin_discovery_and_blueprints(tmp_path, monkeypatch):
    # Create external plugin directory
    ext_dir = tmp_path / "extra_plugins"
    ext_dir.mkdir()
    plugin_dir = ext_dir / "custom_addon"
    plugin_dir.mkdir()

    # plugin-info.json
    info = {
        "id": "custom_addon",
        "display_name": "Custom Addon",
        "class": "CustomAddonPlugin"
    }
    (plugin_dir / "plugin-info.json").write_text(json.dumps(info))

    # custom_addon.py
    code = """
from flask import Blueprint

bp = Blueprint("custom_addon_bp", __name__)

@bp.route("/api/custom_addon/hello")
def hello():
    return {"status": "ok"}

class CustomAddonPlugin:
    def __init__(self, config):
        self.config = config

    @classmethod
    def get_blueprint(cls):
        return bp
"""
    (plugin_dir / "custom_addon.py").write_text(code)

    # Set plugin path
    monkeypatch.setenv("INKYPI_PLUGIN_PATH", str(ext_dir))

    # Load plugins
    plugins_config = [{"id": "custom_addon", "class": "CustomAddonPlugin"}]
    load_plugins(plugins_config)

    assert "custom_addon" in PLUGIN_CLASSES

    # Verify blueprint registration
    app = Flask(__name__)
    register_plugin_blueprints(app)

    client = app.test_client()
    resp = client.get("/api/custom_addon/hello")
    assert resp.status_code == 200
    assert resp.json == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest tests/test_plugin_registry.py -v"`
Expected: FAIL (`ImportError` or `register_plugin_blueprints` not defined).

- [ ] **Step 3: Implement multi-path plugin scanning and `register_plugin_blueprints`**

In `src/plugins/plugin_registry.py`:
```python
import os
import sys
import importlib
import logging
from pathlib import Path
from utils.app_utils import resolve_path

logger = logging.getLogger(__name__)
PLUGINS_DIR = 'plugins'
PLUGIN_CLASSES = {}


def get_plugin_search_paths():
    """Returns list of Path directories to search for plugins."""
    paths = [Path(resolve_path(PLUGINS_DIR))]
    extra_paths = os.getenv("INKYPI_PLUGIN_PATH", "")
    if extra_paths:
        for p in extra_paths.split(":"):
            clean_p = p.strip()
            if clean_p and os.path.isdir(clean_p):
                paths.append(Path(clean_p))
    return paths


def load_plugins(plugins_config):
    search_paths = get_plugin_search_paths()

    # Add extra plugin search paths to sys.path so modules can be imported
    for p in search_paths:
        str_p = str(p)
        if str_p not in sys.path:
            sys.path.insert(0, str_p)

    for plugin in plugins_config:
        plugin_id = plugin.get('id')
        if plugin.get("disabled", False):
            logger.info(f"Plugin {plugin_id} is disabled, skipping.")
            continue

        plugin_dir = None
        module_path = None
        is_builtin = False

        for base_path in search_paths:
            candidate_dir = base_path / plugin_id
            candidate_file = candidate_dir / f"{plugin_id}.py"
            if candidate_dir.is_dir() and candidate_file.is_file():
                plugin_dir = candidate_dir
                module_path = candidate_file
                if base_path == Path(resolve_path(PLUGINS_DIR)):
                    is_builtin = True
                break

        if not plugin_dir or not module_path:
            logger.error(f"Could not find plugin directory or module for '{plugin_id}', skipping.")
            continue

        try:
            if is_builtin:
                module_name = f"plugins.{plugin_id}.{plugin_id}"
                module = importlib.import_module(module_name)
            else:
                spec = importlib.util.spec_from_file_location(plugin_id, module_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[plugin_id] = module
                spec.loader.exec_module(module)

            plugin_class = getattr(module, plugin.get("class"), None)
            if plugin_class:
                PLUGIN_CLASSES[plugin_id] = plugin_class(plugin)
                logger.info(f"Loaded plugin '{plugin_id}' successfully.")

        except Exception as e:
            logger.error(f"Failed to import plugin module '{plugin_id}': {e}", exc_info=True)


def register_plugin_blueprints(app):
    """Registers Flask blueprints exposed by plugins via get_blueprint()."""
    for plugin_id, plugin_instance in PLUGIN_CLASSES.items():
        try:
            if hasattr(plugin_instance, 'get_blueprint'):
                bp = plugin_instance.get_blueprint()
                if bp:
                    app.register_blueprint(bp)
                    logger.info(f"Registered custom blueprint for plugin '{plugin_id}'")
            elif hasattr(type(plugin_instance), 'get_blueprint'):
                bp = type(plugin_instance).get_blueprint()
                if bp:
                    app.register_blueprint(bp)
                    logger.info(f"Registered custom blueprint for plugin '{plugin_id}'")
        except Exception as e:
            logger.warning(f"Failed to register blueprint for plugin '{plugin_id}': {e}")
```

In `src/inkypi.py`:
Add `--plugin-path` CLI option:
```python
parser.add_argument('--plugin-path', type=str, default=None, help='Colon-separated additional plugin paths')
# ...
if args.plugin_path:
    os.environ["INKYPI_PLUGIN_PATH"] = args.plugin_path
```
Import and call `register_plugin_blueprints(app)`:
```python
from plugins.plugin_registry import load_plugins, register_plugin_blueprints

# After core app.register_blueprint(...) calls:
register_plugin_blueprints(app)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest tests/test_plugin_registry.py -v"`
Expected: PASS (1/1 passed).

- [ ] **Step 5: Commit changes**

```bash
git add src/plugins/plugin_registry.py src/inkypi.py tests/test_plugin_registry.py
git commit -m "feat: add dynamic plugin search path and generic blueprint registration"
```

---

### Task 3: Declarative Web UI Protection & Active Controls

**Files:**
- Modify: `src/blueprints/main.py`
- Modify: `src/blueprints/settings.py`
- Modify: `src/blueprints/playlist.py`
- Modify: `src/blueprints/plugin.py`
- Modify: `src/blueprints/apikeys.py`
- Modify: `src/templates/settings.html`
- Modify: `src/templates/playlist.html`
- Modify: `src/templates/plugin.html`
- Modify: `src/templates/apikeys.html`
- Create: `tests/test_declarative_web.py`

**Interfaces:**
- Consumes: `Config.declarative_mode`.
- Produces: HTTP 403 on POST mutation routes when `declarative_mode=True`; Jinja template `is_declarative` flag; HTTP 200 on `/`, `/api/refresh`, `/api/status`, `/api/photoframe/status`, `/api/photoframe/image`.

- [ ] **Step 1: Write failing tests for declarative Web UI behavior**

Create `tests/test_declarative_web.py`:
```python
import json
import pytest
from flask import Flask
from config import Config
from blueprints.main import main_bp
from blueprints.settings import settings_bp
from blueprints.playlist import playlist_bp
from blueprints.apikeys import apikeys_bp
from blueprints.photoframe import photoframe_bp


@pytest.fixture
def declarative_app(tmp_path):
    app = Flask(__name__, template_folder="../src/templates", static_folder="../src/static")
    app.config["TESTING"] = True

    config_data = {
        "device_name": "Declarative InkyPi",
        "display_type": "photoframe",
        "model": "waveshare_13_3",
        "resolution": [1600, 1200],
        "orientation": 0,
        "playlist_config": {"playlists": []},
        "refresh_info": {}
    }
    cfg_file = tmp_path / "device.json"
    cfg_file.write_text(json.dumps(config_data))

    cfg = Config(config_file=str(cfg_file), state_dir=str(tmp_path), declarative_mode=True)
    app.config["DEVICE_CONFIG"] = cfg
    app.config["DECLARATIVE_MODE"] = True

    app.register_blueprint(main_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(playlist_bp)
    app.register_blueprint(apikeys_bp)
    app.register_blueprint(photoframe_bp)

    return app


def test_declarative_mutation_rejected(declarative_app):
    client = declarative_app.test_client()

    # Settings save rejected
    resp = client.post("/settings", data={"orientation": 180})
    assert resp.status_code == 403
    assert "declarative mode" in resp.json["error"].lower()

    # API keys save rejected
    resp = client.post("/api-keys/save", json={"entries": []})
    assert resp.status_code == 403
    assert "declarative mode" in resp.json["error"].lower()


def test_declarative_active_controls_allowed(declarative_app):
    client = declarative_app.test_client()

    # Status endpoints work
    resp = client.get("/api/photoframe/status")
    assert resp.status_code == 200
    assert resp.json["device_name"] == "Declarative InkyPi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest tests/test_declarative_web.py -v"`
Expected: FAIL (endpoints return 200 or 302 instead of 403).

- [ ] **Step 3: Implement route protection and Jinja context processor**

In `src/inkypi.py`:
Add context processor to inject `is_declarative`:
```python
@app.context_processor
def inject_declarative_status():
    return {
        "is_declarative": Config.declarative_mode
    }
```
Store `DECLARATIVE_MODE` in `app.config`:
```python
app.config["DECLARATIVE_MODE"] = Config.declarative_mode
```

In `src/blueprints/settings.py`:
Check declarative mode at the beginning of mutation routes:
```python
@settings_bp.route('/settings', methods=['POST'])
def save_settings():
    if current_app.config.get("DECLARATIVE_MODE", False):
        return jsonify({"success": False, "error": "InkyPi is running in declarative mode. Modify settings in configuration.nix."}), 403
    # ... existing save logic ...
```

In `src/blueprints/playlist.py`:
Check declarative mode on playlist mutation routes:
```python
@playlist_bp.before_request
def check_declarative_playlist():
    if request.method in ("POST", "PUT", "DELETE") and current_app.config.get("DECLARATIVE_MODE", False):
        return jsonify({"success": False, "error": "InkyPi is running in declarative mode. Manage playlists in configuration.nix."}), 403
```

In `src/blueprints/apikeys.py`:
Check declarative mode on save route:
```python
@apikeys_bp.route('/api-keys/save', methods=['POST'])
def save_keys():
    if current_app.config.get("DECLARATIVE_MODE", False):
        return jsonify({"success": False, "error": "InkyPi is running in declarative mode. Provide API keys via environmentFile (agenix)."}), 403
    # ... existing save logic ...
```

In `src/templates/settings.html`, `src/templates/playlist.html`, `src/templates/apikeys.html`:
Add declarative banner block at the top of forms:
```html
{% if is_declarative %}
<div style="background: rgba(30, 144, 255, 0.15); border-left: 4px solid #1e90ff; padding: 12px 16px; margin-bottom: 20px; border-radius: 4px;">
    <strong>Declarative Mode Active:</strong> Settings are managed via NixOS. Configuration on this page is read-only.
</div>
{% endif %}
```
And disable submit buttons when `is_declarative` is True (`{% if is_declarative %}disabled title="Managed via NixOS"{% endif %}`).

- [ ] **Step 4: Run test to verify it passes**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest tests/test_declarative_web.py -v"`
Expected: PASS (2/2 passed).

- [ ] **Step 5: Run full test suite**

Run: `nix-shell -p "python3.withPackages (ps: with ps; [ pytest flask requests pillow waitress psutil pytz icalendar feedparser astral numpy recurring-ical-events python-dotenv ])" --run "PYTHONPATH=src pytest -v"`
Expected: PASS (44/44 passed).

- [ ] **Step 6: Commit changes**

```bash
git add src/blueprints/ src/templates/ src/inkypi.py tests/test_declarative_web.py
git commit -m "feat: add declarative Web UI banner and mutation endpoint protection"
```

---

### Task 4: Nix Flake & Package Definition

**Files:**
- Create: `flake.nix`
- Create: `package.nix`
- Test: `nix build .#default`

**Interfaces:**
- Consumes: InkyPi source code, Nixpkgs python libraries.
- Produces: `packages.<system>.default` containing executable `bin/inkypi`.

- [ ] **Step 1: Write `package.nix`**

Create `package.nix`:
```nix
{ lib
, python3Packages
}:

python3Packages.buildPythonApplication {
  pname = "inkypi";
  version = "1.0.0";
  format = "other";

  src = ./.;

  propagatedBuildInputs = with python3Packages; [
    flask
    python-dotenv
    requests
    pillow
    waitress
    psutil
    pytz
    icalendar
    feedparser
    astral
    numpy
    recurring-ical-events
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/inkypi $out/bin
    cp -r src/* $out/lib/inkypi/

    cat > $out/bin/inkypi <<EOF
    #!/bin/sh
    export PYTHONPATH="$out/lib/inkypi:\$PYTHONPATH"
    exec ${python3Packages.python.interpreter} $out/lib/inkypi/inkypi.py "\$@"
    EOF
    chmod +x $out/bin/inkypi

    runHook postInstall
  '';

  meta = with lib; {
    description = "E-Paper photoframe and dashboard server";
    homepage = "https://github.com/npontious/InkyPi";
    license = licenses.gpl3Only;
    maintainers = [ ];
    mainProgram = "inkypi";
  };
}
```

- [ ] **Step 2: Write `flake.nix`**

Create `flake.nix`:
```nix
{
  description = "InkyPi E-Paper Image Server";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages.default = pkgs.callPackage ./package.nix { };
        packages.inkypi = self.packages.${system}.default;

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/inkypi";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [
              pytest
              flask
              python-dotenv
              requests
              pillow
              waitress
              psutil
              pytz
              icalendar
              feedparser
              astral
              numpy
              recurring-ical-events
            ]))
          ];
        };
      }
    ) // {
      nixosModules.default = import ./nix/module.nix self;
      nixosModules.inkypi = self.nixosModules.default;
    };
}
```

- [ ] **Step 3: Test building the package with Nix**

Run: `nix build .#default --no-link`
Expected: Build succeeds cleanly.

- [ ] **Step 4: Commit package and flake files**

```bash
git add package.nix flake.nix
git commit -m "feat: add Nix packaging and flake definition"
```

---

### Task 5: NixOS Module Definition (`nixosModules.default`)

**Files:**
- Create: `nix/module.nix`
- Test: `nix flake check`

**Interfaces:**
- Consumes: `self` (flake), `options.services.inkypi`.
- Produces: `systemd.services.inkypi` with declarative `device.json` serialization and runtime flags.

- [ ] **Step 1: Write `nix/module.nix`**

Create `nix/module.nix`:
```nix
flakeSelf:
{ config, lib, pkgs, ... }:

let
  cfg = config.services.inkypi;
  configFile = pkgs.writeText "inkypi-device.json" (builtins.toJSON cfg.settings);

  pythonEnv = pkgs.python3.withPackages (ps: 
    (with ps; [
      flask
      python-dotenv
      requests
      pillow
      waitress
      psutil
      pytz
      icalendar
      feedparser
      astral
      numpy
      recurring-ical-events
    ]) ++ (cfg.extraPythonPackages ps)
  );

  pluginPathArgs = lib.optionalString (cfg.extraPlugins != [ ])
    "--plugin-path ${lib.concatStringsSep ":" (map toString cfg.extraPlugins)}";
in
{
  options.services.inkypi = {
    enable = lib.mkEnableOption "InkyPi E-Paper Image Server";

    package = lib.mkOption {
      type = lib.types.package;
      default = flakeSelf.packages.${pkgs.system}.default;
      description = "The InkyPi package to use.";
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
      description = "State directory for mutable rendered images and cache.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "inkypi";
      description = "User account under which to run the service.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "inkypi";
      description = "Group under which to run the service.";
    };

    environmentFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Optional environment file (e.g. from agenix/sops-nix) for API keys.";
    };

    extraPlugins = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      description = "Additional plugin directories to load.";
    };

    extraPythonPackages = lib.mkOption {
      type = lib.types.functionTo (lib.types.listOf lib.types.package);
      default = ps: [ ];
      description = "Extra Python packages to make available for community plugins.";
    };

    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.anything;
      default = { };
      description = "Declarative InkyPi device configuration matching device.json.";
    };
  };

  config = lib.mkIf cfg.enable {
    networking.firewall.allowedTCPPorts = [ cfg.port ];

    users.users = lib.mkIf (cfg.user == "inkypi") {
      inkypi = {
        isSystemUser = true;
        group = cfg.group;
        home = cfg.stateDir;
        createHome = false;
      };
    };

    users.groups = lib.mkIf (cfg.group == "inkypi") {
      inkypi = { };
    };

    systemd.services.inkypi = {
      description = "InkyPi E-Paper Image Server";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];

      environment = {
        PYTHONPATH = "${cfg.package}/lib/inkypi";
      };

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        StateDirectory = "inkypi";
        WorkingDirectory = cfg.stateDir;
        EnvironmentFile = lib.optional (cfg.environmentFile != null) cfg.environmentFile;
        ExecStart = "${pythonEnv}/bin/python3 ${cfg.package}/lib/inkypi/inkypi.py "
          + "--config-file ${configFile} "
          + "--state-dir ${cfg.stateDir} "
          + "--port ${toString cfg.port} "
          + "--host ${cfg.host} "
          + "--declarative "
          + pluginPathArgs;
        Restart = "always";
        RestartSec = "5s";
      };
    };
  };
}
```

- [ ] **Step 2: Run `nix flake check`**

Run: `nix flake check`
Expected: PASS with zero warnings or errors.

- [ ] **Step 3: Commit module**

```bash
git add nix/module.nix
git commit -m "feat: add declarative NixOS service module"
```

---

### Task 6: Host `glacio` Integration & Live Deployment Verification

**Files:**
- Modify: `/etc/nixos/flake.nix` on `glacio`
- Modify: `/etc/nixos/modules/inkypi.nix` on `glacio`
- Modify: `/etc/nixos/hosts/glacio/configuration.nix` on `glacio`

**Interfaces:**
- Consumes: InkyPi git repository / flake output.
- Produces: Running systemd service on `glacio` reading `/nix/store/...-inkypi-device.json` and writing runtime images to `/var/lib/inkypi`.

- [ ] **Step 1: Push InkyPi repository changes to remote**

```bash
git push origin main
```

- [ ] **Step 2: Update `/etc/nixos/flake.nix` on `glacio`**

Add `inkypi` input:
```nix
inkypi.url = "github:npontious/InkyPi";
inkypi.inputs.nixpkgs.follows = "nixpkgs";
```
And pass `inkypi` to `specialArgs`.

- [ ] **Step 3: Update `/etc/nixos/modules/inkypi.nix` on `glacio`**

Rewire `modules/inkypi.nix` to use `inkypi.nixosModules.default`:
```nix
{ config, lib, pkgs, inkypi, ... }:

let
  cfg = config.mySystem.services.inkypi;
in
{
  imports = [ inkypi.nixosModules.default ];

  options.mySystem.services.inkypi = {
    enable = lib.mkEnableOption "InkyPi E-Paper Image Server";
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

- [ ] **Step 4: Update `/etc/nixos/hosts/glacio/configuration.nix`**

Define declarative device settings:
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

- [ ] **Step 5: Rebuild NixOS on `glacio`**

Run: `ssh glacio "sudo nixos-rebuild switch --flake /etc/nixos#glacio"`
Expected: Rebuild passes and restarts `inkypi.service`.

- [ ] **Step 6: Live Verification**

1. Verify systemd status:
   `ssh glacio "systemctl status inkypi"` -> active (running).
2. Query PhotoFrame status:
   `ssh glacio "curl -s http://localhost:8085/api/photoframe/status"` -> valid JSON with device_name and telemetry.
3. Verify manual refresh control:
   `ssh glacio "curl -s -X POST http://localhost:8085/api/refresh"` -> success.
4. Verify mutation rejection:
   `ssh glacio "curl -s -X POST http://localhost:8085/settings"` -> 403 Forbidden with declarative error message.
