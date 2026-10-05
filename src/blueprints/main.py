from flask import Blueprint, request, jsonify, current_app, render_template, send_file
import os
from datetime import datetime

main_bp = Blueprint("main", __name__)

@main_bp.route('/')
def main_page():
    device_config = current_app.config['DEVICE_CONFIG']
    return render_template('inky.html', config=device_config.get_config(), plugins=device_config.get_plugins(), device_config=device_config)

@main_bp.route('/api/current_image')
def get_current_image():
    """Serve current_image.png with conditional request support (If-Modified-Since)."""
    image_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'images', 'current_image.png')
    
    if not os.path.exists(image_path):
        return jsonify({"error": "Image not found"}), 404
    
    # Get the file's last modified time (truncate to seconds to match HTTP header precision)
    file_mtime = int(os.path.getmtime(image_path))
    last_modified = datetime.fromtimestamp(file_mtime)
    
    # Check If-Modified-Since header
    if_modified_since = request.headers.get('If-Modified-Since')
    if if_modified_since:
        try:
            # Parse the If-Modified-Since header
            client_mtime = datetime.strptime(if_modified_since, '%a, %d %b %Y %H:%M:%S %Z')
            client_mtime_seconds = int(client_mtime.timestamp())
            
            # Compare (both now in seconds, no sub-second precision)
            if file_mtime <= client_mtime_seconds:
                return '', 304
        except (ValueError, AttributeError):
            pass
    
    # Send the file with Last-Modified header
    response = send_file(image_path, mimetype='image/png')
    response.headers['Last-Modified'] = last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')
    response.headers['Cache-Control'] = 'no-cache'
    return response


@main_bp.route('/api/plugin_order', methods=['POST'])
def save_plugin_order():
    """Save the custom plugin order."""
    device_config = current_app.config['DEVICE_CONFIG']

    data = request.get_json() or {}
    order = data.get('order', [])

    if not isinstance(order, list):
        return jsonify({"error": "Order must be a list"}), 400

    device_config.set_plugin_order(order)

    return jsonify({"success": True})


@main_bp.route('/api/status')
def get_status():
    """Returns the current status of InkyPi including remote client telemetry."""
    device_config = current_app.config['DEVICE_CONFIG']

    refresh_info = device_config.get_refresh_info().to_dict()
    playlist_manager = device_config.get_playlist_manager() if hasattr(device_config, 'get_playlist_manager') else None

    status = {
        "device_name": device_config.get_config("name", "InkyPi"),
        "active_playlist": playlist_manager.active_playlist if playlist_manager else None,
        "last_refresh_time": refresh_info.get("refresh_time"),
        "last_plugin_id": refresh_info.get("plugin_id"),
        "last_plugin_instance": refresh_info.get("plugin_instance"),
        "refresh_type": refresh_info.get("refresh_type"),
        "remote_client": {
            "last_seen": refresh_info.get("remote_client_last_seen"),
            "battery_voltage": refresh_info.get("remote_client_battery_voltage"),
            "battery_percent": refresh_info.get("remote_client_battery_percent"),
            "wifi_rssi": refresh_info.get("remote_client_wifi_rssi")
        }
    }

    return jsonify(status)