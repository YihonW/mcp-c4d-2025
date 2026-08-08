"""Read-only Redshift runtime capability handler."""

from __future__ import annotations

from typing import Any

import c4d

from ._helpers import RS_NODE_SPACE_ID, RS_RENDERER_ID, probe_redshift


def handle_rs_get_capabilities(_params: dict[str, Any]) -> dict[str, Any]:
    snapshot = probe_redshift()
    return {
        "c4d_version": int(c4d.GetC4DVersion()),
        "renderer_id": RS_RENDERER_ID,
        "node_space_id": RS_NODE_SPACE_ID,
        **snapshot,
    }
