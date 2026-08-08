"""Redshift-specific handlers and runtime capability checks."""

from .capabilities import handle_rs_get_capabilities
from .materials import handle_rs_create_material

REDSHIFT_HANDLERS = {
    "rs_get_capabilities": handle_rs_get_capabilities,
    "rs_create_material": handle_rs_create_material,
}

__all__ = ["REDSHIFT_HANDLERS"]
