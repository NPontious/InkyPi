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
    voltage = _parse_float(request.headers.get("X-Battery-Voltage") or request.args.get("battery") or request.args.get("battery_voltage"))
    percent = _parse_int(
        request.headers.get("X-Battery-Percentage")
        or request.headers.get("X-Battery-Percent")
        or request.args.get("percent")
        or request.args.get("battery_level")
    )
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

    client_ip = request.remote_addr
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
        if client_ip and client_ip != "127.0.0.1":
            refresh_info.remote_client_ip = client_ip
            if hasattr(device_config, "update_value"):
                device_config.update_value("remote_client_ip", client_ip)
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
        parent_dir = os.path.dirname(image_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        from PIL import Image
        img = Image.new("RGB", (1600, 1200), color=(255, 255, 255))
        tmp_path = image_path + f".tmp.{os.getpid()}"
        img.save(tmp_path, format="PNG")
        os.replace(tmp_path, image_path)

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
