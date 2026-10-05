import os
import pytest
from PIL import Image
from flask import Flask
from blueprints.photoframe import photoframe_bp
from blueprints.main import main_bp
from model import RefreshInfo

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

    def get_playlist_manager(self):
        return None

@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    config = MockConfig(tmp_path)
    
    # Create a dummy image
    img = Image.new("RGB", (1600, 1200), color=(100, 150, 200))
    img.save(config.current_image_file, format="PNG")

    app.config["DEVICE_CONFIG"] = config
    app.register_blueprint(photoframe_bp)
    app.register_blueprint(main_bp)
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

    # Test X-Battery-Percentage variant
    res2 = c.get(
        "/api/photoframe/image",
        headers={"X-Battery-Percentage": "87"},
    )
    assert res2.status_code == 200
    assert config.refresh_info.remote_client_battery_percent == 87

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


def test_main_status_endpoint(client):
    c, config = client
    # Send telemetry first
    c.get("/api/photoframe/image?battery=4.05&percent=88&rssi=-60")

    res = c.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["device_name"] == "InkyPi Test"
    assert data["remote_client"]["battery_percent"] == 88
    assert data["remote_client"]["battery_voltage"] == 4.05
    assert data["remote_client"]["wifi_rssi"] == -60


def test_photoframe_fallback_image_creates_missing_directory(tmp_path):
    app = Flask(__name__)
    config = MockConfig(tmp_path)
    # Set image path in a deeply nested non-existent directory
    config.current_image_file = str(tmp_path / "deeply" / "nested" / "dir" / "current_image.png")
    app.config["DEVICE_CONFIG"] = config
    app.register_blueprint(photoframe_bp)

    with app.test_client() as c:
        res = c.get("/api/photoframe/image")
        assert res.status_code == 200
        assert os.path.exists(config.current_image_file)



