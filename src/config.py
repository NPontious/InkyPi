import os
import json
import logging
from dotenv import load_dotenv
from model import PlaylistManager, RefreshInfo

logger = logging.getLogger(__name__)

class Config:
    # Base path for the project directory
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # File paths relative to the script's directory
    config_file = os.path.join(BASE_DIR, "config", "device.json")
    state_dir = BASE_DIR

    # File path for storing the current image being displayed
    current_image_file = os.path.join(BASE_DIR, "static", "images", "current_image.png")

    # Directory path for storing plugin instance images
    plugin_image_dir = os.path.join(BASE_DIR, "static", "images", "plugins")

    declarative_mode = False

    def __init__(self, config_file=None, state_dir=None, declarative_mode=None):
        if config_file is not None:
            self.config_file = config_file
        elif os.getenv("INKYPI_CONFIG"):
            self.config_file = os.getenv("INKYPI_CONFIG")

        if state_dir is not None:
            self.state_dir = state_dir
        elif os.getenv("INKYPI_STATE_DIR"):
            self.state_dir = os.getenv("INKYPI_STATE_DIR")

        if declarative_mode is not None:
            self.declarative_mode = declarative_mode
        elif os.getenv("INKYPI_DECLARATIVE"):
            self.declarative_mode = os.getenv("INKYPI_DECLARATIVE").lower() in ("1", "true", "yes")

        # Resolve image paths relative to state_dir
        if self.state_dir != self.BASE_DIR:
            self.current_image_file = os.path.join(self.state_dir, "images", "current_image.png")
            self.plugin_image_dir = os.path.join(self.state_dir, "images", "plugins")

        # Ensure state directories exist
        os.makedirs(os.path.dirname(self.current_image_file), exist_ok=True)
        os.makedirs(self.plugin_image_dir, exist_ok=True)

        self.config = self.read_config()
        self.plugins_list = self.read_plugins_list()
        self.playlist_manager = self.load_playlist_manager()
        self.refresh_info = self.load_refresh_info()

    def _expand_env_vars(self, obj):
        """Recursively expand environment variables in string values."""
        if isinstance(obj, str):
            return os.path.expandvars(obj)
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(elem) for elem in obj]
        return obj

    def read_config(self):
        """Reads the device config JSON file and returns it as a dictionary."""
        logger.debug(f"Reading device config from {self.config_file}")
        with open(self.config_file) as f:
            config = json.load(f)

        config = self._expand_env_vars(config)

        logger.debug("Loaded config:\n%s", json.dumps(config, indent=3))

        return config

    def read_plugins_list(self):
        """Reads the plugin-info.json config JSON from each plugin folder across search paths."""
        from plugins.plugin_registry import get_plugin_search_paths
        plugins_list = []
        seen_ids = set()

        for base_path in get_plugin_search_paths():
            if not base_path.is_dir():
                continue
            for plugin in sorted(os.listdir(str(base_path))):
                plugin_path = base_path / plugin
                if plugin_path.is_dir() and plugin != "__pycache__":
                    plugin_info_file = plugin_path / "plugin-info.json"
                    if plugin_info_file.is_file():
                        logger.debug(f"Reading plugin info from {plugin_info_file}")
                        try:
                            with open(plugin_info_file) as f:
                                plugin_info = json.load(f)
                            plugin_id = plugin_info.get("id")
                            if plugin_id and plugin_id not in seen_ids:
                                seen_ids.add(plugin_id)
                                plugins_list.append(plugin_info)
                        except Exception as e:
                            logger.error(f"Failed to read {plugin_info_file}: {e}")

        return plugins_list

    def write_config(self):
        """Updates the cached config from the model objects and writes to the config file."""
        self.update_value("playlist_config", self.playlist_manager.to_dict())
        self.update_value("refresh_info", self.refresh_info.to_dict())

        if self.declarative_mode:
            logger.debug("Declarative mode active: skipping disk write to config_file")
            return

        logger.debug(f"Writing device config to {self.config_file}")
        with open(self.config_file, 'w') as outfile:
            json.dump(self.config, outfile, indent=4)

    def get_config(self, key=None, default={}):
        """Gets the value of a specific configuration key or returns the entire config if none provided."""
        if key is not None:
            return self.config.get(key, default)
        return self.config

    def get_plugins(self):
        """Returns the list of plugin configurations, sorted by custom order if set."""
        plugin_order = self.config.get('plugin_order', [])

        if not plugin_order:
            return self.plugins_list

        # Create a dict for quick lookup
        plugins_dict = {p['id']: p for p in self.plugins_list}

        # Build ordered list
        ordered = []
        for plugin_id in plugin_order:
            if plugin_id in plugins_dict:
                ordered.append(plugins_dict.pop(plugin_id))

        # Append any remaining plugins not in the order (new plugins)
        ordered.extend(plugins_dict.values())

        return ordered

    def set_plugin_order(self, order):
        """Sets the custom plugin display order."""
        self.update_value('plugin_order', order, write=True)

    def get_plugin(self, plugin_id):
        """Finds and returns a plugin config by its ID."""
        return next((plugin for plugin in self.plugins_list if plugin['id'] == plugin_id), None)

    def get_resolution(self):
        """Returns the display resolution as a tuple (width, height) from the configuration."""
        resolution = self.get_config("resolution")
        width, height = resolution
        return (int(width), int(height))

    def update_config(self, config):
        """Updates the config with the new values provided and writes to the config file."""
        self.config.update(config)
        self.write_config()

    def update_value(self, key, value, write=False):
        """Updates a specific key in the configuration with a new value and optionally writes it to the config file."""
        self.config[key] = value
        if write:
            self.write_config()

    def load_env_key(self, key):
        """Loads an environment variable using os.environ first, falling back to dotenv."""
        val = os.getenv(key)
        if val is not None:
            return val
        load_dotenv(override=True)
        return os.getenv(key)

    def load_playlist_manager(self):
        """Loads the playlist manager object from the config."""
        playlist_manager = PlaylistManager.from_dict(self.get_config("playlist_config"))
        if not playlist_manager.playlists:
            playlist_manager.add_default_playlist()
        return playlist_manager

    def load_refresh_info(self):
        """Loads the refresh information from the config."""
        return RefreshInfo.from_dict(self.get_config("refresh_info"))

    def get_playlist_manager(self):
        """Returns the playlist manager."""
        return self.playlist_manager

    def get_refresh_info(self):
        """Returns the refresh information."""
        return self.refresh_info
