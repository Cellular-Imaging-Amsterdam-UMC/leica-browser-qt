import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from leica_browser_qt import LeicaBrowserDialog, LeicaGateway
from leica_browser_qt._convertleica_backend import CreatePreview
from leica_browser_qt.leica_browser_dialog import MAX_RECENT_ROOTS, RECENT_ROOTS_KEY
from leica_browser_qt.leica_gateway import LeicaTreeNode
from leica_browser_qt.models import LeicaImageContext

_APP = None


@pytest.fixture(autouse=True)
def restore_browser_settings():
    settings = QSettings("NL-BioImaging", "leica-browser-qt")
    had_last_root = settings.contains("last_root")
    last_root = settings.value("last_root", "", str)
    had_recent_roots = settings.contains(RECENT_ROOTS_KEY)
    recent_roots = settings.value(RECENT_ROOTS_KEY, [])

    yield

    if had_last_root:
        settings.setValue("last_root", last_root)
    else:
        settings.remove("last_root")

    if had_recent_roots:
        settings.setValue(RECENT_ROOTS_KEY, recent_roots)
    else:
        settings.remove(RECENT_ROOTS_KEY)
    settings.sync()


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


class SingleImageGateway(StaticGateway):
    def container_node(self, path):
        path = Path(path)
        ctx = LeicaImageContext(
            name="Only Image",
            container_path=path,
            internal_path=f"{path.name}/Only Image",
            image_id="only",
            kind="lif-image",
            metadata={"xs": 1, "ys": 1},
        )
        return LeicaTreeNode(
            name=path.name,
            kind="container",
            path=path,
            children=[LeicaTreeNode(name="Only Image", kind="lif-image", context=ctx)],
        )


class SingleNestedImageGateway(StaticGateway):
    def container_node(self, path):
        path = Path(path)
        ctx = LeicaImageContext(
            name="Nested Image",
            container_path=path,
            internal_path=f"{path.name}/Folder/Nested Image",
            image_id="nested",
            kind="lif-image",
            metadata={"xs": 1, "ys": 1},
        )
        return LeicaTreeNode(
            name=path.name,
            kind="container",
            path=path,
            children=[
                LeicaTreeNode(
                    name="Folder",
                    kind="folder",
                    path=path,
                    image_id="folder",
                    children=[LeicaTreeNode(name="Nested Image", kind="lif-image", context=ctx)],
                )
            ],
        )


class MultiSImageGateway(StaticGateway):
    def container_node(self, path):
        path = Path(path)
        ctx = LeicaImageContext(
            name="Positions",
            container_path=path,
            internal_path=f"{path.name}/Positions",
            image_id="positions",
            kind="lif-image",
            size_s=5,
            metadata={"xs": 1, "ys": 1, "tiles": 5},
        )
        return LeicaTreeNode(
            name=path.name,
            kind="container",
            path=path,
            children=[LeicaTreeNode(name="Positions", kind="lif-image", context=ctx)],
        )


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


def test_single_root_image_is_auto_selected(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=SingleImageGateway())
    try:
        dialog.load_file_images(lif)

        root = dialog.tree_images.topLevelItem(0)
        only_image = root.child(0)

        assert only_image.isSelected()
        assert dialog.tree_images.currentItem() is only_image
        assert [ctx.name for ctx in dialog._selected_contexts(hydrate=False)] == ["Only Image"]
        assert dialog.ok_button.isEnabled()
    finally:
        if dialog._preview_worker is not None:
            dialog._preview_worker.wait(3000)
        dialog.close()


def test_single_nested_image_is_not_auto_selected(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=SingleNestedImageGateway())
    try:
        dialog.load_file_images(lif)

        root = dialog.tree_images.topLevelItem(0)
        folder = root.child(0)

        assert not folder.isSelected()
        assert dialog._selected_contexts(hydrate=False) == []
        assert not dialog.ok_button.isEnabled()
    finally:
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


def test_browse_choices_are_kept_as_max_ten_recent_folders(tmp_path, monkeypatch):
    app()
    folders = []
    for idx in range(12):
        folder = tmp_path / f"folder-{idx}"
        folder.mkdir()
        folders.append(folder)

    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=StaticGateway())
    try:
        dialog._settings.remove(RECENT_ROOTS_KEY)
        dialog._recent_roots = []
        dialog._refresh_recent_roots_combo()

        choices = iter(str(folder) for folder in folders)
        monkeypatch.setattr(
            "leica_browser_qt.leica_browser_dialog.QFileDialog.getExistingDirectory",
            lambda *args: next(choices),
        )

        for _ in folders:
            dialog.choose_root()

        expected = [str(folder) for folder in reversed(folders[-MAX_RECENT_ROOTS:])]
        stored = dialog._settings.value(RECENT_ROOTS_KEY, [])

        assert [str(root) for root in dialog._recent_roots] == expected
        assert list(stored) == expected
        assert dialog.recent_roots_combo.count() == MAX_RECENT_ROOTS
    finally:
        dialog._settings.remove(RECENT_ROOTS_KEY)
        dialog.close()


def test_recent_folder_selection_changes_root(tmp_path):
    app()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=StaticGateway())
    try:
        dialog._settings.remove(RECENT_ROOTS_KEY)
        dialog._recent_roots = [first, second]
        dialog._refresh_recent_roots_combo()

        dialog.recent_roots_combo.setCurrentIndex(1)

        assert dialog._current_root == second
        assert dialog.lbl_root.text() == f"Root: {second}"
        assert dialog.tree_fs.topLevelItem(0).text(0) == str(second)
    finally:
        dialog._settings.remove(RECENT_ROOTS_KEY)
        dialog.close()


def test_single_multi_s_image_exposes_browser_s_controls(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=MultiSImageGateway())
    try:
        dialog.load_file_images(lif)

        assert not dialog._s_controls.isHidden()
        assert dialog._s_mode_combo.currentText() == "All"
        assert dialog._s_mode_combo.minimumWidth() >= 88
        assert not dialog._s_slider.isEnabled()
        assert dialog._s_slider.singleStep() == 1
        assert dialog._s_slider.pageStep() == 1
        assert dialog._s_slider.maximum() == 4
        assert dialog._s_spin.maximum() == 5
    finally:
        if dialog._preview_worker is not None:
            dialog._preview_worker.wait(3000)
        dialog.close()


def test_browser_fixed_s_is_returned_on_selected_context(tmp_path):
    app()
    lif = tmp_path / "a.lif"
    lif.write_bytes(b"fake")
    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=MultiSImageGateway())
    try:
        dialog.load_file_images(lif)

        dialog._s_mode_combo.setCurrentText("Fixed")
        dialog._s_spin.setValue(4)

        context = dialog.selected_context()

        assert context is not None
        assert context.selected_s == 3
        assert dialog._s_slider.value() == 3
    finally:
        if dialog._preview_worker is not None:
            dialog._preview_worker.wait(3000)
        dialog.close()


def test_preview_cache_filename_varies_with_selected_s(tmp_path, monkeypatch):
    def fake_create_png_from_metadata(metadata, preview_height=256, use_memmap=True):
        temp_path = tmp_path / f"temp-{metadata.get('selected_s', 'all')}.png"
        temp_path.write_bytes(b"png")
        return str(temp_path)

    monkeypatch.setattr(CreatePreview, "create_png_from_metadata", fake_create_png_from_metadata)
    monkeypatch.setattr(CreatePreview.cv2, "imread", lambda path: b"image")
    monkeypatch.setattr(
        CreatePreview.cv2,
        "imwrite",
        lambda path, image: Path(path).write_bytes(b"cached") or True,
    )

    base_metadata = {
        "uuid": "img-1",
        "LOFFilePath": "sample.lof",
        "xs": 10,
        "ys": 10,
    }

    all_path = CreatePreview.create_preview_image(dict(base_metadata), str(tmp_path), preview_height=128)
    s0_path = CreatePreview.create_preview_image(
        {**base_metadata, "selected_s": 0},
        str(tmp_path),
        preview_height=128,
    )
    s1_path = CreatePreview.create_preview_image(
        {**base_metadata, "selected_s": 1},
        str(tmp_path),
        preview_height=128,
    )

    assert all_path != s0_path
    assert s0_path != s1_path


def test_loading_file_updates_last_root_and_recent_roots(tmp_path):
    app()
    data_root = tmp_path / "data"
    data_root.mkdir()
    lif = data_root / "a.lif"
    lif.write_bytes(b"fake")

    dialog = LeicaBrowserDialog(roots=[tmp_path], selection_mode="single", gateway=StaticGateway())
    try:
        dialog._settings.remove(RECENT_ROOTS_KEY)
        dialog._recent_roots = []
        dialog._refresh_recent_roots_combo()

        dialog.load_file_images(lif)

        stored_last_root = dialog._settings.value("last_root", "", str)
        stored_recent_roots = list(dialog._settings.value(RECENT_ROOTS_KEY, []))

        assert stored_last_root == str(data_root)
        assert stored_recent_roots == [str(data_root)]
        assert [str(root) for root in dialog._recent_roots] == [str(data_root)]
    finally:
        dialog._settings.remove(RECENT_ROOTS_KEY)
        if dialog._preview_worker is not None:
            dialog._preview_worker.wait(3000)
        dialog.close()
