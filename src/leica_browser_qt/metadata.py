from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import LeicaImageContext


def pick(metadata: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value is not None:
            return value
    return default


def as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def channel_names_from_metadata(metadata: dict[str, Any]) -> list[str]:
    for key in ("channel_names", "channelNames", "channels_names"):
        value = metadata.get(key)
        if isinstance(value, list):
            return [str(v) for v in value]

    lut_names = metadata.get("lutname")
    if isinstance(lut_names, list):
        return [str(v) for v in lut_names]

    count = as_int(metadata.get("channels") or (metadata.get("dimensions") or {}).get("c"))
    if count:
        return [f"Channel {idx + 1}" for idx in range(count)]
    return []


def context_from_metadata(
    *,
    name: str,
    container_path: Path,
    internal_path: str,
    image_id: str | None,
    kind: str,
    metadata: dict[str, Any],
) -> LeicaImageContext:
    dims = metadata.get("dimensions") if isinstance(metadata.get("dimensions"), dict) else {}
    return LeicaImageContext(
        name=name,
        container_path=container_path,
        internal_path=internal_path,
        image_id=image_id,
        kind=kind,
        size_x=as_int(pick(metadata, "xs", "size_x", default=dims.get("x"))),
        size_y=as_int(pick(metadata, "ys", "size_y", default=dims.get("y"))),
        size_z=as_int(pick(metadata, "zs", "size_z", default=dims.get("z"))),
        size_c=as_int(pick(metadata, "channels", "size_c", default=dims.get("c"))),
        size_t=as_int(pick(metadata, "ts", "size_t", default=dims.get("t"))),
        pixel_size_x_um=as_float(pick(metadata, "xres2", "pixel_size_x_um", "PhysicalSizeX")),
        pixel_size_y_um=as_float(pick(metadata, "yres2", "pixel_size_y_um", "PhysicalSizeY")),
        pixel_size_z_um=as_float(pick(metadata, "zres2", "pixel_size_z_um", "PhysicalSizeZ")),
        channel_names=channel_names_from_metadata(metadata),
        metadata=metadata,
    )


def metadata_rows(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, (dict, list)):
            text = repr(value)
        else:
            text = "" if value is None else str(value)
        rows.append((str(key), text))
    return rows

