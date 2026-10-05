# InkyPi Remote Display & ESP32 PhotoFrame Design Specification

## 1. Overview & Goals

This specification details the architecture and implementation for running InkyPi in **Remote Display / Server Mode**, decoupled from physical Raspberry Pi GPIO/SPI hardware. In this configuration, InkyPi runs on a headless server (or Linux machine / Docker container) to schedule and render dashboards/playlists, while a low-power **Seeed Studio XIAO ePaper Display Board EE02** (ESP32-S3 Plus) drives a **13.3-inch Spectra™ 6 (6-color) E-Ink display** over Wi-Fi.

### Goals
- **Decoupled Server Execution:** InkyPi runs on any standard server environment without requiring Raspberry Pi GPIO libraries or physical display hardware.
- **Maximum Battery Life:** Utilize ESP32 deep sleep, fast RTC Wi-Fi reconnection, and HTTP `ETag` (`304 Not Modified`) caching so the ESP32 wakes, checks for changes, and returns to sleep in < 500 ms when the display content has not changed.
- **Seamless Integration with InkyPi UI:** Expose the Remote PhotoFrame display option in the web UI settings, display the image feed URL, and display remote client telemetry (battery level, Wi-Fi RSSI) on the InkyPi dashboard.
- **High Visual Fidelity:** Render content at the native panel resolution (1600×1200) tailored for the 6-color Spectra 6 palette (Black, White, Red, Yellow, Green, Blue).

---

## 2. Architecture & Components

```
                      ┌──────────────────────────────────────────────┐
                      │                InkyPi Server                 │
                      │       (Linux / Docker / Server Mode)         │
                      ├──────────────────────────────────────────────┤
                      │ • PlaylistManager & Plugins Scheduler        │
                      │ • PhotoframeDisplay Driver (Headless)        │
                      │ • ETag & Hash Validator                      │
                      │ • Client Telemetry Collector (Battery, RSSI) │
                      │ • HTTP API (/api/photoframe/image)           │
                      └──────────────────────▲───────────────────────┘
                                             │
                       Wi-Fi HTTP GET / HEAD │ 200 OK (New Image)
                        with If-None-Match   │ or 304 Not Modified
                                             │
                      ┌──────────────────────▼───────────────────────┐
                      │       XIAO EE02 Driver Board (Client)        │
                      │         (ESP32-S3 Plus + 8MB PSRAM)          │
                      ├──────────────────────────────────────────────┤
                      │ • esp32-photoframe Firmware                  │
                      │ • Fast RTC Wi-Fi Reconnect                   │
                      │ • Dual-CS SPI Controller (CS1 + CS2)         │
                      │ • Power Gating & Deep Sleep Controller       │
                      └──────────────────────┬───────────────────────┘
                                             │ Dual SPI
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │    13.3" Spectra™ 6 E-Ink Display Panel      │
                      │        (1600 × 1200, 6-Color EPD)            │
                      └──────────────────────────────────────────────┘
```

### Components

1. **InkyPi Server:**
   - **`PhotoframeDisplay` (`src/display/photoframe_display.py`):** Concrete implementation of `AbstractDisplay` that saves rendered images to disk/cache and manages hash generation without local GPIO calls.
   - **`PhotoframeBlueprint` (`src/blueprints/photoframe.py`):** Exposes HTTP endpoints for image serving and telemetry ingestion.
   - **`DisplayManager` (`src/display/display_manager.py`):** Updated to instantiate `PhotoframeDisplay` when `display_type == "photoframe"`.
   - **`Model & Config` (`src/model.py`, `src/config.py`):** Extended to persist remote client telemetry (battery level, voltage, RSSI, last sync timestamp).
   - **Web UI:** Settings page exposes "Remote PhotoFrame (Wi-Fi ESP32)" option and image feed URL; Dashboard displays remote client battery and connection telemetry.

2. **XIAO EE02 Display Client:**
   - **Hardware:** Seeed Studio XIAO ESP32-S3 Plus with 8MB PSRAM and integrated LiPo battery management.
   - **Display:** 13.3" Spectra 6 E-Ink panel (1600 × 1200, 6-color) driven via dual chip-select SPI lines.
   - **Firmware:** `aitjcize/esp32-photoframe` (EE02 target build), configured in Image Server client mode.

---

## 3. Data Flow & Protocol Specification

### 3.1. Image Fetch & Caching Protocol

When the ESP32 wakes up, it connects to Wi-Fi and queries the InkyPi server:

#### Request
```http
GET /api/photoframe/image HTTP/1.1
Host: <inkypi-host>:<port>
If-None-Match: "3a7b9c1d..."
X-Battery-Voltage: 4.12
X-Battery-Percent: 94
X-WiFi-RSSI: -62
```

Query parameters are also accepted for clients that cannot set custom headers:
`GET /api/photoframe/image?battery=4.12&percent=94&rssi=-62`

#### Response: Unchanged Content (`304 Not Modified`)
If the server's current `image_hash` matches the client's `If-None-Match`:
```http
HTTP/1.1 304 Not Modified
ETag: "3a7b9c1d..."
Cache-Control: no-cache
Content-Length: 0
```
*Client Action:* Immediately powers off peripherals and enters deep sleep. Wake duration is ~200–400 ms.

#### Response: New Content Ready (`200 OK`)
If the image hash has changed or no `If-None-Match` was sent:
```http
HTTP/1.1 200 OK
Content-Type: image/png
ETag: "8f4e2a1b..."
Cache-Control: no-cache
Content-Length: 194820

<Binary PNG payload (1600x1200)>
```
*Client Action:* Streams PNG data into PSRAM, renders across dual-CS SPI controllers to the display, powers down the panel boost converter, and enters deep sleep.

---

## 4. Detailed InkyPi Server Modifications

### 4.1. Remote Display Driver (`src/display/photoframe_display.py`)
- Subclasses `AbstractDisplay`.
- `initialize_display()`: Verifies that output directory exists and sets ready state without calling hardware GPIO/SPI.
- `display_image(image, image_settings)`: Accepts Pillow image object, ensures correct format, and saves to configured image file path (`current_image.png`).

### 4.2. Display Manager (`src/display/display_manager.py`)
- Add support for `"photoframe"` display type.
- Handle image orientation and resolution scaling to target resolution (`[1600, 1200]`).
- Do not require RPi libraries when `"photoframe"` is active.

### 4.3. PhotoFrame Blueprint (`src/blueprints/photoframe.py`)
- Route: `GET /api/photoframe/image`
  - Ingests telemetry (`battery`, `percent`, `rssi`) from headers or query parameters and stores in `device_config.refresh_info`.
  - Reads `current_image_file` and current `image_hash`.
  - Evaluates `If-None-Match` against `image_hash`.
  - Returns `304` or `200` with appropriate headers.
- Route: `GET /api/photoframe/status`
  - Returns JSON describing current display state:
    ```json
    {
      "image_hash": "3a7b9c1d...",
      "last_refresh_time": "2026-10-05T18:30:00",
      "remote_client": {
        "last_seen": "2026-10-05T18:30:12",
        "battery_voltage": 4.12,
        "battery_percent": 94,
        "wifi_rssi": -62
      }
    }
    ```

### 4.4. Model & Configuration (`src/model.py`, `src/config.py`)
- Extend `RefreshInfo` to include:
  - `remote_client_last_seen` (str/ISO datetime)
  - `remote_client_battery_voltage` (float)
  - `remote_client_battery_percent` (int)
  - `remote_client_wifi_rssi` (int)
- Add `"photoframe"` display configuration presets in `device_dev.json` and `device.json`.

### 4.5. Web UI Updates
- `src/templates/settings.html`: Add "Remote PhotoFrame (Wi-Fi ESP32)" option. When selected, displays the feed URL for copy-pasting into the ESP32.
- `src/templates/inky.html`: Show remote client battery status and Wi-Fi signal strength when operating in PhotoFrame mode.

---

## 5. ESP32 Firmware Setup (XIAO EE02)

1. **Firmware Selection:**
   - Official `aitjcize/esp32-photoframe` merged binary for `seeedstudio_xiao_ee02`.
2. **Flashing via Serial:**
   - Target port: `/dev/ttyACM0`
   - Flashed via `esptool.py` with 460800 baud.
3. **Provisioning:**
   - ESP32 boots into provisioning AP.
   - User inputs Wi-Fi SSID/password.
   - Mode set to `Image Server`.
   - Server URL configured to `http://<server-ip>:<port>/api/photoframe/image`.
   - Wake interval set (e.g., 30 or 60 minutes).

---

## 6. Error Handling & Robustness

- **Server Offline / Unreachable:** ESP32 fails back to deep sleep after connection timeout (10 seconds) to avoid draining battery searching for Wi-Fi.
- **InkyPi Image Generation Failure:** If a plugin fails during refresh, the last successfully generated image remains cached; the server continues serving the valid cached image.
- **Low Battery Warning:** When battery drops below 15%, InkyPi records a low battery warning in the status API and dashboard.

---

## 7. Verification Plan

1. **Unit & Integration Tests:**
   - Verify `PhotoframeDisplay` initializes and saves images properly in headless environment.
   - Verify `GET /api/photoframe/image` returns `200 OK` on first request with `ETag`.
   - Verify sending `If-None-Match` matching current hash returns `304 Not Modified` with zero content length.
   - Verify telemetry headers update `device_config.refresh_info` and reflect in `/api/photoframe/status`.
2. **Hardware Flashing & Live Test:**
   - Flash `seeedstudio_xiao_ee02` firmware over `/dev/ttyACM0`.
   - Verify Wi-Fi provisioning and first image fetch from InkyPi server.
   - Confirm screen refresh and subsequent 304 cache hits in InkyPi server logs.
