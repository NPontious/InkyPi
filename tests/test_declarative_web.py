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
        "name": "Declarative InkyPi",
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
    resp = client.post("/save_settings", data={"orientation": 180})
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
