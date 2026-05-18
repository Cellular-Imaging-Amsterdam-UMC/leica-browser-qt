"""Adapted from NL-BioImaging/ConvertLeica-Docker, Apache-2.0.

Fast, lightweight Leica image XML parser for listing/preview.

Extracts only the minimal metadata needed for UI listing and quick previews:
- dimensions: xs, ys, zs, ts, tiles, channels, isrgb
- pixel sizes: xres, yres, zres and units, plus micrometer-converted xres2/yres2/zres2
- preview offsets: channel/z/t/tile byte increments and channel bit depth
- a consolidated dimensions dict

This intentionally avoids scanning Attachments, LUTs, tiles, hardware info, etc.
Use this when you need snappy folder/image listings. For full details, use
ParseLeicaImageXML.parse_image_xml instead.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET

__all__ = ["parse_image_xml_lite"]


def _unit_to_um_factor(unit: str) -> float:
    u = (unit or "").strip().lower()
    if u in ("meter", "m"):
        return 1e6
    if u in ("centimeter", "cm"):
        return 1e4
    if u in ("millimeter", "mm"):
        return 1e3
    if u in ("micrometer", "um", "µm"):
        return 1.0
    if u in ("inch", "in"):
        return 25400.0
    # Default to micrometers if ambiguous/unknown
    return 1.0


def parse_image_xml_lite(xml_element: ET.Element) -> dict:
    """
    Parse the minimal metadata quickly from a Leica image XML element.

    Returns a dict with keys:
      - UniqueID, ElementName
      - xs, ys, zs, ts, tiles, channels, isrgb
      - xres, yres, zres, resunit, xres2, yres2, zres2, resunit2
      - dimensions: {x,y,z,c,t,s,isrgb}
    """
    meta: dict = {
        "UniqueID": None,
        "ElementName": None,
        # Sizes
        "xs": 1, "ys": 1, "zs": 1, "ts": 1, "tiles": 1,
        "channels": 1,
        "isrgb": False,
        "channelResolution": [],
        "channelbytesinc": [],
        "lutname": [],
        "xbytesinc": 0,
        "ybytesinc": 0,
        "zbytesinc": 0,
        "tbytesinc": 0,
        "tilesbytesinc": 0,
        # Pixel sizes (native units)
        "xres": 0.0, "yres": 0.0, "zres": 0.0,
        "resunit": "",
        # Pixel sizes (micrometers)
        "xres2": 0.0, "yres2": 0.0, "zres2": 0.0, "resunit2": "micrometer",
    }

    # Basic identity
    if xml_element.tag == "Element":
        meta["UniqueID"] = xml_element.attrib.get("UniqueID")
        meta["ElementName"] = xml_element.attrib.get("Name", "")

    # Find ImageDescription quickly; fall back to deep search if needed
    img_desc = xml_element.find("ImageDescription")
    if img_desc is None:
        img_desc = xml_element.find(".//ImageDescription")

    if img_desc is not None:
        # Channels and potential RGB flag
        chs = img_desc.find("Channels")
        if chs is not None:
            ch_descs = chs.findall("ChannelDescription")
            if ch_descs:
                meta["channels"] = len(ch_descs)
                # Heuristic similar to full parser: non-zero ChannelTag in first channel => RGB
                try:
                    ch_tag = ch_descs[0].attrib.get("ChannelTag")
                    if ch_tag is not None and int(ch_tag) != 0:
                        meta["isrgb"] = True
                except Exception:
                    pass
                for ch_desc in ch_descs:
                    meta["channelbytesinc"].append(_as_int(ch_desc.attrib.get("BytesInc")))
                    meta["channelResolution"].append(_as_int(ch_desc.attrib.get("Resolution"), 8))
                    lut = ch_desc.attrib.get("LUTName") or ""
                    meta["lutname"].append(lut.lower())
            else:
                # Sometimes Channels exists but is empty; look for a single ChannelDescription
                one = img_desc.find(".//ChannelDescription")
                if one is not None:
                    meta["channels"] = 1
                    meta["channelbytesinc"].append(_as_int(one.attrib.get("BytesInc")))
                    meta["channelResolution"].append(_as_int(one.attrib.get("Resolution"), 8))
                    lut = one.attrib.get("LUTName") or ""
                    meta["lutname"].append(lut.lower())
        else:
            # No Channels block; try a single ChannelDescription
            one = img_desc.find(".//ChannelDescription")
            if one is not None:
                meta["channels"] = 1
                meta["channelbytesinc"].append(_as_int(one.attrib.get("BytesInc")))
                meta["channelResolution"].append(_as_int(one.attrib.get("Resolution"), 8))
                lut = one.attrib.get("LUTName") or ""
                meta["lutname"].append(lut.lower())

        # Dimensions and pixel size
        dims = img_desc.find("Dimensions")
        if dims is not None:
            for d in dims.findall("DimensionDescription"):
                try:
                    dim_id = int(d.attrib.get("DimID", "0"))
                except Exception:
                    dim_id = 0
                try:
                    n = int(d.attrib.get("NumberOfElements", "0"))
                except Exception:
                    n = 0
                try:
                    length = float(d.attrib.get("Length", "0"))
                except Exception:
                    length = 0.0
                bytes_inc = _as_int(d.attrib.get("BytesInc"))
                unit = d.attrib.get("Unit", meta["resunit"]) or meta["resunit"]
                if unit and not meta["resunit"]:
                    meta["resunit"] = unit
                # Resolution per element (guard when n<=1)
                res = (length / (n - 1)) if n > 1 else 0.0

                if dim_id == 1:  # X
                    meta["xs"] = n
                    meta["xres"] = res
                    meta["xbytesinc"] = bytes_inc
                elif dim_id == 2:  # Y
                    meta["ys"] = n
                    meta["yres"] = res
                    meta["ybytesinc"] = bytes_inc
                elif dim_id == 3:  # Z
                    meta["zs"] = n
                    meta["zres"] = res
                    meta["zbytesinc"] = bytes_inc
                elif dim_id == 4:  # T
                    meta["ts"] = n
                    meta["tbytesinc"] = bytes_inc
                elif dim_id == 10:  # Tiles
                    meta["tiles"] = n
                    meta["tilesbytesinc"] = bytes_inc

    # Convert to micrometers
    factor = _unit_to_um_factor(meta.get("resunit", ""))
    meta["xres2"] = meta["xres"] * factor
    meta["yres2"] = meta["yres"] * factor
    meta["zres2"] = meta["zres"] * factor
    meta["resunit2"] = "micrometer"

    # Consolidated dimensions
    meta["dimensions"] = {
        "x": meta["xs"],
        "y": meta["ys"],
        "z": meta["zs"],
        "c": meta["channels"],
        "t": meta["ts"],
        "s": meta["tiles"],
        "isrgb": meta["isrgb"],
    }
    while len(meta["channelbytesinc"]) < meta["channels"]:
        meta["channelbytesinc"].append(0)
    while len(meta["channelResolution"]) < meta["channels"]:
        meta["channelResolution"].append(8)
    while len(meta["lutname"]) < meta["channels"]:
        meta["lutname"].append("")

    return meta


def _as_int(value, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default
