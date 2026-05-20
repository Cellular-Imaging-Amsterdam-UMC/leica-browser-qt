from pathlib import Path

import numpy as np

from leica_browser_qt import LeicaImageContext


def _write_plane(buffer: bytearray, offset: int, plane: np.ndarray, row_stride: int) -> None:
    for row_index, row in enumerate(np.asarray(plane, dtype=np.uint16)):
        start = offset + row_index * row_stride
        buffer[start : start + row.nbytes] = row.astype("<u2").tobytes()


def test_handle_reads_real_lof_planes_stacks_and_array(tmp_path: Path):
    xs, ys, zs, ts, channels = 3, 2, 2, 2, 2
    itemsize = 2
    row_stride = 8
    plane_span = row_stride * ys
    base = 62
    data = np.arange(ts * channels * zs * ys * xs, dtype=np.uint16).reshape(
        ts, channels, zs, ys, xs
    )
    raw = bytearray(base + ts * zs * channels * plane_span)
    for t in range(ts):
        for z in range(zs):
            for c in range(channels):
                offset = base + t * (zs * channels * plane_span) + z * (
                    channels * plane_span
                ) + c * plane_span
                _write_plane(raw, offset, data[t, c, z], row_stride)

    pixel_file = tmp_path / "sample.lof"
    pixel_file.write_bytes(raw)
    ctx = LeicaImageContext(
        name="sample",
        container_path=pixel_file,
        internal_path="sample",
        image_id="__LOF__",
        kind="lof-image",
        size_x=xs,
        size_y=ys,
        size_z=zs,
        size_c=channels,
        size_t=ts,
        metadata={
            "filetype": ".lof",
            "LOFFilePath": str(pixel_file),
            "xs": xs,
            "ys": ys,
            "zs": zs,
            "ts": ts,
            "channels": channels,
            "channelResolution": [16, 16],
            "channelbytesinc": [0, plane_span],
            "xbytesinc": itemsize,
            "ybytesinc": row_stride,
            "zbytesinc": channels * plane_span,
            "tbytesinc": zs * channels * plane_span,
        },
    )

    handle = ctx.open()

    assert np.array_equal(handle.read_plane(c=1, z=1, t=1), data[1, 1, 1])
    assert np.array_equal(handle.read_stack(c=0, t=1), data[1, 0])
    assert np.array_equal(handle.read_array(), data)


def test_handle_rejects_out_of_range_channel(tmp_path: Path):
    pixel_file = tmp_path / "sample.lof"
    pixel_file.write_bytes(bytes(62 + 4))
    ctx = LeicaImageContext(
        name="sample",
        container_path=pixel_file,
        internal_path="sample",
        image_id="__LOF__",
        kind="lof-image",
        size_x=1,
        size_y=1,
        size_z=1,
        size_c=1,
        size_t=1,
        metadata={
            "filetype": ".lof",
            "LOFFilePath": str(pixel_file),
            "xs": 1,
            "ys": 1,
            "zs": 1,
            "ts": 1,
            "channels": 1,
            "channelResolution": [16],
            "channelbytesinc": [0],
            "xbytesinc": 2,
            "ybytesinc": 2,
        },
    )

    with np.testing.assert_raises(IndexError):
        ctx.open().read_plane(c=1)


def test_handle_reads_specific_s_position_and_context_default(tmp_path: Path):
    xs, ys, zs, ts, channels, tiles = 3, 2, 1, 1, 1, 2
    itemsize = 2
    row_stride = xs * itemsize
    plane_span = row_stride * ys
    base = 62
    data = np.arange(tiles * ts * channels * zs * ys * xs, dtype=np.uint16).reshape(
        tiles, ts, channels, zs, ys, xs
    )
    raw = bytearray(base + tiles * ts * channels * zs * plane_span)
    for tile in range(tiles):
        for t in range(ts):
            for z in range(zs):
                for c in range(channels):
                    offset = (
                        base
                        + tile * (ts * channels * zs * plane_span)
                        + t * (channels * zs * plane_span)
                        + z * (channels * plane_span)
                        + c * plane_span
                    )
                    _write_plane(raw, offset, data[tile, t, c, z], row_stride)

    pixel_file = tmp_path / "sample_tiles.lof"
    pixel_file.write_bytes(raw)
    ctx = LeicaImageContext(
        name="sample",
        container_path=pixel_file,
        internal_path="sample",
        image_id="__LOF__",
        kind="lof-image",
        size_x=xs,
        size_y=ys,
        size_z=zs,
        size_c=channels,
        size_t=ts,
        size_s=tiles,
        selected_s=1,
        metadata={
            "filetype": ".lof",
            "LOFFilePath": str(pixel_file),
            "xs": xs,
            "ys": ys,
            "zs": zs,
            "ts": ts,
            "tiles": tiles,
            "channels": channels,
            "channelResolution": [16],
            "channelbytesinc": [0],
            "xbytesinc": itemsize,
            "ybytesinc": row_stride,
            "zbytesinc": channels * plane_span,
            "tbytesinc": zs * channels * plane_span,
            "tilesbytesinc": ts * zs * channels * plane_span,
        },
    )

    handle = ctx.open()

    assert np.array_equal(handle.read_plane(s=0), data[0, 0, 0, 0])
    assert np.array_equal(handle.read_plane(), data[1, 0, 0, 0])
    assert np.array_equal(handle.read_stack(), data[1, 0, 0])
    assert np.array_equal(handle.read_array(), data[1])


def test_handle_rejects_out_of_range_s_position(tmp_path: Path):
    pixel_file = tmp_path / "sample_tiles.lof"
    pixel_file.write_bytes(bytes(62 + 8))
    ctx = LeicaImageContext(
        name="sample",
        container_path=pixel_file,
        internal_path="sample",
        image_id="__LOF__",
        kind="lof-image",
        size_x=1,
        size_y=1,
        size_z=1,
        size_c=1,
        size_t=1,
        size_s=2,
        metadata={
            "filetype": ".lof",
            "LOFFilePath": str(pixel_file),
            "xs": 1,
            "ys": 1,
            "zs": 1,
            "ts": 1,
            "tiles": 2,
            "channels": 1,
            "channelResolution": [16],
            "channelbytesinc": [0],
            "xbytesinc": 2,
            "ybytesinc": 2,
            "tilesbytesinc": 2,
        },
    )

    with np.testing.assert_raises(IndexError):
        ctx.open().read_plane(s=2)
