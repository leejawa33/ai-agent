import importlib
import pkgutil
from pathlib import Path

from .base import REGISTRY

_pkg_path = Path(__file__).resolve().parent
for module_info in pkgutil.iter_modules([str(_pkg_path)]):
    if module_info.name.endswith("_tool"):
        importlib.import_module(f"tools.{module_info.name}")

TOOLS = REGISTRY
