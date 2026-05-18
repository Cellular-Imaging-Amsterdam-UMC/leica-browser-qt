import json

from leica_browser_qt import LeicaGateway


class FakeAdapter:
    available = True

    def read_tree(self, path, folder_uuid=None):
        return {
            "children": [
                {
                    "name": "Image A",
                    "type": "image",
                    "uuid": "img-a",
                    "xs": 64,
                    "ys": 32,
                    "channels": 2,
                }
            ]
        }

    def read_image_metadata(self, path, image_uuid, folder_metadata=None):
        return {
            "save_child_name": "Image A",
            "uuid": image_uuid,
            "filetype": path.suffix.lower(),
            "xs": 64,
            "ys": 32,
            "zs": 3,
            "channels": 2,
            "ts": 1,
            "xres2": 0.2,
            "yres2": 0.2,
            "lutname": ["green", "magenta"],
        }


class CountingAdapter(FakeAdapter):
    def __init__(self):
        self.image_metadata_reads = 0

    def read_image_metadata(self, path, image_uuid, folder_metadata=None):
        self.image_metadata_reads += 1
        return super().read_image_metadata(path, image_uuid, folder_metadata)


def test_scans_single_lif(tmp_path):
    lif = tmp_path / "sample.lif"
    lif.write_bytes(b"fake")

    nodes = LeicaGateway(adapter=FakeAdapter()).scan_roots([lif])

    assert nodes[0].name == "sample.lif"
    assert nodes[0].children[0].context.name == "Image A"
    assert nodes[0].children[0].context.size_x == 64


def test_container_tree_uses_lightweight_image_metadata_until_hydrated(tmp_path):
    lif = tmp_path / "sample.lif"
    lif.write_bytes(b"fake")
    adapter = CountingAdapter()
    gateway = LeicaGateway(adapter=adapter)

    node = gateway.container_node(lif)

    assert adapter.image_metadata_reads == 0
    assert node.children[0].context.size_x == 64
    assert node.children[0].metadata_loaded is False

    context = gateway.hydrate_image_node(node.children[0])

    assert adapter.image_metadata_reads == 1
    assert context.size_z == 3
    assert node.children[0].metadata_loaded is True


def test_scans_single_xlef(tmp_path):
    xlef = tmp_path / "experiment.xlef"
    xlef.write_text("<xlef />")

    nodes = LeicaGateway(adapter=FakeAdapter()).scan_roots([xlef])

    assert nodes[0].children[0].context.kind == "xlef-image"


def test_scans_single_lof_without_backend(tmp_path):
    lof = tmp_path / "tile.lof"
    lof.write_bytes(b"fake")

    nodes = LeicaGateway().scan_roots([lof])

    assert nodes[0].children[0].context.kind == "lof-image"
    assert nodes[0].children[0].context.image_id == "__LOF__"


def test_scans_folder_with_multiple_leica_containers(tmp_path):
    (tmp_path / "a.lif").write_bytes(b"fake")
    (tmp_path / "b.xlef").write_text("<xlef />")
    (tmp_path / "c.lof").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_text("ignore")

    root = LeicaGateway(adapter=FakeAdapter()).scan_roots([tmp_path])[0]

    names = [child.name for child in root.children]
    assert names == ["a.lif", "b.xlef", "c.lof"]


def test_missing_path_does_not_crash(tmp_path):
    nodes = LeicaGateway().scan_roots([tmp_path / "missing.lif"])

    assert nodes[0].kind == "warning"
    assert "does not exist" in nodes[0].warning


def test_folder_with_xlef_hides_other_entries_in_browser(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from leica_browser_qt import LeicaBrowserDialog

    app = QApplication.instance() or QApplication([])
    (tmp_path / "experiment.xlef").write_text("<xlef />")
    (tmp_path / "sidecar.lof").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_text("ignore")
    (tmp_path / "nested").mkdir()

    dialog = LeicaBrowserDialog(roots=[tmp_path])
    try:
        root = dialog.tree_fs.topLevelItem(0)
        dialog._populate_fs_children(root)
        names = [root.child(i).text(0) for i in range(root.childCount())]
        assert names == ["experiment.xlef"]
    finally:
        dialog.close()
