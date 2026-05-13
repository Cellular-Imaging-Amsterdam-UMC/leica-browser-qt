# leica-browser-qt

Reusable PyQt6 dialog for browsing Leica `.lif`, `.xlef`, and standalone `.lof`
files and returning selected image contexts to another application.

The browser is focused on browsing, previewing, metadata inspection, selection,
and direct NumPy pixel reads. Conversion to OME-TIFF remains outside this
package.

## Install

```bash
pip install -e .
```

The Leica browser and preview backend is bundled from the browser/preview parts
of [NL-BioImaging/ConvertLeica-Docker](https://github.com/NL-BioImaging/ConvertLeica-Docker).
It uses the same underlying reader and preview functions that `ConvertLeicaQT.py`
uses:

- `ReadLeicaLIF.read_leica_lif`
- `ReadLeicaXLEF.read_leica_xlef`
- `ReadLeicaLOF.read_leica_lof`
- `CreatePreview.create_preview_image`

## Single Select

```python
from PyQt6.QtWidgets import QApplication
from leica_browser_qt import LeicaBrowserDialog

app = QApplication([])
ctx = LeicaBrowserDialog.select_image_context(roots=[r"D:\data"])
if ctx is not None:
    print(ctx.name, ctx.container_path, ctx.internal_path)
```

## Multi Select

```python
from PyQt6.QtWidgets import QApplication
from leica_browser_qt import LeicaBrowserDialog

app = QApplication([])
contexts = LeicaBrowserDialog.select_image_contexts(
    roots=[r"D:\data\run1.lif", r"D:\data\experiment.xlef"],
)
for ctx in contexts:
    print(ctx.name, ctx.container_path, ctx.internal_path)
```

## CLI

```bash
leica_browser D:\data
leica_browser file1.lif file2.xlef file3.lof --multi
python -m leica_browser_qt.cli file1.lof --single
leica_viewer
run_viewer.cmd
python -m leica_browser_qt.leica_viewer
```

The CLI prints selected contexts as JSON.

## Leica Viewer

This package includes an OMERO-viewer-style Leica viewer adapted from
`omero-browser-qt`. It opens the Leica browser, lets you choose one image, and
shows a zoomable microscopy preview with channel toggles, contrast controls,
Z/T controls, projection mode, metadata, and a scale bar when pixel size is
available.

```python
from PyQt6.QtWidgets import QApplication
from leica_browser_qt import LeicaViewerWindow

app = QApplication([])
win = LeicaViewerWindow()
win.show()
app.exec()
```

## cideconvolve-style Integration

```python
from leica_browser_qt import LeicaBrowserDialog


def open_leica_single(parent):
    ctx = LeicaBrowserDialog.select_image_context(parent=parent)
    if ctx is None:
        return None
    handle = ctx.open()
    return handle.read_array(), ctx.metadata  # TCZYX NumPy array


def open_leica_multiple(parent):
    contexts = LeicaBrowserDialog.select_image_contexts(parent=parent)
    results = []
    for ctx in contexts:
        handle = ctx.open()
        results.append((handle.read_array(), ctx.metadata))
    return results
```

## Known Limitations

- `read_array()` returns a full in-memory `TCZYX` NumPy array. For large Leica
  datasets, prefer `read_plane()` or `read_stack()` to avoid loading all
  timepoints and channels at once.
- Tests use mocked parser output and fake Leica paths unless local Leica test
  data is supplied by a downstream project.
