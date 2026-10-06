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
    config_data = {"playlist_config": {"playlists": []}, "refresh_info": {}}
    config_file = tmp_path / "dummy.json"
    config_file.write_text(json.dumps(config_data))
    cfg = Config(config_file=str(config_file), state_dir=str(tmp_path))
    assert cfg.load_env_key("TEST_API_KEY") == "secret_from_env"


def test_config_env_var_expansion(monkeypatch, tmp_path):
    monkeypatch.setenv("CALENDAR_SECRET_URL", "https://secret.calendar/feed.ics")
    config_data = {
        "playlist_config": {
            "playlists": [{
                "name": "Default",
                "plugins": [{
                    "id": "dashboard",
                    "settings": {
                        "calendarURLs[]": ["$CALENDAR_SECRET_URL"],
                        "otherKey": "${CALENDAR_SECRET_URL}/extra"
                    }
                }]
            }]
        },
        "refresh_info": {}
    }
    config_file = tmp_path / "env_device.json"
    config_file.write_text(json.dumps(config_data))
    cfg = Config(config_file=str(config_file), state_dir=str(tmp_path))
    dashboard_settings = cfg.get_config("playlist_config")["playlists"][0]["plugins"][0]["settings"]
    assert dashboard_settings["calendarURLs[]"] == ["https://secret.calendar/feed.ics"]
    assert dashboard_settings["otherKey"] == "https://secret.calendar/feed.ics/extra"

