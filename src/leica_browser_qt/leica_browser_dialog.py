from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .leica_gateway import LEICA_EXTENSIONS, LeicaGateway, LeicaTreeNode
from .metadata import metadata_rows
from .models import LeicaImageContext, LeicaImageHandle
from .preview import preview_png_from_metadata

NODE_ROLE = int(Qt.ItemDataRole.UserRole)
CONTEXT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PLACEHOLDER_TEXT = "..."


class PreviewWorker(QThread):
    previewReady = pyqtSignal(int, int, str)
    error = pyqtSignal(int, str)

    def __init__(self, job_id: int, context: LeicaImageContext, heights: list[int]) -> None:
        super().__init__()
        self.job_id = job_id
        self.context = context
        self.heights = heights

    def run(self) -> None:
        try:
            for height in self.heights:
                if self.isInterruptionRequested():
                    break
                path = preview_png_from_metadata(self.context.metadata, preview_height=height)
                self.previewReady.emit(self.job_id, height, str(path))
                if height != self.heights[-1]:
                    QThread.msleep(120)
        except Exception:
            self.error.emit(self.job_id, traceback.format_exc())


class LeicaBrowserDialog(QDialog):
    """Reusable ConvertLeicaQT-style browser for selecting Leica image contexts."""

    def __init__(
        self,
        roots: Iterable[str | Path] | None = None,
        selection_mode: str = "single",
        parent: QWidget | None = None,
        gateway: LeicaGateway | None = None,
    ) -> None:
        super().__init__(parent)
        if selection_mode not in {"single", "multiple"}:
            raise ValueError("selection_mode must be 'single' or 'multiple'")

        root_list = list(roots) if roots is not None else None
        self.gateway = gateway or LeicaGateway()
        self.selection_mode = selection_mode
        self._preview_worker: PreviewWorker | None = None
        self._stale_preview_workers: list[PreviewWorker] = []
        self._preview_job_id = 0
        self._current_file: Path | None = None
        self._settings = QSettings("NL-BioImaging", "leica-browser-qt")
        self._current_root = self._initial_root(root_list)
        self._initial_files = self._initial_file_roots(root_list)

        self.setWindowTitle("Browse Leica Images")
        self.setWindowIcon(self._asset_icon("app-icon.png"))
        self.resize(1180, 760)
        self._build_ui()
        self._apply_style()
        self.populate_fs_root()
        if self._initial_files:
            self.load_file_images(self._initial_files[0])

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_browse_root = QPushButton("Browse...")
        self.btn_browse_root.setFixedWidth(100)
        self.btn_browse_root.clicked.connect(self.choose_root)
        top.addWidget(self.btn_browse_root)

        self.lbl_root = QLabel(f"Root: {self._current_root}")
        self.lbl_root.setWordWrap(True)
        top.addWidget(self.lbl_root, 1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        top.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter Leica contents")
        self.filter_edit.textChanged.connect(self.apply_content_filter)
        top.addWidget(self.filter_edit, 1)

        self.select_all_below_button = QPushButton("Select all images below")
        self.select_all_below_button.clicked.connect(self.select_all_images_below)
        self.select_all_below_button.setVisible(self.selection_mode == "multiple")
        top.addWidget(self.select_all_below_button)
        outer.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_folders = QLabel("Folders and Leica files:")
        left_layout.addWidget(self.lbl_folders)
        self.tree_fs = QTreeWidget()
        self.tree_fs.setHeaderHidden(True)
        self.tree_fs.itemExpanded.connect(self.on_fs_item_expanded)
        self.tree_fs.itemSelectionChanged.connect(self.on_fs_selection_changed)
        self.tree_fs.itemDoubleClicked.connect(self.on_fs_item_double_clicked)
        left_layout.addWidget(self.tree_fs, 1)
        splitter.addWidget(left)

        right_split = QSplitter(Qt.Orientation.Horizontal)
        contents = QWidget()
        contents_layout = QVBoxLayout(contents)
        contents_layout.setContentsMargins(0, 0, 0, 0)
        contents_layout.addWidget(QLabel("Contents of selected Leica file:"))
        self.tree_images = QTreeWidget()
        self.tree_images.setHeaderHidden(True)
        self.tree_images.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection
            if self.selection_mode == "single"
            else QTreeWidget.SelectionMode.ExtendedSelection
        )
        self.tree_images.itemExpanded.connect(self.on_content_item_expanded)
        self.tree_images.itemSelectionChanged.connect(self.on_image_selection_changed)
        self.tree_images.itemDoubleClicked.connect(self.on_image_double_clicked)
        contents_layout.addWidget(self.tree_images, 1)
        right_split.addWidget(contents)

        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel("Select an image to preview it")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(420, 300)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview_label, 2)

        self.metadata_table = QTableWidget(0, 2)
        self.metadata_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.metadata_table.horizontalHeader().setStretchLastSection(True)
        self.metadata_table.verticalHeader().setVisible(False)
        preview_layout.addWidget(self.metadata_table, 1)
        right_split.addWidget(preview)
        right_split.setStretchFactor(0, 36)
        right_split.setStretchFactor(1, 64)
        right_split.setSizes([265, 480])

        splitter.addWidget(right_split)
        splitter.setStretchFactor(0, 36)
        splitter.setStretchFactor(1, 64)
        splitter.setSizes([425, 745])
        outer.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("No image selected")
        footer.addWidget(self.status_label, 1)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        footer.addWidget(self.button_box)
        outer.addLayout(footer)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #202020; color: #f0f0f0; }"
            "QLabel { color: #f0f0f0; }"
            "QTreeWidget, QTableWidget, QLineEdit {"
            "background: #2d2d2d; color: #f7f7f7; border: 1px solid #555;"
            "selection-background-color: #3d5068; }"
            "QHeaderView::section { background: #1e293b; color: #e2e8f0; border: 0; padding: 4px; }"
            "QPushButton { background: #0d47a1; color: white; border: 1px solid #1e5bb8;"
            "border-radius: 4px; padding: 6px 10px; }"
            "QPushButton:hover { background: #1565c0; }"
            "QPushButton:disabled { background: #444; color: #888; border-color: #555; }"
        )

    # ------------------------------------------------------------------
    # Root and filesystem tree
    # ------------------------------------------------------------------

    def _initial_root(self, roots: Iterable[str | Path] | None) -> Path:
        if roots:
            first = Path(next(iter(roots))).expanduser()
            if first.is_file():
                return first.parent
            return first
        remembered = self._settings.value("last_root", "", str)
        if remembered:
            path = Path(remembered).expanduser()
            if self._is_usable_root(path):
                return path
        return Path.home()

    def _initial_file_roots(self, roots: Iterable[str | Path] | None) -> list[Path]:
        files: list[Path] = []
        if roots:
            for root in roots:
                path = Path(root).expanduser()
                if path.is_file() and path.suffix.lower() in LEICA_EXTENSIONS:
                    files.append(path)
                elif path.is_dir() and path.suffix.lower() == ".xlef":
                    files.append(path)
        return files

    def choose_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose root folder", str(self._current_root))
        if chosen:
            self._current_root = Path(chosen)
            self._remember_root(self._current_root)
            self.lbl_root.setText(f"Root: {self._current_root}")
            self.refresh()

    def refresh(self) -> None:
        self.populate_fs_root()
        self.tree_images.clear()
        self._clear_preview()
        self.metadata_table.setRowCount(0)
        self._current_file = None
        self._update_ok_state()

    def populate_fs_root(self) -> None:
        self.tree_fs.clear()
        item = QTreeWidgetItem([str(self._current_root)])
        item.setIcon(0, self.icon_folder())
        item.setData(0, NODE_ROLE, self._current_root)
        item.addChild(QTreeWidgetItem([PLACEHOLDER_TEXT]))
        self.tree_fs.addTopLevelItem(item)
        self.tree_fs.expandItem(item)

    def on_fs_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).text(0) == PLACEHOLDER_TEXT:
            self._populate_fs_children(item)

    def _populate_fs_children(self, parent_item: QTreeWidgetItem) -> None:
        parent_item.takeChildren()
        parent_path = parent_item.data(0, NODE_ROLE)
        if not parent_path:
            return
        path = Path(parent_path)
        if path.is_dir() and path.suffix.lower() == ".xlef":
            return
        if not path.is_dir():
            return

        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            parent_item.addChild(QTreeWidgetItem([f"Warning: {exc}"]))
            return

        has_xlef = any(entry.is_file() and entry.suffix.lower() == ".xlef" for entry in entries)
        for entry in entries:
            if self.gateway._ignore_name(entry.name):
                continue
            if has_xlef and not (entry.is_file() and entry.suffix.lower() == ".xlef"):
                continue
            if entry.is_dir() and entry.suffix.lower() == ".xlef":
                self._add_fs_file(parent_item, entry)
            elif entry.is_dir():
                item = QTreeWidgetItem([entry.name])
                item.setIcon(0, self.icon_folder())
                item.setData(0, NODE_ROLE, entry)
                item.addChild(QTreeWidgetItem([PLACEHOLDER_TEXT]))
                parent_item.addChild(item)
            elif entry.suffix.lower() in LEICA_EXTENSIONS:
                self._add_fs_file(parent_item, entry)

    def _add_fs_file(self, parent_item: QTreeWidgetItem, path: Path) -> None:
        item = QTreeWidgetItem([path.name])
        item.setIcon(0, self.icon_for_file(path.suffix))
        item.setData(0, NODE_ROLE, path)
        parent_item.addChild(item)

    def on_fs_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        path = item.data(0, NODE_ROLE)
        if not path:
            return
        path = Path(path)
        if path.is_dir() and path.suffix.lower() != ".xlef":
            self._current_root = path
            self._remember_root(self._current_root)
            self.lbl_root.setText(f"Root: {self._current_root}")
            self.refresh()
        elif self._is_leica_container(path):
            self.load_file_images(path)

    def on_fs_selection_changed(self) -> None:
        items = self.tree_fs.selectedItems()
        if not items:
            return
        path = items[0].data(0, NODE_ROLE)
        if path and self._is_leica_container(Path(path)):
            self.load_file_images(Path(path))

    # ------------------------------------------------------------------
    # Leica content tree
    # ------------------------------------------------------------------

    def load_file_images(self, path: str | Path) -> None:
        container = Path(path)
        self._current_file = container
        self._remember_root(container.parent if container.is_file() else container)
        self.tree_images.clear()
        self._clear_preview()
        self.metadata_table.setRowCount(0)
        self.preview_label.setText(f"Loading {container.name}...")
        QApplication.processEvents()

        node = self.gateway.container_node(container)
        root_item = self._content_item_from_node(node, is_root=True)
        self.tree_images.addTopLevelItem(root_item)
        self.tree_images.expandItem(root_item)
        self.preview_label.setText("Select an image to preview it")
        self.apply_content_filter()
        self._update_ok_state()

    def _content_item_from_node(self, node: LeicaTreeNode, *, is_root: bool = False) -> QTreeWidgetItem:
        text = node.name if not node.warning else f"{node.name}  [{node.warning}]"
        item = QTreeWidgetItem([text])
        item.setData(0, NODE_ROLE, node)
        if node.context is not None:
            item.setData(0, CONTEXT_ROLE, node.context)
            item.setIcon(0, self.icon_image())
        elif node.kind == "container":
            item.setIcon(0, self.icon_for_file(Path(node.name).suffix))
        elif node.kind == "folder":
            item.setIcon(0, self.icon_folder())
        else:
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))

        if node.context is None and not is_root:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        for child in node.children:
            item.addChild(self._content_item_from_node(child))
        if node.kind == "folder" and not node.children:
            item.addChild(QTreeWidgetItem([PLACEHOLDER_TEXT]))
        return item

    def on_content_item_expanded(self, item: QTreeWidgetItem) -> None:
        node = item.data(0, NODE_ROLE)
        if not isinstance(node, LeicaTreeNode) or node.kind != "folder":
            return
        if item.childCount() != 1 or item.child(0).text(0) != PLACEHOLDER_TEXT:
            return
        if not node.path or not node.image_id:
            return
        item.takeChildren()
        try:
            children = self.gateway.children_for_folder(node.path, node.image_id, node.internal_path)
            node.children = children
            for child in children:
                item.addChild(self._content_item_from_node(child))
        except Exception as exc:
            warn = QTreeWidgetItem([f"Warning: {exc}"])
            warn.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
            item.addChild(warn)

    def selected_contexts(self) -> list[LeicaImageContext]:
        contexts: list[LeicaImageContext] = []
        for item in self.tree_images.selectedItems():
            context = item.data(0, CONTEXT_ROLE)
            if isinstance(context, LeicaImageContext) and context not in contexts:
                contexts.append(context)
        return contexts

    def selected_context(self) -> LeicaImageContext | None:
        contexts = self.selected_contexts()
        return contexts[0] if contexts else None

    def on_image_selection_changed(self) -> None:
        contexts = self.selected_contexts()
        if len(contexts) == 1:
            self.show_context(contexts[0])
        elif len(contexts) > 1:
            self._cancel_preview_worker()
            self.preview_label.setText(f"{len(contexts)} images selected")
            self.metadata_table.setRowCount(0)
        else:
            self._cancel_preview_worker()
            self._clear_preview()
            self.metadata_table.setRowCount(0)
        self._update_ok_state()

    def on_image_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if self.selection_mode == "single" and isinstance(item.data(0, CONTEXT_ROLE), LeicaImageContext):
            self.accept()

    def select_all_images_below(self) -> None:
        if self.selection_mode != "multiple":
            return
        roots = self.tree_images.selectedItems() or [
            self.tree_images.topLevelItem(i) for i in range(self.tree_images.topLevelItemCount())
        ]
        self.tree_images.blockSignals(True)
        self.tree_images.clearSelection()

        def select_images(item: QTreeWidgetItem) -> None:
            if isinstance(item.data(0, CONTEXT_ROLE), LeicaImageContext):
                item.setSelected(True)
            for idx in range(item.childCount()):
                select_images(item.child(idx))

        for root in roots:
            select_images(root)
        self.tree_images.blockSignals(False)
        self.on_image_selection_changed()

    def apply_content_filter(self) -> None:
        text = self.filter_edit.text().strip().lower()

        def update(item: QTreeWidgetItem) -> bool:
            own_match = not text or text in item.text(0).lower()
            child_match = False
            for idx in range(item.childCount()):
                child_match = update(item.child(idx)) or child_match
            visible = own_match or child_match
            item.setHidden(not visible)
            return visible

        for idx in range(self.tree_images.topLevelItemCount()):
            update(self.tree_images.topLevelItem(idx))

    # ------------------------------------------------------------------
    # Preview and metadata
    # ------------------------------------------------------------------

    def show_context(self, context: LeicaImageContext) -> None:
        self._populate_metadata(context.metadata)
        self._start_preview(context)

    def _populate_metadata(self, metadata: dict) -> None:
        rows = metadata_rows(metadata)
        self.metadata_table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            self.metadata_table.setItem(row, 0, QTableWidgetItem(key))
            self.metadata_table.setItem(row, 1, QTableWidgetItem(value))
        self.metadata_table.resizeColumnsToContents()

    def _start_preview(self, context: LeicaImageContext) -> None:
        self._cancel_preview_worker()
        self._preview_job_id += 1
        job_id = self._preview_job_id
        heights = self._preview_heights(context)
        self.preview_label.setText(f"Loading preview {heights[0]}px...")
        self._preview_worker = PreviewWorker(job_id, context, heights)
        self._preview_worker.previewReady.connect(self._on_preview_ready)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _on_preview_ready(self, job_id: int, height: int, path: str) -> None:
        if job_id != self._preview_job_id:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_label.setText("Preview unavailable")
            return
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_label.setToolTip(f"Preview height: {height}px")

    def _on_preview_error(self, job_id: int, message: str) -> None:
        if job_id != self._preview_job_id:
            return
        last_line = message.strip().splitlines()[-1] if message.strip() else "Preview unavailable"
        self.preview_label.setText(last_line)

    def _clear_preview(self) -> None:
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setToolTip("")
        self.preview_label.setText("Select an image to preview it")

    def _preview_heights(self, context: LeicaImageContext) -> list[int]:
        steps = [24, 112, 256, 512]
        sx = context.size_x
        sy = context.size_y
        if sx is not None and sy is not None and sx <= 2048 and sy <= 2048:
            return [max(steps)]
        return steps

    # ------------------------------------------------------------------
    # Icons and helpers
    # ------------------------------------------------------------------

    def _asset_icon(self, name: str, fallback: QStyle.StandardPixmap | None = None) -> QIcon:
        path = Path(__file__).with_name("images") / name
        if path.exists():
            return QIcon(str(path))
        if fallback is not None:
            return self.style().standardIcon(fallback)
        return QIcon()

    def icon_folder(self) -> QIcon:
        return self._asset_icon("folder.svg", QStyle.StandardPixmap.SP_DirIcon)

    def icon_image(self) -> QIcon:
        return self._asset_icon("image.svg", QStyle.StandardPixmap.SP_FileIcon)

    def icon_for_file(self, ext: str) -> QIcon:
        ext = ext.lower().lstrip(".")
        mapping = {"lif": "file-lif.svg", "xlef": "file-xlef.svg", "lof": "file-lof.svg"}
        return self._asset_icon(mapping.get(ext, "image.svg"), QStyle.StandardPixmap.SP_FileIcon)

    @staticmethod
    def _is_leica_container(path: Path) -> bool:
        return (path.is_file() and path.suffix.lower() in LEICA_EXTENSIONS) or (
            path.is_dir() and path.suffix.lower() == ".xlef"
        )

    def _remember_root(self, root: Path) -> None:
        if self._is_usable_root(root):
            self._settings.setValue("last_root", str(root))

    def _is_usable_root(self, root: Path) -> bool:
        """Return True when a remembered folder still looks readable/useful."""

        if not root.exists() or not root.is_dir() or self._is_source_checkout(root):
            return False
        if not os.access(root, os.R_OK):
            return False
        try:
            entries = list(root.iterdir())
        except OSError:
            return False

        for entry in entries:
            if entry.is_file() and entry.suffix.lower() in LEICA_EXTENSIONS:
                try:
                    with entry.open("rb"):
                        pass
                except OSError:
                    return False
        return True

    @staticmethod
    def _is_source_checkout(path: Path) -> bool:
        """Avoid persisting this package checkout as a data browsing root."""

        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        markers = [
            resolved / "pyproject.toml",
            resolved / "src" / "leica_browser_qt",
            resolved / "plan_leica_browser_qt.md",
        ]
        return all(marker.exists() for marker in markers)

    def _update_ok_state(self) -> None:
        count = len(self.selected_contexts())
        valid = count == 1 if self.selection_mode == "single" else count > 0
        self.ok_button.setEnabled(valid)
        self.status_label.setText(f"{count} image selected" if count == 1 else f"{count} images selected")

    def _cancel_preview_worker(self) -> None:
        if self._preview_worker is not None:
            worker = self._preview_worker
            worker.requestInterruption()
            self._stale_preview_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._forget_stale_worker(w))
            self._preview_worker = None

    def _forget_stale_worker(self, worker: PreviewWorker) -> None:
        try:
            self._stale_preview_workers.remove(worker)
        except ValueError:
            pass

    def _shutdown_workers(self) -> None:
        workers = [self._preview_worker, *self._stale_preview_workers]
        for worker in workers:
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(1500)
        self._preview_worker = None
        self._stale_preview_workers.clear()

    def accept(self) -> None:
        self._shutdown_workers()
        super().accept()

    def reject(self) -> None:
        self._shutdown_workers()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._shutdown_workers()
        super().closeEvent(event)

    @classmethod
    def select_image_context(
        cls,
        roots: Iterable[str | Path] | None = None,
        parent: QWidget | None = None,
    ) -> LeicaImageContext | None:
        ensure_app()
        dialog = cls(roots=roots, selection_mode="single", parent=parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_context()
        return None

    @classmethod
    def select_image_contexts(
        cls,
        roots: Iterable[str | Path] | None = None,
        parent: QWidget | None = None,
    ) -> list[LeicaImageContext]:
        ensure_app()
        dialog = cls(roots=roots, selection_mode="multiple", parent=parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_contexts()
        return []

    @classmethod
    def select_image(
        cls,
        roots: Iterable[str | Path] | None = None,
        parent: QWidget | None = None,
    ) -> LeicaImageHandle | None:
        context = cls.select_image_context(roots=roots, parent=parent)
        return context.open() if context is not None else None

    @classmethod
    def select_images(
        cls,
        roots: Iterable[str | Path] | None = None,
        parent: QWidget | None = None,
    ) -> list[LeicaImageHandle]:
        return [context.open() for context in cls.select_image_contexts(roots=roots, parent=parent)]


_APP_REF: QApplication | None = None


def ensure_app() -> QApplication:
    global _APP_REF
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    _APP_REF = app
    return app


def run_dialog_as_json(paths: list[str], *, multiple: bool) -> int:
    ensure_app()
    dialog = LeicaBrowserDialog(roots=paths or None, selection_mode="multiple" if multiple else "single")
    if dialog.exec() == QDialog.DialogCode.Accepted:
        contexts = dialog.selected_contexts()
        payload = [ctx.to_dict() for ctx in contexts] if multiple else (
            contexts[0].to_dict() if contexts else None
        )
        print(json.dumps(payload, indent=2))
        return 0
    print("[]" if multiple else "null")
    return 1
