from leica_browser_qt import LeicaBrowserDialog


def open_leica_single(parent):
    ctx = LeicaBrowserDialog.select_image_context(parent=parent)
    if ctx is None:
        return None
    handle = ctx.open()
    arr = handle.read_array()
    metadata = ctx.metadata
    return arr, metadata


def open_leica_multiple(parent):
    contexts = LeicaBrowserDialog.select_image_contexts(parent=parent)
    results = []
    for ctx in contexts:
        handle = ctx.open()
        results.append((handle.read_array(), ctx.metadata))
    return results

