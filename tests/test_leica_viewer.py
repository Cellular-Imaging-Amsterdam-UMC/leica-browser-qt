import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from leica_browser_qt import LeicaImageContext, LeicaViewerWindow

_APP = None


def app():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def test_viewer_instantiates_without_real_leica_data():
    app()
    ctx = LeicaImageContext(
        name="Preview",
        container_path=Path("sample.lif"),
        internal_path="sample.lif/Preview",
        image_id="preview",
        kind="lif-image",
        size_x=128,
        size_y=96,
        size_z=3,
        size_c=2,
        size_t=1,
        pixel_size_x_um=0.25,
        channel_names=["Green", "Magenta"],
        metadata={"xs": 128, "ys": 96, "zs": 3, "channels": 2},
    )

    win = LeicaViewerWindow(ctx)
    try:
        app().processEvents()
        assert win.windowTitle() == "Leica Viewer"
        assert win._provider is not None
        assert len(win._channel_buttons) == 2
    finally:
        win.close()
