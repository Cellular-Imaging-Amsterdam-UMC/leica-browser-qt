"""Leica path scanning and backend adapter.

The backend call pattern is adapted from NL-BioImaging/ConvertLeica-Docker's
ConvertLeicaQT.py, which uses ci_leica_converters_helpers.read_leica_file and
related helpers to inspect LIF/XLEF/LOF metadata. ConvertLeica-Docker is
licensed under Apache-2.0.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .metadata import context_from_metadata
from .models import LeicaImageContext

LEICA_EXTENSIONS = {".lif", ".xlef", ".lof"}
IGNORED_NAME_PARTS = (
    "metadata",
    "_pmd_",
    "_histo",
    "_environmetalgraph",
    "iomanagerconfiguation",
    "iomanagerconfiguration",
)


@dataclass
class LeicaTreeNode:
    name: str
    kind: str
    path: Path | None = None
    internal_path: str = ""
    image_id: str | None = None
    context: LeicaImageContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    folder_metadata: dict[str, Any] | None = None
    metadata_loaded: bool = False
    warning: str | None = None
    children: list["LeicaTreeNode"] = field(default_factory=list)

    @property
    def is_image(self) -> bool:
        return self.context is not None


class ConvertLeicaAdapter:
    """Small adapter around ConvertLeica-Docker helper functions."""

    def __init__(self) -> None:
        self._helpers = None

    @property
    def available(self) -> bool:
        return self._load_helpers() is not None

    def _load_helpers(self):
        if self._helpers is not None:
            return self._helpers
        for module_name in (
            "leica_browser_qt._convertleica_backend.helpers",
            "ci_leica_converters_helpers",
        ):
            try:
                self._helpers = importlib.import_module(module_name)
                return self._helpers
            except ImportError:
                continue
        return None

    def read_tree(self, path: Path, folder_uuid: str | None = None) -> dict[str, Any]:
        helpers = self._load_helpers()
        if helpers is None:
            raise RuntimeError(
                "Leica parser backend is unavailable."
            )
        raw = helpers.read_leica_file(str(path), folder_uuid=folder_uuid)
        return json.loads(raw) if isinstance(raw, str) else raw

    def read_image_metadata(
        self,
        path: Path,
        image_uuid: str | None,
        folder_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        helpers = self._load_helpers()
        if helpers is None:
            raise RuntimeError("Leica parser backend is unavailable.")
        ext = path.suffix.lower()
        if ext == ".lof" or image_uuid == "__LOF__":
            raw = helpers.read_leica_file(str(path))
        elif ext == ".xlef" and folder_metadata is not None and image_uuid:
            if hasattr(helpers, "read_image_metadata"):
                raw = helpers.read_image_metadata(str(path), image_uuid)
            else:
                folder_json = json.dumps(folder_metadata)
                entry = json.loads(helpers.get_image_metadata(folder_json, image_uuid))
                meta = json.loads(helpers.get_image_metadata_LOF(folder_json, image_uuid))
                if "save_child_name" in entry:
                    meta["save_child_name"] = entry["save_child_name"]
                raw = meta
        elif image_uuid:
            raw = helpers.read_leica_file(str(path), image_uuid=image_uuid)
        else:
            raw = helpers.read_leica_file(str(path))
        return json.loads(raw) if isinstance(raw, str) else raw


class LeicaGateway:
    """Scan Leica roots and lazily bridge to Leica metadata/preview backends."""

    def __init__(self, adapter: ConvertLeicaAdapter | None = None) -> None:
        self.adapter = adapter or ConvertLeicaAdapter()

    def scan_roots(self, roots: Iterable[str | Path] | None = None) -> list[LeicaTreeNode]:
        paths = [Path(p).expanduser() for p in roots] if roots else [Path.cwd()]
        nodes: list[LeicaTreeNode] = []
        for path in paths:
            nodes.extend(self.scan_path(path))
        return nodes

    def scan_path(self, path: str | Path) -> list[LeicaTreeNode]:
        root = Path(path).expanduser()
        if root.is_dir() and root.suffix.lower() == ".xlef":
            return [self.container_node(root)]
        if root.is_dir():
            return [self._scan_directory(root)]
        if root.is_file() and root.suffix.lower() in LEICA_EXTENSIONS:
            return [self.container_node(root)]
        if not root.exists():
            return [
                LeicaTreeNode(
                    name=root.name or str(root),
                    kind="warning",
                    path=root,
                    warning=f"Path does not exist: {root}",
                )
            ]
        return []

    def _scan_directory(self, path: Path) -> LeicaTreeNode:
        node = LeicaTreeNode(name=path.name or str(path), kind="folder", path=path)
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            node.warning = str(exc)
            return node

        has_xlef = any(child.suffix.lower() == ".xlef" for child in entries if child.is_file())
        for child in entries:
            if self._ignore_name(child.name):
                continue
            if child.is_dir() and child.suffix.lower() == ".xlef":
                node.children.append(self.container_node(child))
            elif child.is_dir():
                node.children.append(self._scan_directory(child))
            elif child.suffix.lower() in LEICA_EXTENSIONS:
                if has_xlef and child.suffix.lower() not in {".xlef", ".lif", ".lof"}:
                    continue
                node.children.append(self.container_node(child))
        return node

    def container_node(self, path: str | Path) -> LeicaTreeNode:
        container = Path(path)
        node = LeicaTreeNode(
            name=container.name,
            kind="container",
            path=container,
            internal_path=container.name,
        )

        if container.suffix.lower() == ".lof":
            metadata = self._safe_lof_metadata(container)
            node.children.append(
                LeicaTreeNode(
                    name=container.name,
                    kind="lof-image",
                    path=container,
                    internal_path=container.name,
                    image_id="__LOF__",
                    context=context_from_metadata(
                        name=container.name,
                        container_path=container,
                        internal_path=container.name,
                        image_id="__LOF__",
                        kind="lof-image",
                        metadata=metadata,
                    ),
                    metadata=metadata,
                    metadata_loaded=True,
                )
            )
            return node

        try:
            root_metadata = self.adapter.read_tree(container)
            node.metadata = root_metadata
            node.children = self._children_from_metadata(
                container=container,
                folder_metadata=root_metadata,
                parent_internal_path=container.name,
            )
        except Exception as exc:
            node.warning = str(exc)
            node.children.append(
                LeicaTreeNode(
                    name=f"Warning: {exc}",
                    kind="warning",
                    path=container,
                    internal_path=container.name,
                    warning=str(exc),
                )
            )
        return node

    def children_for_folder(
        self,
        container: Path,
        folder_uuid: str,
        parent_internal_path: str,
    ) -> list[LeicaTreeNode]:
        folder_metadata = self.adapter.read_tree(container, folder_uuid=folder_uuid)
        return self._children_from_metadata(container, folder_metadata, parent_internal_path)

    def _children_from_metadata(
        self,
        container: Path,
        folder_metadata: dict[str, Any],
        parent_internal_path: str,
    ) -> list[LeicaTreeNode]:
        children: list[LeicaTreeNode] = []
        for child in folder_metadata.get("children", []) or []:
            if not isinstance(child, dict):
                continue
            name = child.get("name") or child.get("ElementName") or "(unnamed)"
            if self._ignore_name(str(name)):
                continue
            uuid = child.get("uuid") or child.get("UniqueID") or child.get("ImageUUID")
            child_type = str(child.get("type") or "").lower()
            internal_path = f"{parent_internal_path}/{name}"
            if child_type in {"folder", "file"}:
                children.append(
                    LeicaTreeNode(
                        name=str(name),
                        kind="folder",
                        path=container,
                        internal_path=internal_path,
                        image_id=str(uuid) if uuid else None,
                        metadata=child,
                        folder_metadata=folder_metadata,
                    )
                )
            else:
                metadata = self._lightweight_image_metadata(container, child)
                children.append(
                    LeicaTreeNode(
                        name=str(name),
                        kind=self._image_kind(container),
                        path=container,
                        internal_path=internal_path,
                        image_id=str(uuid) if uuid else None,
                        context=context_from_metadata(
                            name=str(name),
                            container_path=container,
                            internal_path=internal_path,
                            image_id=str(uuid) if uuid else None,
                            kind=self._image_kind(container),
                            metadata=metadata,
                        ),
                        metadata=metadata,
                        folder_metadata=folder_metadata,
                        metadata_loaded=False,
                    )
                )
        return children

    def hydrate_image_node(self, node: LeicaTreeNode) -> LeicaImageContext | None:
        """Load full image metadata for an image node on demand.

        Building large Leica trees is much faster when the tree is made from
        the folder-level XML only. Full image metadata can require extra LIF
        XML parsing or LOF reads, so defer it until the image is returned to
        callers.
        """

        if node.context is None:
            return None
        if node.metadata_loaded:
            return node.context
        if node.path is None:
            node.metadata_loaded = True
            return node.context

        metadata = self._safe_image_metadata(
            node.path,
            node.image_id,
            node.folder_metadata or {},
            node.metadata,
        )
        node.metadata = metadata
        node.metadata_loaded = True
        node.context = context_from_metadata(
            name=node.name,
            container_path=node.context.container_path,
            internal_path=node.internal_path,
            image_id=node.image_id,
            kind=node.kind,
            metadata=metadata,
        )
        return node.context

    def _lightweight_image_metadata(
        self,
        container: Path,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(source)
        metadata.setdefault("filetype", container.suffix.lower())
        if container.suffix.lower() == ".lif":
            metadata.setdefault("LIFFile", str(container))
        if container.suffix.lower() in {".xlef", ".lof"}:
            metadata.setdefault("LOFFilePath", metadata.get("lof_file_path", str(container)))
        return metadata

    def _safe_image_metadata(
        self,
        container: Path,
        image_uuid: str | None,
        folder_metadata: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            metadata = self.adapter.read_image_metadata(container, image_uuid, folder_metadata)
        except Exception:
            metadata = dict(fallback)
        metadata.setdefault("filetype", container.suffix.lower())
        if container.suffix.lower() == ".lif":
            metadata.setdefault("LIFFile", str(container))
        if container.suffix.lower() in {".xlef", ".lof"}:
            metadata.setdefault("LOFFilePath", metadata.get("lof_file_path", str(container)))
        return metadata

    def _safe_lof_metadata(self, container: Path) -> dict[str, Any]:
        try:
            metadata = self.adapter.read_image_metadata(container, "__LOF__")
        except Exception as exc:
            metadata = {"filetype": ".lof", "LOFFilePath": str(container), "warning": str(exc)}
        metadata.setdefault("filetype", ".lof")
        metadata.setdefault("LOFFilePath", str(container))
        return metadata

    def read_thumbnail(self, context: LeicaImageContext, max_size: int = 512):
        from .preview import preview_png_from_metadata

        preview_path = preview_png_from_metadata(context.metadata, preview_height=max_size)
        try:
            import cv2

            image = cv2.imread(str(preview_path), cv2.IMREAD_UNCHANGED)
            if image is not None:
                return image
        except ImportError:
            pass
        return np.asarray(preview_path)

    def read_plane(self, context: LeicaImageContext, z: int = 0, c: int = 0, t: int = 0):
        from .leica_pixels import read_leica_plane

        return read_leica_plane(context, z=z, c=c, t=t)

    def read_array(self, context: LeicaImageContext):
        from .leica_pixels import read_leica_array

        return read_leica_array(context)

    @staticmethod
    def _ignore_name(name: str) -> bool:
        low = name.lower()
        return low.endswith(".lifext") or any(part in low for part in IGNORED_NAME_PARTS)

    @staticmethod
    def _image_kind(container: Path) -> str:
        return {
            ".lif": "lif-image",
            ".xlef": "xlef-image",
            ".lof": "lof-image",
        }.get(container.suffix.lower(), "leica-image")
