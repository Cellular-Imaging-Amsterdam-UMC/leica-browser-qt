from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import Any


def cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "leica_browser_qt_preview_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_create_preview_image():
    """Load ConvertLeica-Docker's preview helper when it is importable.

    This adapter intentionally mirrors the call pattern used by
    ConvertLeicaQT.py while keeping the new browser package independent from
    the conversion UI. ConvertLeica-Docker is licensed under Apache-2.0.
    """

    for module_name in (
        "leica_browser_qt._convertleica_backend.CreatePreview",
        "CreatePreview",
        "leica_browser_qt_ext.CreatePreview",
    ):
        try:
            module = importlib.import_module(module_name)
            return getattr(module, "create_preview_image")
        except (ImportError, AttributeError):
            continue
    return None


def preview_png_from_metadata(
    metadata: dict[str, Any],
    *,
    selected_s: int | None = None,
    preview_height: int = 512,
    use_memmap: bool = True,
    max_cache_size: int = 500,
) -> Path:
    metadata = dict(metadata)
    if selected_s is None:
        metadata.pop("selected_s", None)
    else:
        metadata["selected_s"] = int(selected_s)
    create_preview_image = _load_create_preview_image()
    if create_preview_image is None:
        raise RuntimeError(
            "Preview backend is unavailable. Install or expose ConvertLeica-Docker's "
            "CreatePreview.py on PYTHONPATH to enable Leica pixel previews."
        )
    path = create_preview_image(
        metadata,
        str(cache_dir()),
        preview_height=int(preview_height),
        use_memmap=bool(use_memmap),
        max_cache_size=int(max_cache_size),
    )
    return Path(path)
