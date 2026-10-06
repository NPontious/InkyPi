import os
import pytest
from PIL import Image
from display.photoframe_display import PhotoframeDisplay
from display.display_manager import DisplayManager

class DummyConfig:
    def __init__(self, tmp_path):
        self.current_image_file = str(tmp_path / "current_image.png")
        self.config = {
            "display_type": "photoframe",
            "resolution": [1600, 1200],
            "orientation": "horizontal",
            "inverted_image": False,
            "image_settings": {}
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


def test_display_manager_photoframe_transformed_and_atomic(tmp_path):
    conf = DummyConfig(tmp_path)
    conf.config["orientation"] = "vertical"
    conf.config["resolution"] = [1200, 1600]
    dm = DisplayManager(conf)

    raw_img = Image.new("RGB", (800, 600), color=(0, 255, 0))
    dm.display_image(raw_img)

    saved_img = Image.open(conf.current_image_file)
    assert saved_img.size == (1200, 1600)


def test_photoframe_display_notifies_remote_client(tmp_path, monkeypatch):
    conf = DummyConfig(tmp_path)
    conf.config["remote_client_ip"] = "10.0.0.99"
    disp = PhotoframeDisplay(conf)

    called = []
    def mock_post(url, timeout=None):
        called.append((url, timeout))
    monkeypatch.setattr("requests.post", mock_post)

    img = Image.new("RGB", (1600, 1200), color=(10, 20, 30))
    disp.display_image(img)

    # Wait briefly for daemon thread to execute
    import time
    time.sleep(0.1)

    assert len(called) == 1
    assert called[0][0] == "http://10.0.0.99/api/rotate"
    assert called[0][1] == 5


