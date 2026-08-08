"""Redshift-specific handlers and runtime capability checks."""

from .camera import handle_rs_set_camera
from .capabilities import handle_rs_get_capabilities
from .lights import handle_rs_create_light
from .materials import handle_rs_create_material, handle_rs_set_material_pbr

REDSHIFT_HANDLERS = {
    "rs_get_capabilities": handle_rs_get_capabilities,
    "rs_create_light": handle_rs_create_light,
    "rs_set_camera": handle_rs_set_camera,
    "rs_create_material": handle_rs_create_material,
    "rs_set_material_pbr": handle_rs_set_material_pbr,
}

__all__ = ["REDSHIFT_HANDLERS"]
