import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from leica_browser_qt import LeicaBrowserDialog, LeicaGateway
from leica_browser_qt.leica_gateway import LeicaTreeNode
from leica_browser_qt.models import LeicaImageContext

_APP = None


class StaticGateway(LeicaGateway):
    def __init__(self):
        super().__init__()
        self.hydrate_calls = 0

    def container_node(self, path):
        path = Path(path)
        ctx1 = LeicaImageContext(
            name="Image 1",
            container_path=path,
            internal_path="a.lif/Image 1",
            image_id="1",
            kind="lif-image",
            metadata={"xs": 1, "ys": 1},
        )
        ctx2 = LeicaImageContext(
            name="Image 2",
            container_path=path,
            internal_path="a.lif/Image 2",
            image_id="2",
            kind="lif-image",
            metadata={"xs": 1, "ys": 1},
        )
        return LeicaTreeNode(
            name=path.name,
            kind="container",
            path=path,
            children=[
                LeicaTreeNode(name="Image 1", kind="lif-image", context=ctx1),
                LeicaTreeNode(name="Image 2", kind="lif-image", context=ctx2),
            ],
        )

    def hydrate_image_node(self, node):
        self.hydrate_calls += 1
        return super().hydrate_image_node(node)


def app():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def test_gui_instantiates_single_mode(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=StaticGateway())
    try:
        dialog.load_file_images(lif)

        assert dialog.selection_mode == "single"
        assert dialog.tree_fs.topLevelItemCount() == 1
        assert dialog.tree_images.topLevelItemCount() == 1
    finally:
        dialog.close()


def test_multi_select_returns_list(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="multiple", gateway=StaticGateway())
    try:
        dialog.load_file_images(lif)

        root = dialog.tree_images.topLevelItem(0)
        first = root.child(0)
        second = root.child(1)
        first.setSelected(True)
        second.setSelected(True)

        contexts = dialog.selected_contexts()

        assert [ctx.name for ctx in contexts] == ["Image 1", "Image 2"]
    finally:
        if dialog._preview_worker is not None:
            dialog._preview_worker.wait(3000)
        dialog.close()


def test_selecting_image_does_not_hydrate_full_metadata(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    gateway = StaticGateway()
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=gateway)
    try:
        dialog.load_file_images(lif)

        root = dialog.tree_images.topLevelItem(0)
        root.child(0).setSelected(True)
        app().processEvents()

        assert gateway.hydrate_calls == 0
    finally:
        if dialog._preview_worker is not None:
            dialog._preview_worker.wait(3000)
        dialog.close()


def test_source_checkout_is_not_used_as_remembered_root(tmp_path):
    app()
    source_root = tmp_path / "repo"
    (source_root / "src" / "leica_browser_qt").mkdir(parents=True)
    (source_root / "pyproject.toml").write_text("[project]\nname = 'leica-browser-qt'\n")
    (source_root / "plan_leica_browser_qt.md").write_text("plan")

    dialog = LeicaBrowserDialog(selection_mode="single", gateway=StaticGateway())
    try:
        dialog._settings.setValue("last_root", str(source_root))
        assert dialog._initial_root(None) == Path.home()
    finally:
        dialog.close()


def test_unreadable_remembered_root_falls_back_home(tmp_path, monkeypatch):
    app()
    remembered = tmp_path / "remembered"
    remembered.mkdir()

    dialog = LeicaBrowserDialog(selection_mode="single", gateway=StaticGateway())
    try:
        dialog._settings.setValue("last_root", str(remembered))
        monkeypatch.setattr(
            "leica_browser_qt.leica_browser_dialog.os.access",
            lambda path, mode: False if Path(path) == remembered else True,
        )
        assert dialog._initial_root(None) == Path.home()
    finally:
        dialog.close()
