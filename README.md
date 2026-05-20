# leica-browser-qt

Reusable PyQt6 dialog for browsing Leica `.lif`, `.xlef`, and standalone `.lof`
files and returning selected image contexts to another application.

The browser is focused on browsing, previewing, metadata inspection, selection,
and direct NumPy pixel reads. Conversion to OME-TIFF remains outside this
package.

Large unmerged tilescans and Leica multiposition data are exposed as an `S`
axis. The browser can either pin one `S` position before returning a context,
or leave `S` as `All` so the viewer keeps interactive control.

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
    print("size_s=", ctx.size_s, "selected_s=", ctx.selected_s)
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

Returned contexts now include:

- `size_s`: number of Leica stage or tile positions when available.
- `selected_s`: the browser-selected fixed `S` position, or `None` when the
    browser was left at `All`.

## Leica Viewer

This package includes an OMERO-viewer-style Leica viewer adapted from
`omero-browser-qt`. It opens the Leica browser, lets you choose one image, and
shows a zoomable microscopy preview with channel toggles, contrast controls,
Z/T controls, optional `S` controls, projection mode, metadata, and a scale bar
when pixel size is available.

Browser and viewer `S` behavior:

- `All` in the browser keeps the full `S` dimension available and the viewer
    shows an `S` slider for interactive browsing.
- `Fixed` in the browser pins one `S` position on the returned context and the
    viewer opens that position directly.
- Browser preview refresh uses the selected `S` position, so changing the
    browser `S` slider changes the preview image.

## Direct Pixel Reads

The public read API accepts an optional `s` argument:

```python
handle = ctx.open()

plane = handle.read_plane(z=0, c=0, t=0, s=3)
stack = handle.read_stack(c=0, t=0, s=3)
arr = handle.read_array(s=3)
```

If `s` is omitted:

- a browser-pinned `ctx.selected_s` is used when present
- otherwise the default remains `s=0`

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

If your application wants to respect the browser's fixed `S` choice, simply use
the returned context normally. If it wants to override that choice, pass `s=`
explicitly to `read_plane()`, `read_stack()`, or `read_array()`.

## Known Limitations

- `read_array()` returns a full in-memory `TCZYX` NumPy array. For large Leica
  datasets, prefer `read_plane()` or `read_stack()` to avoid loading all
  timepoints and channels at once.
- `S` support selects one Leica position at a time. It does not stitch or merge
    tiles into a mosaic.
- Tests use mocked parser output and fake Leica paths unless local Leica test
  data is supplied by a downstream project.
