import os
import logging
try:
    from display.abstract_display import AbstractDisplay
except ImportError:
    from .abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)

class PhotoframeDisplay(AbstractDisplay):
    """
    Display implementation for headless server mode.
    Saves the rendered and processed image to disk for remote Wi-Fi clients (e.g. ESP32).
    """

    def initialize_display(self):
        """Initializes the remote photoframe display storage."""
        logger.info("Initializing Remote PhotoFrame display")
        output_dir = os.path.dirname(self.device_config.current_image_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

    def display_image(self, image, image_settings=[]):
        """
        Saves the processed image to the configured current_image_file path atomically.

        Args:
            image (PIL.Image): The final processed image.
            image_settings (list, optional): Optional image adjustments.
        """
        output_path = self.device_config.current_image_file
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        logger.info(f"PhotoframeDisplay: Writing image atomically to {output_path}")
        tmp_path = output_path + f".tmp.{os.getpid()}"
        image.save(tmp_path, format="PNG")
        os.replace(tmp_path, output_path)

