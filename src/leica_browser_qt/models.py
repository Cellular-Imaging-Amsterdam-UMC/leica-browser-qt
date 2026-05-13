from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class LeicaImageContext:
    """Stable description of one selected Leica image.

    The context is intentionally serializable and backend-neutral. It contains
    enough file path and internal image identity to reopen the image later.
    """

    name: str
    container_path: Path
    internal_path: str
    image_id: str | None
    kind: str
    size_x: int | None = None
    size_y: int | None = None
    size_z: int | None = None
    size_c: int | None = None
    size_t: int | None = None
    pixel_size_x_um: float | None = None
    pixel_size_y_um: float | None = None
    pixel_size_z_um: float | None = None
    channel_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.container_path = Path(self.container_path)

    def open(self) -> "LeicaImageHandle":
        return LeicaImageHandle(self)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["container_path"] = str(self.container_path)
        return _json_safe(data)


class LeicaImageHandle:
    """Thin image handle that delegates pixel work to the configured gateway."""

    def __init__(self, context: LeicaImageContext) -> None:
        self.context = context

    def read_thumbnail(self, max_size: int = 512):
        from .leica_gateway import LeicaGateway

        return LeicaGateway().read_thumbnail(self.context, max_size=max_size)

    def read_plane(self, z: int = 0, c: int = 0, t: int = 0):
        from .leica_gateway import LeicaGateway

        return LeicaGateway().read_plane(self.context, z=z, c=c, t=t)

    def read_stack(self, c: int = 0, t: int = 0, progress=None):
        from .leica_pixels import read_leica_stack

        return read_leica_stack(self.context, c=c, t=t, progress=progress)

    def read_array(self):
        from .leica_gateway import LeicaGateway

        return LeicaGateway().read_array(self.context)

    def read_lazy(self):
        raise NotImplementedError("Lazy Leica reading is not implemented in this first browser release.")
