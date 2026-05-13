"""Tree helpers for the Qt browser.

The first implementation uses QTreeWidget for a compact embeddable dialog.
This module keeps shared role names and flattening helpers separate so a later
QAbstractItemModel can replace the widget-backed tree without changing the
dialog API.
"""

from __future__ import annotations

from collections.abc import Iterable

from .leica_gateway import LeicaTreeNode
from .models import LeicaImageContext


def iter_image_contexts(nodes: Iterable[LeicaTreeNode]) -> Iterable[LeicaImageContext]:
    for node in nodes:
        if node.context is not None:
            yield node.context
        yield from iter_image_contexts(node.children)

