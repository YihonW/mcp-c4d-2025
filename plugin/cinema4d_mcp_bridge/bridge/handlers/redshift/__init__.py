"""Redshift-specific handlers and runtime capability checks."""

from .aovs import (
    handle_rs_clear_aovs,
    handle_rs_list_aovs,
    handle_rs_remove_aov,
    handle_rs_upsert_aov,
)
from .camera import handle_rs_set_camera
from .capabilities import handle_rs_get_capabilities
from .lights import handle_rs_create_light
from .materials import handle_rs_create_material, handle_rs_set_material_pbr
from .render import handle_rs_configure_render

REDSHIFT_HANDLERS = {
    "rs_get_capabilities": handle_rs_get_capabilities,
    "rs_create_light": handle_rs_create_light,
    "rs_set_camera": handle_rs_set_camera,
    "rs_create_material": handle_rs_create_material,
    "rs_set_material_pbr": handle_rs_set_material_pbr,
    "rs_list_aovs": handle_rs_list_aovs,
    "rs_upsert_aov": handle_rs_upsert_aov,
    "rs_remove_aov": handle_rs_remove_aov,
    "rs_clear_aovs": handle_rs_clear_aovs,
    "rs_configure_render": handle_rs_configure_render,
}

__all__ = ["REDSHIFT_HANDLERS"]
