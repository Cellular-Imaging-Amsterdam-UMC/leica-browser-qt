# Plan: PyPI library for browsing Leica LIF/XLEF containers

## Goal

Create a reusable PyPI package, tentatively named `leica-browser-qt`, that provides a PyQt6 dialog for browsing Leica `.lif` and `.xlef` datasets in a way similar to `omero-browser-qt`.

The package should let applications such as `cideconvolve` open one or more LIF/XLEF files, browse their internal folder/image structure, preview images, inspect metadata, and return selected image contexts to the caller.

## Design references

Use these repositories as references:

- `omero-browser-qt`
  - Reusable PyQt6 dialog package.
  - Public API pattern with selection helper methods.
  - Lazy tree loading, preview, metadata table, name filtering, embeddable dialog.

- `ConvertLeica-Docker`
  - Existing Leica parsing/conversion logic.
  - Existing Qt6 Leica viewer/browser code.
  - Existing support for `.lif`, `.lof`, `.xlef`.
  - Reuse parsing logic where possible, but move reusable browser functionality into a clean package.

- `cideconvolve`
  - Integrate as a GUI loading option similar to OMERO browsing.
  - Add `Open Leica Container...` or `Open LIF/XLEF...`.

## Package scope

Create a new Python package:

```text
leica-browser-qt/
  pyproject.toml
  README.md
  LICENSE
  src/
    leica_browser_qt/
      __init__.py
      api.py
      models.py
      leica_gateway.py
      leica_browser_dialog.py
      leica_tree_model.py
      preview.py
      metadata.py
      pixel_loader.py
      cli.py
  tests/
    test_scan_paths.py
    test_models.py
    test_public_api.py
  examples/
    minimal_select_single_image.py
    minimal_select_multiple_images.py
    open_multiple_lif_xlef.py
```

Target Python: 3.10-3.12 initially, because this matches common scientific/Qt packaging better than Python 3.13-only.

## Dependencies

Core dependencies:

```text
PyQt6
numpy
tifffile
imagecodecs
```

Optional dependencies:

```toml
[project.optional-dependencies]
dask = ["dask[array]"]
viewer = ["matplotlib", "vispy"]
dev = ["pytest", "ruff", "build", "twine"]
```

Leica parsing dependency strategy:

1. First try to reuse/refactor parser code from `ConvertLeica-Docker`.
2. Prefer a clean internal abstraction so the backend can later switch to `liffile`, `bioio`, or custom Leica parsing without changing the GUI API.
3. Avoid requiring `pyvips` for browsing unless absolutely needed.
4. Keep conversion-to-OME-TIFF outside the core browser package for now.

## Public API

Expose this from `leica_browser_qt/__init__.py`:

```python
from .api import LeicaImageContext, LeicaImageHandle
from .leica_gateway import LeicaGateway
from .leica_browser_dialog import LeicaBrowserDialog
```

Required selection APIs:

```python
# Single image selection. Returns one LeicaImageContext or None.
ctx = LeicaBrowserDialog.select_image_context(
    roots=[r"D:\\data\\experiment1.lif"],
    parent=None,
)

# Multiple image selection. Returns list[LeicaImageContext].
contexts = LeicaBrowserDialog.select_image_contexts(
    roots=[r"D:\\data\\experiment1.lif", r"D:\\data\\folder_with_xlef"],
    parent=None,
)
```

Also provide lower-level explicit mode support:

```python
dialog = LeicaBrowserDialog(
    roots=[r"D:\\data"],
    selection_mode="single",  # "single" or "multiple"
    parent=None,
)

if dialog.exec():
    contexts = dialog.selected_contexts()
```

Convenience image-handle API:

```python
# Single image handle, or None.
handle = LeicaBrowserDialog.select_image(
    roots=[r"D:\\data\\experiment1.lif"],
    parent=None,
)

# Multiple image handles.
handles = LeicaBrowserDialog.select_images(
    roots=[r"D:\\data\\experiment1.lif", r"D:\\data\\folder_with_xlef"],
    parent=None,
)
```

## Selection behavior

The library must support both single-select and multi-select use cases.

### Single-select mode

Use this when the caller needs exactly one image, for example selecting one input volume for one deconvolution run.

Requirements:

1. Tree view uses single selection.
2. OK button is enabled only when exactly one image node is selected.
3. Folder/container nodes are not valid final selections unless they resolve to a single image.
4. API returns `LeicaImageContext | None` or `LeicaImageHandle | None`.
5. Double-clicking an image should accept the dialog.

### Multi-select mode

Use this when the caller wants batch processing, for example selecting several images from one or more LIF/XLEF containers.

Requirements:

1. Tree view uses extended selection.
2. OK button is enabled when one or more image nodes are selected.
3. Folder/container nodes should not be returned directly.
4. Optional helper: if a folder/container node is selected, provide a button or context action `Select all images below`.
5. API returns `list[LeicaImageContext]` or `list[LeicaImageHandle]`.
6. Preserve selection order where practical; otherwise return tree order.

## Data model

Create a dataclass:

```python
@dataclass
class LeicaImageContext:
    name: str
    container_path: Path
    internal_path: str
    image_id: str | None
    kind: str              # "lif-image", "xlef-image", "lof-image", "folder"
    size_x: int | None
    size_y: int | None
    size_z: int | None
    size_c: int | None
    size_t: int | None
    pixel_size_x_um: float | None
    pixel_size_y_um: float | None
    pixel_size_z_um: float | None
    channel_names: list[str]
    metadata: dict[str, Any]

    def open(self) -> "LeicaImageHandle": ...
```

Create a backend-neutral image handle:

```python
class LeicaImageHandle:
    context: LeicaImageContext

    def read_thumbnail(self, max_size: int = 512) -> np.ndarray: ...
    def read_plane(self, z: int = 0, c: int = 0, t: int = 0) -> np.ndarray: ...
    def read_array(self) -> np.ndarray: ...
    def read_lazy(self): ...
```

## Backend layer

Implement `LeicaGateway`.

Responsibilities:

1. Accept multiple roots:
   - individual `.lif`
   - individual `.xlef`
   - individual `.lof`
   - folders containing `.lif`, `.xlef`, `.lof`
2. Scan roots recursively, but do not fully parse every huge container immediately.
3. Build a logical tree:
   - filesystem folders
   - Leica container files
   - internal Leica folders
   - images/acquisitions
4. Provide lazy metadata loading.
5. Provide lazy preview loading.
6. Provide selected image handles.

Important behavior:

- Multiple LIF/XLEF files should appear as separate top-level items or as items inside their filesystem folders.
- XLEF experiments that reference LOF/XLCF/XLIF sidecar files should be resolved relative to the XLEF location.
- Missing sidecars should be shown with a warning icon/status, not crash the dialog.
- Keep internal Leica paths/breadcrumbs so selected images can be identified again.

## GUI

Implement `LeicaBrowserDialog`.

Layout:

```text
Top:
  Add File(s)...
  Add Folder...
  Remove
  Refresh
  Filter: [ text box ]
  Selection mode: single/multiple, or set by constructor

Main:
  Left: tree view
    folders
    LIF/XLEF containers
    internal folders
    image nodes

  Right:
    preview image
    metadata table
    dimensions/channels summary

Bottom:
  selected image count
  OK / Cancel
```

Required features:

1. Browse multiple LIF/XLEF files at once.
2. Show filesystem folders and Leica internal folders.
3. Support both single-select and multi-select modes.
4. Name filter.
5. Lazy tree expansion.
6. Preview selected image.
7. Metadata table.
8. Do not block the UI on large files; use worker thread for scanning and preview generation.
9. Show clear errors in the UI for unreadable files.

Nice-to-have, but not required for first version:

- Recent folders/files history.
- Cached thumbnails.
- Channel toggle preview.
- Z/T slider preview.
- Export selected image to OME-TIFF by delegating to `ConvertLeica-Docker` logic.

## CLI entry point

Add a small launcher:

```toml
[project.scripts]
leica_browser = "leica_browser_qt.cli:main"
```

Command examples:

```bash
leica_browser D:\data
leica_browser file1.lif file2.xlef
leica_browser --single D:\data
leica_browser --multiple D:\data
```

The CLI opens the browser and prints selected contexts as JSON.

## cideconvolve integration

In `cideconvolve` GUI:

1. Add dependency option:
   - `leica-browser-qt` in GUI requirements.
2. Add button:
   - `Open Leica...`
3. For normal one-image workflows:
   - call `LeicaBrowserDialog.select_image_context(...)`
   - use single-select mode.
4. For batch workflows:
   - call `LeicaBrowserDialog.select_image_contexts(...)`
   - use multi-select mode.
5. Read selected image using returned handle.
6. Feed result into existing image-loading pipeline.
7. Preserve metadata:
   - pixel size XY/Z
   - channel names
   - wavelengths if available
   - microscope type if available
   - objective NA if available
   - pinhole if available
8. If metadata is incomplete, fall back to existing GUI parameter values.

Pseudo-code for single image:

```python
from leica_browser_qt import LeicaBrowserDialog

def open_single_leica_image(self):
    ctx = LeicaBrowserDialog.select_image_context(
        roots=self.last_data_roots,
        parent=self,
    )
    if ctx is None:
        return

    handle = ctx.open()
    arr = handle.read_array()
    self.load_image_array(arr, metadata=ctx.metadata, source_name=ctx.name)
```

Pseudo-code for batch selection:

```python
from leica_browser_qt import LeicaBrowserDialog

def open_multiple_leica_images(self):
    contexts = LeicaBrowserDialog.select_image_contexts(
        roots=self.last_data_roots,
        parent=self,
    )
    for ctx in contexts:
        handle = ctx.open()
        arr = handle.read_array()
        self.load_image_array(arr, metadata=ctx.metadata, source_name=ctx.name)
```

## Migration from ConvertLeica-Docker

Do not copy the whole converter into the new package.

Refactor only reusable parts:

1. Leica container scanning.
2. Internal image listing.
3. Metadata extraction.
4. Thumbnail/preview reading.
5. Optional plane reading.

Keep OME-TIFF conversion in `ConvertLeica-Docker`.

Where code is copied, preserve license headers and attribution.

## Testing

Create small test fixtures if possible:

```text
tests/data/
  tiny.lif
  tiny_xlef/
    experiment.xlef
    ...
```

If real Leica test files are too large/private:

1. Add parser unit tests with mocked metadata structures.
2. Add GUI smoke tests that instantiate the dialog.
3. Add path scanning tests using fake file trees.
4. Add optional integration tests enabled only when `LEICA_TEST_DATA` is set.

Test cases:

- Single LIF file.
- Single XLEF folder.
- Folder containing multiple LIF/XLEF files.
- Missing XLEF sidecar file.
- Single-select returns exactly one context or None.
- Multi-select returns multiple stable contexts.
- Preview failure does not crash GUI.
- Metadata table handles missing values.

## Documentation

README should include:

1. Installation:

```bash
pip install leica-browser-qt
```

2. Minimal single-select use:

```python
from PyQt6.QtWidgets import QApplication
from leica_browser_qt import LeicaBrowserDialog

app = QApplication([])
ctx = LeicaBrowserDialog.select_image_context()
if ctx is not None:
    print(ctx.name, ctx.container_path, ctx.internal_path)
```

3. Minimal multi-select use:

```python
from PyQt6.QtWidgets import QApplication
from leica_browser_qt import LeicaBrowserDialog

app = QApplication([])
contexts = LeicaBrowserDialog.select_image_contexts(
    roots=[r"D:\\data\\run1.lif", r"D:\\data\\experiment_xlef"],
)
for ctx in contexts:
    print(ctx.name, ctx.container_path, ctx.internal_path)
```

4. cideconvolve integration example.
5. Known limitations:
   - first version is browsing/selection focused
   - conversion remains outside this package
   - some Leica variants may need extra backend handling

## Implementation steps

### Step 1 - Create package skeleton

- Create `pyproject.toml`.
- Add src-layout package.
- Add basic README.
- Add minimal CLI.
- Add empty public API.

### Step 2 - Add data models

- Implement `LeicaImageContext`.
- Implement `LeicaImageHandle`.
- Add JSON serialization helper for CLI output.

### Step 3 - Implement scanner/gateway

- Implement `LeicaGateway.scan_roots()`.
- Support files and folders.
- Detect `.lif`, `.xlef`, `.lof`.
- Return a lazy tree structure.
- Add placeholder metadata extraction.

### Step 4 - Port/refactor Leica parsing

- Reuse relevant logic from `ConvertLeica-Docker`.
- Implement:
  - list internal images
  - list internal folders
  - extract dimensions
  - extract channel names
  - extract physical pixel sizes
  - extract useful microscope metadata

### Step 5 - Implement Qt tree browser

- Add `LeicaBrowserDialog`.
- Add tree model.
- Add file/folder buttons.
- Add filter.
- Add OK/Cancel.
- Implement constructor-level `selection_mode="single" | "multiple"`.
- Implement single-select and multi-select helper methods.

### Step 6 - Add preview and metadata panel

- Load preview in worker thread.
- Show image preview.
- Show metadata key/value table.
- Do not block UI on large containers.
- Show readable errors.

### Step 7 - Add pixel loading

- Implement `read_plane()`.
- Implement `read_thumbnail()`.
- Implement `read_array()` only when safe.
- Add lazy/dask loading if practical.

### Step 8 - Add cideconvolve integration example

- Add example code in `examples/cideconvolve_open_leica.py`.
- Then patch `cideconvolve` GUI:
  - add `Open Leica...`
  - use single-select for normal workflows
  - use multi-select for batch workflows
  - load selected image/images
  - pass metadata into existing deconvolution metadata pipeline.

### Step 9 - Tests and packaging

- Add unit tests.
- Add GUI smoke test.
- Add optional integration test with `LEICA_TEST_DATA`.
- Run:

```bash
python -m pip install -e ".[dev]"
pytest
python -m build
```

### Step 10 - First release

- Version `0.1.0`.
- Publish to TestPyPI first.
- Install into the cideconvolve conda env.
- Test:
  - one LIF
  - one XLEF
  - folder with multiple containers
  - single-select image opening
  - multi-select batch opening
  - opening selected images in cideconvolve GUI

## Acceptance criteria

Version `0.1.0` is done when:

1. `pip install leica-browser-qt` works.
2. `leica_browser` opens a PyQt6 browser.
3. User can add multiple LIF/XLEF files or folders.
4. Browser shows file/folder/container/image hierarchy.
5. User can preview an image.
6. User can inspect metadata.
7. Single-select mode returns one selected image or None.
8. Multi-select mode returns one or more selected images as a list.
9. API returns stable `LeicaImageContext` objects.
10. `cideconvolve` can open selected Leica images through the new dialog.
11. Missing metadata or unreadable images show warnings but do not crash.
