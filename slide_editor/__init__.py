from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_BUILD_DIR = Path(__file__).parent / "frontend" / "dist"
_component = components.declare_component("platter_slide_editor", path=_BUILD_DIR)


def slide_editor(
    payload: dict[str, object],
    *,
    selected_slide: int = 0,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Render the Fabric.js editor and return its autosaved layer model."""
    if not (_BUILD_DIR / "index.html").exists():
        raise RuntimeError(
            "The slide editor frontend is not built. Run `npm run build` in slide_editor/frontend."
        )
    return _component(
        payload=payload,
        selected_slide=selected_slide,
        key=key,
        default=None,
    )
