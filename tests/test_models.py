from pathlib import Path

from leica_browser_qt import LeicaImageContext


def test_context_serializes_path_and_metadata():
    ctx = LeicaImageContext(
        name="Image 1",
        container_path=Path("sample.lif"),
        internal_path="sample.lif/Folder/Image 1",
        image_id="abc",
        kind="lif-image",
        size_x=10,
        size_y=20,
        channel_names=["DAPI"],
        metadata={"nested": {"path": Path("sample.lif")}},
    )

    data = ctx.to_dict()

    assert data["container_path"] == "sample.lif"
    assert data["metadata"]["nested"]["path"] == "sample.lif"

