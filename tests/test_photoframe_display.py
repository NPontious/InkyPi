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
