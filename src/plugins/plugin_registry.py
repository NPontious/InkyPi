import os
import sys
import importlib
import importlib.util
import logging
from pathlib import Path
from utils.app_utils import resolve_path

logger = logging.getLogger(__name__)
PLUGINS_DIR = 'plugins'
PLUGIN_CLASSES = {}


def get_plugin_search_paths():
    """Returns list of Path directories to search for plugins."""
    paths = [Path(resolve_path(PLUGINS_DIR))]
    extra_paths = os.getenv("INKYPI_PLUGIN_PATH", "")
    if extra_paths:
        for p in extra_paths.split(":"):
            clean_p = p.strip()
            if clean_p and os.path.isdir(clean_p):
                paths.append(Path(clean_p))
    return paths


def load_plugins(plugins_config):
    search_paths = get_plugin_search_paths()

    # Add extra plugin search paths to sys.path so modules can be imported
    for p in search_paths:
        str_p = str(p)
        if str_p not in sys.path:
            sys.path.insert(0, str_p)

    for plugin in plugins_config:
        plugin_id = plugin.get('id')
        if plugin.get("disabled", False):
            logger.info(f"Plugin {plugin_id} is disabled, skipping.")
            continue

        plugin_dir = None
        module_path = None
        is_builtin = False

        for base_path in search_paths:
            candidate_dir = base_path / plugin_id
            candidate_file = candidate_dir / f"{plugin_id}.py"
            if candidate_dir.is_dir() and candidate_file.is_file():
                plugin_dir = candidate_dir
                module_path = candidate_file
                if base_path == Path(resolve_path(PLUGINS_DIR)):
                    is_builtin = True
                break

        if not plugin_dir or not module_path:
            logger.error(f"Could not find plugin directory or module for '{plugin_id}', skipping.")
            continue

        try:
            if is_builtin:
                module_name = f"plugins.{plugin_id}.{plugin_id}"
                module = importlib.import_module(module_name)
            else:
                # Import as a package since base_path is in sys.path
                module_name = f"{plugin_id}.{plugin_id}"
                module = importlib.import_module(module_name)

            plugin_class = getattr(module, plugin.get("class"), None)
            if plugin_class:
                PLUGIN_CLASSES[plugin_id] = plugin_class(plugin)
                logger.info(f"Loaded plugin '{plugin_id}' successfully.")

        except Exception as e:
            logger.error(f"Failed to import plugin module '{plugin_id}': {e}", exc_info=True)


def register_plugin_blueprints(app):
    """Registers Flask blueprints exposed by plugins via get_blueprint()."""
    for plugin_id, plugin_instance in PLUGIN_CLASSES.items():
        try:
            if hasattr(plugin_instance, 'get_blueprint'):
                bp = plugin_instance.get_blueprint()
                if bp:
                    app.register_blueprint(bp)
                    logger.info(f"Registered custom blueprint for plugin '{plugin_id}'")
            elif hasattr(type(plugin_instance), 'get_blueprint'):
                bp = type(plugin_instance).get_blueprint()
                if bp:
                    app.register_blueprint(bp)
                    logger.info(f"Registered custom blueprint for plugin '{plugin_id}'")
        except Exception as e:
            logger.warning(f"Failed to register blueprint for plugin '{plugin_id}': {e}")


def get_plugin_instance(plugin_config):
    plugin_id = plugin_config.get("id")
    # Retrieve the plugin class factory function
    plugin_class = PLUGIN_CLASSES.get(plugin_id)
    
    if plugin_class:
        # Initialize the plugin with its configuration
        return plugin_class
    else:
        raise ValueError(f"Plugin '{plugin_id}' is not registered.")