"""Browser-focused Leica helper functions adapted from ConvertLeica-Docker.

This is a lean subset of ``ci_leica_converters_helpers.py``. It keeps the
reader dispatch and XLEF/LOF metadata merge behavior used by ConvertLeicaQT,
but leaves out conversion, OME schema downloads, and TIFF saving.
"""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .ReadLeicaLIF import read_leica_lif
from .ReadLeicaLOF import read_leica_lof
from .ReadLeicaXLEF import read_leica_xlef


def read_leica_file(
    file_path: str | os.PathLike,
    include_xmlelement: bool = False,
    image_uuid: str | None = None,
    folder_uuid: str | None = None,
):
    """Read Leica LIF, XLEF, or LOF metadata.

    Returns the same JSON-like structures as ConvertLeica-Docker's
    ``read_leica_file``.
    """

    file_path = str(file_path)
    ext = Path(file_path).suffix.lower()
    if ext == ".lif":
        return read_leica_lif(file_path, include_xmlelement, image_uuid, folder_uuid)
    if ext == ".xlef":
        return read_leica_xlef(file_path, folder_uuid)
    if ext == ".lof":
        return read_leica_lof(file_path, include_xmlelement)
    raise ValueError(f"Unsupported file type: {ext}")


def get_image_metadata_LOF(folder_metadata: str, image_uuid: str):
    folder_metadata_dict = json.loads(folder_metadata)
    image_metadata_dict = next(
        (img for img in folder_metadata_dict["children"] if img.get("uuid") == image_uuid),
        None,
    )
    if not image_metadata_dict:
        raise ValueError(f"Image UUID {image_uuid} not found")
    return read_leica_file(image_metadata_dict["lof_file_path"])


def get_image_metadata(folder_metadata: str, image_uuid: str):
    folder_metadata_dict = json.loads(folder_metadata)
    image_metadata_dict = next(
        (img for img in folder_metadata_dict["children"] if img.get("uuid") == image_uuid),
        None,
    )
    if not image_metadata_dict:
        raise ValueError(f"Image UUID {image_uuid} not found")
    return json.dumps(image_metadata_dict, indent=2)


def read_image_metadata(file_path: str | os.PathLike, image_uuid: str | None) -> dict[str, Any]:
    """Return full metadata for one image in a LIF, XLEF, or LOF container."""

    path = Path(file_path)
    ext = path.suffix.lower()
    if ext == ".lif":
        if not image_uuid:
            raise ValueError("LIF image_uuid is required")
        raw = read_leica_file(path, image_uuid=image_uuid)
        meta = json.loads(raw) if isinstance(raw, str) else raw
        meta.setdefault("LIFFile", str(path))
        meta.setdefault("filetype", ".lif")
        return meta
    if ext == ".lof" or image_uuid == "__LOF__":
        raw = read_leica_file(path)
        meta = json.loads(raw) if isinstance(raw, str) else raw
        meta.setdefault("LOFFilePath", str(path))
        meta.setdefault("filetype", ".lof")
        return meta
    if ext == ".xlef":
        if not image_uuid:
            raise ValueError("XLEF image_uuid is required")
        return _read_xlef_image(str(path), image_uuid)
    raise ValueError(f"Unsupported file type: {ext}")


def _read_xlef_image(xlef_path: str, image_uuid: str) -> dict[str, Any]:
    """Return metadata for one image UUID inside an XLEF experiment."""

    start = Path(xlef_path)
    queue: deque[Path] = deque([start])
    seen: set[Path] = set()
    while queue:
        current = queue.popleft().resolve()
        if current in seen:
            continue
        seen.add(current)
        try:
            tree_raw = read_leica_file(current)
            tree = json.loads(tree_raw) if isinstance(tree_raw, str) else tree_raw
        except Exception as exc:
            print(f"Warning: Could not read linked XLEF '{current}': {exc}")
            continue

        found = _find_image_entry(tree, image_uuid)
        if found is not None:
            folder_json = json.dumps({"children": [found]})
            try:
                entry = json.loads(get_image_metadata(folder_json, image_uuid))
                meta = json.loads(get_image_metadata_LOF(folder_json, image_uuid))
                if "save_child_name" in entry:
                    meta["save_child_name"] = entry["save_child_name"]
                meta.setdefault("LOFFilePath", meta.get("lof_file_path", str(current)))
                meta.setdefault("filetype", ".xlef")
                return meta
            except Exception as exc:
                print(f"Warning: Could not read/merge LOF metadata: {exc}")
                fallback = dict(found)
                fallback.setdefault("LOFFilePath", fallback.get("lof_file_path", str(current)))
                fallback.setdefault("filetype", ".xlef")
                return fallback

        for child in tree.get("children", []) or []:
            child_path = child.get("path") or child.get("Path")
            if not child_path:
                continue
            decoded = unquote(str(child_path))
            linked = Path(decoded)
            if not linked.is_absolute():
                linked = current.parent / linked
            if linked.suffix.lower() in {".xlef", ".xlcf", ".xlif"} and linked.exists():
                queue.append(linked)

    raise ValueError(f"Image UUID {image_uuid} not found in {xlef_path} or linked XLEFs")


def _find_image_entry(tree: dict[str, Any], image_uuid: str) -> dict[str, Any] | None:
    for child in tree.get("children", []) or []:
        if child.get("uuid") == image_uuid:
            ctype = str(child.get("type") or "").lower()
            if ctype not in {"folder", "file"}:
                return child
        nested = _find_image_entry(child, image_uuid) if isinstance(child, dict) else None
        if nested is not None:
            return nested
    return None

