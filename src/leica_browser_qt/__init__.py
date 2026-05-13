"""Reusable PyQt6 browser for Leica LIF, XLEF, and LOF image containers."""

from .api import LeicaBrowserDialog, LeicaGateway, LeicaImageContext, LeicaImageHandle

__all__ = [
    "LeicaBrowserDialog",
    "LeicaGateway",
    "LeicaImageContext",
    "LeicaImageHandle",
    "LeicaViewerWindow",
]


def __getattr__(name: str):
    if name == "LeicaViewerWindow":
        from .leica_viewer import LeicaViewerWindow

        return LeicaViewerWindow
    raise AttributeError(name)
