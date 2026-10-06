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
