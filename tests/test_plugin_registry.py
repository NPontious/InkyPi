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

    # api.py with a blueprint
    api_code = """
from flask import Blueprint

bp = Blueprint("custom_addon_bp", __name__)

@bp.route("/api/custom_addon/hello")
def hello():
    return {"status": "ok"}
"""
    (plugin_dir / "api.py").write_text(api_code)

    # custom_addon.py importing api.py via relative import
    code = """
from .api import bp

class CustomAddonPlugin:
    def __init__(self, config):
        self.config = config

    @classmethod
    def get_blueprint(cls):
        return bp
"""
    (plugin_dir / "custom_addon.py").write_text(code)

    # __init__.py to make it a package
    (plugin_dir / "__init__.py").write_text("")

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


def test_external_plugin_config_discovery(tmp_path, monkeypatch):
    from config import Config
    ext_dir = tmp_path / "extra_plugins"
    ext_dir.mkdir()
    plugin_dir = ext_dir / "my_ext"
    plugin_dir.mkdir()
    (plugin_dir / "plugin-info.json").write_text(json.dumps({
        "id": "my_ext",
        "display_name": "My Extension",
        "class": "MyExtension"
    }))

    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps({
        "playlist_config": {"playlists": []},
        "refresh_info": {}
    }))

    monkeypatch.setenv("INKYPI_PLUGIN_PATH", str(ext_dir))
    cfg = Config(config_file=str(config_file))
    plugin_ids = [p["id"] for p in cfg.get_plugins()]
    assert "my_ext" in plugin_ids
    assert cfg.get_plugin("my_ext")["display_name"] == "My Extension"


def test_external_plugin_base_plugin_dir_and_template(tmp_path, monkeypatch):
    from plugins.base_plugin.base_plugin import BasePlugin
    ext_dir = tmp_path / "extra_plugins"
    ext_dir.mkdir()
    plugin_dir = ext_dir / "my_ext"
    plugin_dir.mkdir()
    (plugin_dir / "settings.html").write_text("<div>Custom Plugin Settings</div>")

    monkeypatch.setenv("INKYPI_PLUGIN_PATH", str(ext_dir))
    plugin = BasePlugin({"id": "my_ext"})
    assert plugin.get_plugin_dir() == str(plugin_dir)
    assert plugin.get_plugin_dir("settings.html") == str(plugin_dir / "settings.html")
    template_params = plugin.generate_settings_template()
    assert template_params["settings_template"] == "my_ext/settings.html"


def test_external_plugin_icon_serving(tmp_path, monkeypatch):
    from blueprints.plugin import plugin_bp
    ext_dir = tmp_path / "extra_plugins"
    ext_dir.mkdir()
    plugin_dir = ext_dir / "my_ext"
    plugin_dir.mkdir()
    (plugin_dir / "icon.png").write_bytes(b"dummy_icon_bytes")

    monkeypatch.setenv("INKYPI_PLUGIN_PATH", str(ext_dir))
    app = Flask(__name__)
    app.register_blueprint(plugin_bp)

    client = app.test_client()
    resp = client.get("/images/my_ext/icon.png")
    assert resp.status_code == 200
    assert resp.data == b"dummy_icon_bytes"

    # Directory traversal check
    resp_traversal = client.get("/images/my_ext/../evil.txt")
    assert resp_traversal.status_code in (403, 404)


def test_external_plugin_jinja_template_loading(tmp_path, monkeypatch):
    from jinja2 import Environment, ChoiceLoader, FileSystemLoader
    from plugins.plugin_registry import get_plugin_search_paths

    ext_dir = tmp_path / "extra_plugins"
    ext_dir.mkdir()
    plugin_dir = ext_dir / "my_ext"
    plugin_dir.mkdir()
    (plugin_dir / "settings.html").write_text("<p>Hello from external settings</p>")

    monkeypatch.setenv("INKYPI_PLUGIN_PATH", str(ext_dir))

    template_dirs = [str(p) for p in get_plugin_search_paths() if p.is_dir()]
    loader = ChoiceLoader([FileSystemLoader(d) for d in template_dirs])
    env = Environment(loader=loader)

    template = env.get_template("my_ext/settings.html")
    assert "<p>Hello from external settings</p>" in template.render()


