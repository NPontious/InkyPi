import os
import logging
import threading
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
        Also automatically sends a background push notification to the remote client if reachable.

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

        # Trigger background push notification to remote client if known
        client_ip = None
        if hasattr(self.device_config, "get_refresh_info"):
            refresh_info = self.device_config.get_refresh_info()
            client_ip = getattr(refresh_info, "remote_client_ip", None)
        if not client_ip and hasattr(self.device_config, "get_config"):
            client_ip = self.device_config.get_config("remote_client_ip")

        if client_ip:
            self._notify_remote_client(client_ip)

    def _notify_remote_client(self, client_ip):
        def _send():
            try:
                import requests
                logger.info(f"PhotoframeDisplay: Triggering automatic refresh on client http://{client_ip}/api/rotate")
                requests.post(f"http://{client_ip}/api/rotate", timeout=5)
            except Exception as e:
                logger.debug(f"PhotoframeDisplay: Remote client notification to {client_ip} skipped/failed: {e}")

        threading.Thread(target=_send, daemon=True).start()


