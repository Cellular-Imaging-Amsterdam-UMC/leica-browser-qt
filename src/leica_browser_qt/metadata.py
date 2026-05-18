from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .models import LeicaImageContext

SPATIAL_RESOLUTION_AXES = ("x", "y", "z")


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


def unit_to_micrometer_factor(unit: Any) -> float:
    text = str(unit or "").strip().lower()
    if text in {"meter", "metre", "meters", "metres", "m"}:
        return 1_000_000.0
    if text in {"centimeter", "centimetre", "centimeters", "centimetres", "cm"}:
        return 10_000.0
    if text in {"millimeter", "millimetre", "millimeters", "millimetres", "mm"}:
        return 1_000.0
    if text in {"micrometer", "micrometre", "micrometers", "micrometres", "um", "µm"}:
        return 1.0
    if text in {"nanometer", "nanometre", "nanometers", "nanometres", "nm"}:
        return 0.001
    if text in {"inch", "in"}:
        return 25_400.0
    return 1.0


def normalize_resolution_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Repair micrometer-resolution fields when Leica metadata is incomplete."""

    factor = unit_to_micrometer_factor(pick(metadata, "resunit", "xresunit", "unit"))
    for axis in SPATIAL_RESOLUTION_AXES:
        native = as_float(metadata.get(f"{axis}res"))
        converted = as_float(metadata.get(f"{axis}res2"))
        if native is None:
            continue
        expected = native * factor
        if _needs_resolution_fallback(native, converted, factor):
            metadata[f"{axis}res2"] = expected
    if any(f"{axis}res2" in metadata for axis in SPATIAL_RESOLUTION_AXES):
        metadata["resunit2"] = "micrometer"
    return metadata


def _needs_resolution_fallback(native: float, converted: float | None, factor: float) -> bool:
    if converted is None or converted == 0:
        return native != 0
    if factor == 1.0:
        return False
    return abs(converted - native) <= max(abs(native), 1.0) * 1e-12


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
    metadata = normalize_resolution_metadata(metadata)
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
    metadata = normalize_resolution_metadata(metadata)
    rows: list[tuple[str, str]] = []
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, (dict, list)):
            text = repr(value)
        else:
            text = "" if value is None else str(value)
        rows.append((str(key), text))
    return rows


def format_metadata_summary(metadata: dict[str, Any]) -> str:
    """Return the compact metadata summary used by ConvertLeicaQT."""

    metadata = normalize_resolution_metadata(metadata)
    name = pick(metadata, "save_child_name", "name", "ElementName", default="(unnamed)")
    uuid = pick(metadata, "uuid", "UniqueID", "ImageUUID", default="")

    dims = metadata.get("dimensions") if isinstance(metadata.get("dimensions"), dict) else {}
    xs = pick(metadata, "xs", "size_x", default=dims.get("x"))
    ys = pick(metadata, "ys", "size_y", default=dims.get("y"))
    zs = pick(metadata, "zs", "size_z", default=dims.get("z"))
    ts = pick(metadata, "ts", "size_t", default=dims.get("t"))
    cs = pick(metadata, "channels", "size_c", default=dims.get("c"))

    dims_parts = []
    if xs and ys:
        dims_parts.append(f"{xs} x {ys}")
    if zs:
        dims_parts.append(f"Z={zs}")
    if ts:
        dims_parts.append(f"T={ts}")
    if cs:
        dims_parts.append(f"C={cs}")

    vx = pick(metadata, "xres2", "pixel_size_x_um", "PhysicalSizeX")
    vy = pick(metadata, "yres2", "pixel_size_y_um", "PhysicalSizeY")
    vz = pick(metadata, "zres2", "pixel_size_z_um", "PhysicalSizeZ")
    vunit = pick(metadata, "resunit2", default="um")

    def fmt2(value: Any) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return str(value)

    scale_parts = []
    if vx:
        scale_parts.append(f"X={fmt2(vx)} {vunit}")
    if vy:
        scale_parts.append(f"Y={fmt2(vy)} {vunit}")
    if vz:
        scale_parts.append(f"Z={fmt2(vz)} {vunit}")

    is_rgb = bool(pick(metadata, "isrgb", default=False))
    channel_resolution = metadata.get("channelResolution") or []
    pixel_type = None
    if isinstance(channel_resolution, list) and channel_resolution:
        try:
            first = channel_resolution[0]
            pixel_type = (
                f"{first}-bit"
                if all(value == first for value in channel_resolution if value is not None)
                else "mixed-bit"
            )
        except Exception:
            pixel_type = None
    if pixel_type and is_rgb:
        pixel_type = f"{pixel_type} RGB"
    elif is_rgb:
        pixel_type = "RGB"

    lines = [
        f"Name: {name}",
        f"UUID: {uuid}" if uuid else "UUID: (n/a)",
        f"Dimensions: {'  '.join(dims_parts)}" if dims_parts else "Dimensions: (n/a)",
        f"Voxel size: {', '.join(scale_parts)}" if scale_parts else "Voxel size: (n/a)",
        f"Pixel type: {pixel_type}" if pixel_type else "Pixel type: (n/a)",
    ]

    experiment = pick(metadata, "experiment_name")
    if experiment:
        lines.append(f"Experiment: {experiment}")

    date_text = _format_datetime(pick(metadata, "experiment_datetime", "experiment_datetime_str"))
    if date_text:
        lines.append(f"Date: {date_text}")
    return "\n".join(lines)


def _format_datetime(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pretty = raw.replace("T", " ")
        if "." in pretty:
            pretty = pretty.split(".", 1)[0]
        for sep in ("+", "-"):
            pos = pretty.find(sep, 10)
            if pos != -1:
                pretty = pretty[:pos]
                break
        return pretty
