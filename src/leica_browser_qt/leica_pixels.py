"""Real Leica pixel readers backed by ConvertLeica metadata offsets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .models import LeicaImageContext


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _dtype_from_bits(bits: Any) -> np.dtype:
    bit_count = _as_int(bits, 8)
    if bit_count <= 8:
        return np.dtype("u1")
    if bit_count <= 16:
        return np.dtype("<u2")
    if bit_count <= 32:
        return np.dtype("<u4")
    raise ValueError(f"Unsupported Leica channel resolution: {bits!r} bits")


def _channel_resolution(metadata: dict[str, Any], c: int) -> int:
    resolutions = metadata.get("channelResolution", 8)
    if isinstance(resolutions, list):
        if not resolutions:
            return 8
        index = min(max(c, 0), len(resolutions) - 1)
        return _as_int(resolutions[index], 8)
    return _as_int(resolutions, 8)


def _channel_offset(metadata: dict[str, Any], c: int, bytes_per_pixel: int) -> int:
    offsets = metadata.get("channelbytesinc")
    if isinstance(offsets, list) and c < len(offsets) and offsets[c] is not None:
        return _as_int(offsets[c], 0)
    xs = max(_as_int(metadata.get("xs"), 1), 1)
    ys = max(_as_int(metadata.get("ys"), 1), 1)
    return c * xs * ys * bytes_per_pixel


def _pixel_file_and_base(metadata: dict[str, Any]) -> tuple[Path, int]:
    filetype = str(metadata.get("filetype") or "").lower()
    if filetype == ".lif":
        filename = metadata.get("LIFFile") or metadata.get("LOFFilePath")
        base_pos = _as_int(metadata.get("Position"), 0)
    elif filetype in {".xlef", ".lof"}:
        filename = metadata.get("LOFFilePath") or metadata.get("lof_file_path")
        # ConvertLeica reads LOF image bytes after the 62-byte LOF image header.
        base_pos = _as_int(metadata.get("Position"), 62)
    else:
        raise ValueError(f"Unsupported Leica filetype for pixel reading: {filetype!r}")

    if not filename:
        raise ValueError("Leica pixel metadata does not contain a source pixel file path")
    path = Path(str(filename))
    if not path.exists():
        raise FileNotFoundError(f"Leica pixel file does not exist: {path}")
    return path, base_pos


def _bounded_index(name: str, value: int, size: int) -> int:
    size = max(int(size), 1)
    index = int(value)
    if index < 0 or index >= size:
        raise IndexError(f"{name} index {index} out of range for size {size}")
    return index


def _plane_offset(
    metadata: dict[str, Any],
    *,
    c: int,
    z: int,
    t: int,
    tile: int,
    bytes_per_pixel: int,
) -> int:
    _, base_pos = _pixel_file_and_base(metadata)
    return (
        base_pos
        + tile * _as_int(metadata.get("tilesbytesinc"), 0)
        + t * _as_int(metadata.get("tbytesinc"), 0)
        + z * _as_int(metadata.get("zbytesinc"), 0)
        + _channel_offset(metadata, c, bytes_per_pixel)
    )


def _read_strided_plane(
    filename: Path,
    *,
    offset: int,
    shape: tuple[int, int],
    dtype: np.dtype,
    strides: tuple[int, int],
) -> np.ndarray:
    ys, xs = shape
    last_byte = (
        offset
        + (ys - 1) * strides[0]
        + (xs - 1) * strides[1]
        + dtype.itemsize
    )
    file_size = filename.stat().st_size
    if offset < 0 or last_byte > file_size:
        raise ValueError(
            "Leica pixel plane extends beyond the source file "
            f"({filename}, offset={offset}, needed={last_byte}, size={file_size})"
        )
    mmap = np.memmap(filename, dtype=np.uint8, mode="r")
    try:
        view = np.ndarray(
            shape,
            dtype=dtype,
            buffer=mmap,
            offset=offset,
            strides=strides,
        )
        return np.asarray(view).copy()
    finally:
        del mmap


def read_leica_plane(
    context: LeicaImageContext,
    *,
    z: int = 0,
    c: int = 0,
    t: int = 0,
    tile: int = 0,
) -> np.ndarray:
    """Read one real Leica plane as a 2-D NumPy array."""

    metadata = context.metadata
    xs = max(_as_int(metadata.get("xs"), context.size_x or 1), 1)
    ys = max(_as_int(metadata.get("ys"), context.size_y or 1), 1)
    size_z = max(_as_int(metadata.get("zs"), context.size_z or 1), 1)
    size_t = max(_as_int(metadata.get("ts"), context.size_t or 1), 1)
    size_tiles = max(_as_int(metadata.get("tiles"), 1), 1)
    size_c = 3 if bool(metadata.get("isrgb")) else max(
        _as_int(metadata.get("channels"), context.size_c or 1),
        1,
    )

    c = _bounded_index("channel", c, size_c)
    z = _bounded_index("z", z, size_z)
    t = _bounded_index("time", t, size_t)
    tile = _bounded_index("tile", tile, size_tiles)

    dtype = _dtype_from_bits(_channel_resolution(metadata, c))
    filename, _ = _pixel_file_and_base(metadata)

    if bool(metadata.get("isrgb")):
        offset = _plane_offset(
            metadata,
            c=0,
            z=z,
            t=t,
            tile=tile,
            bytes_per_pixel=dtype.itemsize,
        ) + c * dtype.itemsize
        x_stride = dtype.itemsize * 3
        y_stride = _as_int(metadata.get("ybytesinc"), xs * x_stride)
    else:
        offset = _plane_offset(
            metadata,
            c=c,
            z=z,
            t=t,
            tile=tile,
            bytes_per_pixel=dtype.itemsize,
        )
        x_stride = _as_int(metadata.get("xbytesinc"), dtype.itemsize)
        y_stride = _as_int(metadata.get("ybytesinc"), xs * x_stride)

    return _read_strided_plane(
        filename,
        offset=offset,
        shape=(ys, xs),
        dtype=dtype,
        strides=(y_stride, x_stride),
    )


def read_leica_stack(
    context: LeicaImageContext,
    *,
    c: int = 0,
    t: int = 0,
    tile: int = 0,
    progress=None,
) -> np.ndarray:
    """Read one channel/timepoint stack as ``ZYX``."""

    size_z = max(_as_int(context.metadata.get("zs"), context.size_z or 1), 1)
    planes = []
    for z in range(size_z):
        planes.append(read_leica_plane(context, z=z, c=c, t=t, tile=tile))
        if progress is not None:
            progress(z + 1, size_z)
    return np.stack(planes, axis=0)


def read_leica_array(context: LeicaImageContext, *, tile: int = 0, progress=None) -> np.ndarray:
    """Read a full Leica image as a NumPy array with shape ``TCZYX``."""

    metadata = context.metadata
    size_t = max(_as_int(metadata.get("ts"), context.size_t or 1), 1)
    size_c = 3 if bool(metadata.get("isrgb")) else max(
        _as_int(metadata.get("channels"), context.size_c or 1),
        1,
    )
    total = max(size_t * size_c, 1)
    stacks = []
    done = 0
    for t in range(size_t):
        channel_stacks = []
        for c in range(size_c):
            channel_stacks.append(read_leica_stack(context, c=c, t=t, tile=tile))
            done += 1
            if progress is not None:
                progress(done, total)
        stacks.append(np.stack(channel_stacks, axis=0))
    return np.stack(stacks, axis=0)
