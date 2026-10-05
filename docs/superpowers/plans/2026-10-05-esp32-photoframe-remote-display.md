# InkyPi Remote Display & ESP32 PhotoFrame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable InkyPi to run in headless server mode, generating and scheduling 1600x1200 images for a battery-powered Seeed Studio XIAO EE02 ESP32-S3 driver board running `esp32-photoframe` driving a 13.3" Spectra 6 E-Ink display over Wi-Fi with ultra-fast ETag deep sleep caching.

**Architecture:** A new `PhotoframeDisplay` driver operates headlessly on the server without physical GPIO/SPI requirements. An optimized `/api/photoframe/image` endpoint evaluates `If-None-Match` to return `304 Not Modified` when content is unchanged (allowing < 500 ms ESP32 wake-and-sleep cycles), delivers full PNG payloads when updated, and extracts client battery/RSSI telemetry into InkyPi's dashboard and status APIs.

**Tech Stack:** Python 3, Flask, Pillow, pytest, ESP-IDF / `esp32-photoframe` binary, `esptool.py`.

**Spec:** `docs/superpowers/specs/2026-10-05-esp32-photoframe-remote-display-design.md`

## Global Constraints
- Decoupled server execution: No hardware dependencies (e.g. `spidev`, `RPi.GPIO`, `inky`) required when using `display_type: "photoframe"`.
- Native panel resolution: Default 1600 × 1200 pixels.
- HTTP Caching compliance: `ETag` must match image hash, and `If-None-Match` must return `HTTP 304 Not Modified` with zero-length body.
- Telemetry ingestion: Must support both HTTP request headers (`X-Battery-Voltage`, `X-Battery-Percent`, `X-WiFi-RSSI`) and query parameters (`?battery=...&percent=...&rssi=...`).
- Test execution: Python test suite runs via `nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest"`.

## Review Focus
1. `If-None-Match` quoting: Clients may send `If-None-Match` with or without surrounding quotes (e.g., `"hash123"` vs `hash123`); the server must match both correctly.
2. Missing or ungenerated image: If the display endpoint is accessed before any refresh has executed, it must fall back to generating or serving the startup/default image gracefully rather than returning 500.
3. Telemetry parameter sanitization: Malformed or non-numeric battery/RSSI values in query parameters or headers must be safely ignored without raising uncaught exceptions.
4. Concurrency: Multiple rapid polling requests from clients must not corrupt `current_image.png` while a refresh task is actively writing it.
5. Inverted/Orientation compatibility: Changing rotation/orientation in InkyPi configuration must correctly transform the 1600x1200 image output served to the remote photoframe.

---

### Task 1: Model & Telemetry Storage (`RefreshInfo`)

**Files:**
- Modify: `src/model.py:15-75`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: None
- Produces: `RefreshInfo` attributes `remote_client_last_seen`, `remote_client_battery_voltage`, `remote_client_battery_percent`, `remote_client_wifi_rssi`.

- [ ] **Step 1: Write the failing unit tests for remote client telemetry**

Add test cases in `tests/test_model.py`:
```python
def test_refresh_info_remote_client_telemetry():
    from src.model import RefreshInfo

    info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2026-10-05T18:00:00",
        image_hash="abc12345",
        remote_client_last_seen="2026-10-05T18:05:00",
        remote_client_battery_voltage=4.12,
        remote_client_battery_percent=94,
        remote_client_wifi_rssi=-62
    )

    data = info.to_dict()
    assert data["remote_client_last_seen"] == "2026-10-05T18:05:00"
    assert data["remote_client_battery_voltage"] == 4.12
    assert data["remote_client_battery_percent"] == 94
    assert data["remote_client_wifi_rssi"] == -62

    restored = RefreshInfo.from_dict(data)
    assert restored.remote_client_last_seen == "2026-10-05T18:05:00"
    assert restored.remote_client_battery_voltage == 4.12
    assert restored.remote_client_battery_percent == 94
    assert restored.remote_client_wifi_rssi == -62
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest tests/test_model.py::test_refresh_info_remote_client_telemetry"
```
Expected: FAIL with `TypeError: RefreshInfo.__init__() got an unexpected keyword argument 'remote_client_last_seen'`.

- [ ] **Step 3: Update `RefreshInfo` in `src/model.py`**

In `src/model.py`, update `RefreshInfo.__init__`, `to_dict`, and `from_dict`:
```python
class RefreshInfo:
    def __init__(
        self,
        refresh_type=None,
        plugin_id=None,
        refresh_time=None,
        image_hash=None,
        playlist=None,
        plugin_instance=None,
        duration_seconds=None,
        plugin_processing_duration_seconds=None,
        display_refresh_duration_seconds=None,
        remote_client_last_seen=None,
        remote_client_battery_voltage=None,
        remote_client_battery_percent=None,
        remote_client_wifi_rssi=None,
    ):
        self.refresh_time = refresh_time
        self.image_hash = image_hash
        self.refresh_type = refresh_type
        self.plugin_id = plugin_id
        self.playlist = playlist
        self.plugin_instance = plugin_instance
        self.duration_seconds = duration_seconds
        self.plugin_processing_duration_seconds = plugin_processing_duration_seconds
        self.display_refresh_duration_seconds = display_refresh_duration_seconds
        self.remote_client_last_seen = remote_client_last_seen
        self.remote_client_battery_voltage = remote_client_battery_voltage
        self.remote_client_battery_percent = remote_client_battery_percent
        self.remote_client_wifi_rssi = remote_client_wifi_rssi

    def to_dict(self):
        refresh_dict = {
            "refresh_time": self.refresh_time,
            "image_hash": self.image_hash,
            "refresh_type": self.refresh_type,
            "plugin_id": self.plugin_id,
        }
        if self.playlist:
            refresh_dict["playlist"] = self.playlist
        if self.plugin_instance:
            refresh_dict["plugin_instance"] = self.plugin_instance
        if self.duration_seconds is not None:
            refresh_dict["duration_seconds"] = self.duration_seconds
        if self.plugin_processing_duration_seconds is not None:
            refresh_dict["plugin_processing_duration_seconds"] = self.plugin_processing_duration_seconds
        if self.display_refresh_duration_seconds is not None:
            refresh_dict["display_refresh_duration_seconds"] = self.display_refresh_duration_seconds
        if self.remote_client_last_seen is not None:
            refresh_dict["remote_client_last_seen"] = self.remote_client_last_seen
        if self.remote_client_battery_voltage is not None:
            refresh_dict["remote_client_battery_voltage"] = self.remote_client_battery_voltage
        if self.remote_client_battery_percent is not None:
            refresh_dict["remote_client_battery_percent"] = self.remote_client_battery_percent
        if self.remote_client_wifi_rssi is not None:
            refresh_dict["remote_client_wifi_rssi"] = self.remote_client_wifi_rssi
        return refresh_dict

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            refresh_time=data.get("refresh_time"),
            image_hash=data.get("image_hash"),
            refresh_type=data.get("refresh_type"),
            plugin_id=data.get("plugin_id"),
            playlist=data.get("playlist"),
            plugin_instance=data.get("plugin_instance"),
            duration_seconds=data.get("duration_seconds"),
            plugin_processing_duration_seconds=data.get("plugin_processing_duration_seconds"),
            display_refresh_duration_seconds=data.get("display_refresh_duration_seconds"),
            remote_client_last_seen=data.get("remote_client_last_seen"),
            remote_client_battery_voltage=data.get("remote_client_battery_voltage"),
            remote_client_battery_percent=data.get("remote_client_battery_percent"),
            remote_client_wifi_rssi=data.get("remote_client_wifi_rssi"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest tests/test_model.py"
```
Expected: PASS (all tests pass).

- [ ] **Step 5: Commit**

```bash
git add src/model.py tests/test_model.py
git commit -m "feat(model): add remote client telemetry fields to RefreshInfo"
```

---

### Task 2: Remote Photoframe Display Driver (`PhotoframeDisplay`)

**Files:**
- Create: `src/display/photoframe_display.py`
- Modify: `src/display/display_manager.py:40-60`
- Test: `tests/test_photoframe_display.py`

**Interfaces:**
- Consumes: `AbstractDisplay` from `src/display/abstract_display.py`
- Produces: `PhotoframeDisplay` class; `DisplayManager` returns `PhotoframeDisplay` when `display_type == "photoframe"`.

- [ ] **Step 1: Write the failing unit tests for PhotoframeDisplay**

Create `tests/test_photoframe_display.py`:
```python
import os
import pytest
from PIL import Image
from src.config import Config
from src.display.photoframe_display import PhotoframeDisplay
from src.display.display_manager import DisplayManager

class DummyConfig:
    def __init__(self, tmp_path):
        self.current_image_file = str(tmp_path / "current_image.png")
        self.config = {
            "display_type": "photoframe",
            "resolution": [1600, 1200],
            "orientation": "horizontal",
            "inverted_image": False,
            "image_settings": []
        }

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def get_resolution(self):
        res = self.config.get("resolution")
        return (int(res[0]), int(res[1]))

def test_photoframe_display_saves_image(tmp_path):
    conf = DummyConfig(tmp_path)
    disp = PhotoframeDisplay(conf)

    img = Image.new("RGB", (1600, 1200), color=(255, 0, 0))
    disp.display_image(img)

    assert os.path.exists(conf.current_image_file)
    saved_img = Image.open(conf.current_image_file)
    assert saved_img.size == (1600, 1200)

def test_display_manager_initializes_photoframe(tmp_path):
    conf = DummyConfig(tmp_path)
    dm = DisplayManager(conf)
    assert isinstance(dm.display, PhotoframeDisplay)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest tests/test_photoframe_display.py"
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.display.photoframe_display'`.

- [ ] **Step 3: Create `src/display/photoframe_display.py` and update `src/display/display_manager.py`**

Create `src/display/photoframe_display.py`:
```python
import os
import logging
from display.abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)

class PhotoframeDisplay(AbstractDisplay):
    """
    Display implementation for headless server mode.
    Saves the rendered and processed image to disk for remote Wi-Fi clients (e.g. ESP32).
    """

    def initialize_display(self):
        """Initializes the remote photoframe display storage."""
        logger.info("Initializing Remote PhotoFrame display")
        output_dir = os.path.dirname(self.device_config.current_image_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

    def display_image(self, image, image_settings=[]):
        """
        Saves the processed image to the configured current_image_file path.

        Args:
            image (PIL.Image): The final processed image.
            image_settings (list, optional): Optional image adjustments.
        """
        logger.info(f"PhotoframeDisplay: Writing image to {self.device_config.current_image_file}")
        image.save(self.device_config.current_image_file, format="PNG")
```

In `src/display/display_manager.py`, import `PhotoframeDisplay` and add it to `__init__`:
```python
from display.photoframe_display import PhotoframeDisplay
...
        if display_type == "mock":
            self.display = MockDisplay(device_config)
        elif display_type == "photoframe":
            self.display = PhotoframeDisplay(device_config)
        elif display_type == "inky":
...
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest tests/test_photoframe_display.py"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/display/photoframe_display.py src/display/display_manager.py tests/test_photoframe_display.py
git commit -m "feat(display): add PhotoframeDisplay for headless Wi-Fi remote displays"
```

---

### Task 3: PhotoFrame API Blueprint & Caching (`/api/photoframe/image` and `/api/photoframe/status`)

**Files:**
- Create: `src/blueprints/photoframe.py`
- Modify: `src/inkypi.py:75-85`
- Test: `tests/test_photoframe_blueprint.py`

**Interfaces:**
- Consumes: `current_app.config['DEVICE_CONFIG']`
- Produces:
  - `GET /api/photoframe/image` (returns 200 with PNG and ETag, or 304 Not Modified; ingests telemetry headers/query params)
  - `GET /api/photoframe/status` (returns JSON status)

- [ ] **Step 1: Write integration tests for PhotoFrame endpoints**

Create `tests/test_photoframe_blueprint.py`:
```python
import os
import pytest
from PIL import Image
from flask import Flask
from src.blueprints.photoframe import photoframe_bp
from src.model import RefreshInfo

class MockConfig:
    def __init__(self, tmp_path):
        self.current_image_file = str(tmp_path / "current_image.png")
        self.refresh_info = RefreshInfo(
            refresh_time="2026-10-05T18:00:00",
            image_hash="hash-12345",
            refresh_type="Playlist",
            plugin_id="clock"
        )
        self.written = False

    def get_refresh_info(self):
        return self.refresh_info

    def write_config(self):
        self.written = True

    def get_config(self, key, default=None):
        return "InkyPi Test" if key == "name" else default

@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    config = MockConfig(tmp_path)
    
    # Create a dummy image
    img = Image.new("RGB", (1600, 1200), color=(100, 150, 200))
    img.save(config.current_image_file, format="PNG")

    app.config["DEVICE_CONFIG"] = config
    app.register_blueprint(photoframe_bp)
    with app.test_client() as c:
        yield c, config

def test_get_image_returns_200_and_etag(client):
    c, config = client
    res = c.get("/api/photoframe/image")
    assert res.status_code == 200
    assert res.headers.get("Content-Type") == "image/png"
    assert res.headers.get("ETag") == '"hash-12345"'
    assert len(res.data) > 0

def test_get_image_returns_304_on_matching_if_none_match(client):
    c, config = client
    # Test with quoted ETag
    res = c.get("/api/photoframe/image", headers={"If-None-Match": '"hash-12345"'})
    assert res.status_code == 304
    assert len(res.data) == 0

    # Test with unquoted ETag
    res2 = c.get("/api/photoframe/image", headers={"If-None-Match": "hash-12345"})
    assert res2.status_code == 304

def test_telemetry_ingestion_via_headers(client):
    c, config = client
    res = c.get(
        "/api/photoframe/image",
        headers={
            "X-Battery-Voltage": "4.15",
            "X-Battery-Percent": "92",
            "X-WiFi-RSSI": "-58",
        },
    )
    assert res.status_code == 200
    assert config.refresh_info.remote_client_battery_voltage == 4.15
    assert config.refresh_info.remote_client_battery_percent == 92
    assert config.refresh_info.remote_client_wifi_rssi == -58
    assert config.refresh_info.remote_client_last_seen is not None
    assert config.written is True

def test_telemetry_ingestion_via_query_params(client):
    c, config = client
    res = c.get("/api/photoframe/image?battery=3.85&percent=65&rssi=-72")
    assert res.status_code == 200
    assert config.refresh_info.remote_client_battery_voltage == 3.85
    assert config.refresh_info.remote_client_battery_percent == 65
    assert config.refresh_info.remote_client_wifi_rssi == -72

def test_photoframe_status_endpoint(client):
    c, config = client
    res = c.get("/api/photoframe/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["image_hash"] == "hash-12345"
    assert "remote_client" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest tests/test_photoframe_blueprint.py"
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.blueprints.photoframe'`.

- [ ] **Step 3: Create `src/blueprints/photoframe.py` and register in `src/inkypi.py`**

Create `src/blueprints/photoframe.py`:
```python
import os
import logging
from datetime import datetime, timezone
from flask import Blueprint, current_app, request, Response, send_file, jsonify

logger = logging.getLogger(__name__)

photoframe_bp = Blueprint("photoframe", __name__)

def _parse_float(val):
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _parse_int(val):
    try:
        return int(float(val)) if val is not None else None
    except (ValueError, TypeError):
        return None

def _update_telemetry(device_config):
    """Parses telemetry from headers or query parameters and updates device_config."""
    voltage = _parse_float(request.headers.get("X-Battery-Voltage") or request.args.get("battery"))
    percent = _parse_int(request.headers.get("X-Battery-Percent") or request.args.get("percent"))
    rssi = _parse_int(request.headers.get("X-WiFi-RSSI") or request.args.get("rssi"))

    now_iso = datetime.now(timezone.utc).isoformat()
    updated = False

    refresh_info = device_config.get_refresh_info()
    refresh_info.remote_client_last_seen = now_iso
    updated = True

    if voltage is not None:
        refresh_info.remote_client_battery_voltage = voltage
        updated = True
    if percent is not None:
        refresh_info.remote_client_battery_percent = percent
        updated = True
    if rssi is not None:
        refresh_info.remote_client_wifi_rssi = rssi
        updated = True

    if updated:
        try:
            device_config.write_config()
        except Exception as e:
            logger.warning(f"Could not persist telemetry update: {e}")

@photoframe_bp.route("/api/photoframe/image", methods=["GET", "HEAD"])
def get_photoframe_image():
    """
    Serves the current rendered image to the remote photoframe client.
    Supports ETag / 304 Not Modified caching and ingests client telemetry.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    _update_telemetry(device_config)

    refresh_info = device_config.get_refresh_info()
    current_hash = refresh_info.image_hash or ""
    quoted_hash = f'"{current_hash}"'

    # Check ETag / If-None-Match header
    client_etag = request.headers.get("If-None-Match", "").strip()
    if client_etag and current_hash:
        # Match with or without double quotes
        if client_etag == quoted_hash or client_etag.strip('"') == current_hash:
            logger.debug(f"PhotoFrame ETag match ({client_etag}), returning 304 Not Modified")
            resp = Response(status=304)
            resp.headers["ETag"] = quoted_hash
            resp.headers["Cache-Control"] = "no-cache"
            return resp

    image_path = device_config.current_image_file
    if not os.path.exists(image_path):
        logger.warning(f"Current image not found at {image_path}, generating fallback")
        from PIL import Image
        img = Image.new("RGB", (1600, 1200), color=(255, 255, 255))
        img.save(image_path, format="PNG")

    resp = send_file(image_path, mimetype="image/png")
    resp.headers["ETag"] = quoted_hash
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@photoframe_bp.route("/api/photoframe/status", methods=["GET"])
def get_photoframe_status():
    """Returns the remote display and telemetry status."""
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_info = device_config.get_refresh_info()
    
    return jsonify({
        "device_name": device_config.get_config("name", "InkyPi"),
        "image_hash": refresh_info.image_hash,
        "last_refresh_time": refresh_info.refresh_time,
        "remote_client": {
            "last_seen": refresh_info.remote_client_last_seen,
            "battery_voltage": refresh_info.remote_client_battery_voltage,
            "battery_percent": refresh_info.remote_client_battery_percent,
            "wifi_rssi": refresh_info.remote_client_wifi_rssi,
        }
    })
```

In `src/inkypi.py`, register the blueprint:
```python
from blueprints.photoframe import photoframe_bp
...
app.register_blueprint(photoframe_bp)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest tests/test_photoframe_blueprint.py"
```
Expected: PASS (all 5 integration tests pass).

- [ ] **Step 5: Commit**

```bash
git add src/blueprints/photoframe.py src/inkypi.py tests/test_photoframe_blueprint.py
git commit -m "feat(api): add photoframe image and status endpoints with ETag caching"
```

---

### Task 4: UI & Configuration Updates (Settings & Dashboard Telemetry Badge)

**Files:**
- Modify: `src/config/device_dev.json:1-10`
- Modify: `src/templates/settings.html:15-60`
- Modify: `src/templates/inky.html:10-50`
- Modify: `src/blueprints/main.py:60-90`

**Interfaces:**
- Consumes: `device_config.get_refresh_info()`
- Produces: UI options for "photoframe" display type; remote battery and RSSI status on dashboard.

- [ ] **Step 1: Update `device_dev.json` preset**

Ensure `"photoframe"` is recognized and configure the 1600x1200 resolution:
```json
{
    "name": "InkyPi Development",
    "display_type": "photoframe",
    "resolution": [
        1600,
        1200
    ],
    "orientation": "horizontal",
...
```

- [ ] **Step 2: Update `src/templates/settings.html`**

Add the `Remote PhotoFrame (Wi-Fi ESP32)` option in the `display_type` `<select>`:
```html
<option value="photoframe" {% if device_config.get_config('display_type') == 'photoframe' %}selected{% endif %}>Remote PhotoFrame (Wi-Fi ESP32 - 13.3" Spectra 6)</option>
```
And add a helper card showing the Image Server URL when `photoframe` is selected:
```html
<div id="photoframe-help" class="alert alert-info mt-2" {% if device_config.get_config('display_type') != 'photoframe' %}style="display:none;"{% endif %}>
    <strong>ESP32 Image Server URL:</strong>
    <code>http://&lt;your-server-ip&gt;:{{ request.host.split(':')[1] if ':' in request.host else '80' }}/api/photoframe/image</code>
</div>
```

- [ ] **Step 3: Update `src/templates/inky.html` (Dashboard)**

In `src/templates/inky.html`, display the remote battery indicator when `remote_client_battery_percent` is present:
```html
{% set refresh_info = device_config.get_refresh_info() %}
{% if refresh_info.remote_client_battery_percent is not none %}
<div class="remote-client-badge text-muted small mt-1">
    <i class="bi bi-battery-charging"></i> ESP32 Battery: <strong>{{ refresh_info.remote_client_battery_percent }}%</strong>
    {% if refresh_info.remote_client_battery_voltage %}({{ refresh_info.remote_client_battery_voltage }}V){% endif %}
    {% if refresh_info.remote_client_wifi_rssi %}| Wi-Fi: <strong>{{ refresh_info.remote_client_wifi_rssi }} dBm</strong>{% endif %}
</div>
{% endif %}
```

- [ ] **Step 4: Update `/api/status` in `src/blueprints/main.py`**

Include remote client telemetry in `/api/status`:
```python
    status["remote_client"] = {
        "last_seen": refresh_info.get("remote_client_last_seen"),
        "battery_voltage": refresh_info.get("remote_client_battery_voltage"),
        "battery_percent": refresh_info.get("remote_client_battery_percent"),
        "wifi_rssi": refresh_info.get("remote_client_wifi_rssi")
    }
```

- [ ] **Step 5: Run full test suite to verify no regressions**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest"
```
Expected: PASS (all tests pass).

- [ ] **Step 6: Commit**

```bash
git add src/config/device_dev.json src/templates/settings.html src/templates/inky.html src/blueprints/main.py
git commit -m "feat(ui): add photoframe settings option and dashboard telemetry badge"
```

---

### Task 5: Firmware Flashing Tooling for XIAO EE02 (`scripts/flash_ee02.sh`)

**Files:**
- Create: `scripts/flash_ee02.sh`

**Interfaces:**
- Consumes: `/dev/ttyACM0` (or user specified port)
- Produces: Executable script that downloads official `esp32-photoframe` merged firmware for `seeedstudio_xiao_ee02` and flashes it using `esptool.py`.

- [ ] **Step 1: Create `scripts/flash_ee02.sh`**

Create `scripts/flash_ee02.sh`:
```bash
#!/usr/bin/env bash
set -e

PORT="${1:-/dev/ttyACM0}"
BAUD="${2:-460800}"
FW_DIR="/tmp/esp32-photoframe-ee02"
RELEASE_TAG="v1.3.1"
FW_NAME="photoframe-firmware-seeedstudio_xiao_ee02-merged.bin"
FW_URL="https://github.com/aitjcize/esp32-photoframe/releases/download/${RELEASE_TAG}/${FW_NAME}"

echo "=========================================================="
echo "  Flashing XIAO EE02 13.3\" Spectra 6 E-Ink Firmware"
echo "=========================================================="
echo "Port: $PORT"
echo "Baud: $BAUD"
echo "Release: $RELEASE_TAG"

if [ ! -e "$PORT" ]; then
    echo "Error: Device port $PORT not found!"
    exit 1
fi

mkdir -p "$FW_DIR"
if [ ! -f "$FW_DIR/$FW_NAME" ]; then
    echo "Downloading prebuilt firmware: $FW_URL..."
    curl -L "$FW_URL" -o "$FW_DIR/$FW_NAME"
else
    echo "Firmware binary already downloaded at $FW_DIR/$FW_NAME"
fi

echo "Flashing firmware to $PORT..."
python3 -m esptool --port "$PORT" --baud "$BAUD" write_flash 0x0 "$FW_DIR/$FW_NAME"

echo "=========================================================="
echo "  Flashing complete!"
echo "  1. Reset or power cycle the XIAO EE02 board."
echo "  2. Connect to the 'PhotoFrame-XXXX' Wi-Fi access point."
echo "  3. Configure your Wi-Fi credentials."
echo "  4. Set Mode to 'Image Server' and URL to:"
echo "     http://<your-server-ip>:8080/api/photoframe/image"
echo "=========================================================="
```
Make it executable:
```bash
chmod +x scripts/flash_ee02.sh
```

- [ ] **Step 2: Commit**

```bash
git add scripts/flash_ee02.sh
git commit -m "feat(tools): add automated firmware flashing script for XIAO EE02"
```

---

### Task 6: Full Integration Test & End-to-End Verification

**Files:**
- Test: All tests in `tests/`
- Manual execution: Start InkyPi dev server and test live endpoints.

- [ ] **Step 1: Run complete test suite**

Run:
```bash
nix-shell -p python3Packages.pytest python3Packages.flask python3Packages.pillow --run "pytest -v"
```
Expected: All tests PASS.

- [ ] **Step 2: Run InkyPi with `--dev` flag and verify startup**

Run:
```bash
python3 src/inkypi.py --dev
```
Verify logs:
- "Initializing Remote PhotoFrame display"
- Server listens on port 8080.
- Querying `http://localhost:8080/api/photoframe/status` returns valid JSON with `image_hash` and `remote_client`.

- [ ] **Step 3: Test live ETag request**

Run:
```bash
curl -i http://localhost:8080/api/photoframe/image
```
Verify:
- Returns `HTTP/1.1 200 OK`
- `Content-Type: image/png`
- Contains `ETag: "<hash>"`

Now run with `If-None-Match`:
```bash
curl -i -H 'If-None-Match: "<hash>"' http://localhost:8080/api/photoframe/image
```
Verify:
- Returns `HTTP/1.1 304 Not Modified`
- Zero content body.

- [ ] **Step 4: Final Git Status & Clean Tree Verification**

Run:
```bash
git status
```
Verify working tree is clean and ready.
