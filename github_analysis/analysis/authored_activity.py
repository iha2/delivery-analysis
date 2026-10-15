"""Compatibility shim: this module moved to delivery_analysis.connectors.github.authored_activity."""
import sys
from importlib import import_module

sys.modules[__name__] = import_module("delivery_analysis.connectors.github.authored_activity")
