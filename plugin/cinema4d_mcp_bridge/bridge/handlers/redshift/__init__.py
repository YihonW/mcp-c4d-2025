"""Redshift-specific handlers and runtime capability checks."""

from .capabilities import handle_rs_get_capabilities

REDSHIFT_HANDLERS = {
    "rs_get_capabilities": handle_rs_get_capabilities,
}

__all__ = ["REDSHIFT_HANDLERS"]
