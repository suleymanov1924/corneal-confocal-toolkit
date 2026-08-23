"""Art.Suleimanov1924."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameInfo:
    frame_index: int
    filename: str
    path: Path
    source_type: str


@dataclass(frozen=True)
class SelectionEntry:
    frame_index: int
    filename: str
    include: bool
    eye: str
    confidence: str
    depth_um: str
    note: str
