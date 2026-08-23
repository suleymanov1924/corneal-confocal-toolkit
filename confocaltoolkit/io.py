"""Art.Suleimanov1924."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from .algorithm import IMAGE_SIZE_PX


def extract_frame_index(path: Path) -> int:
    match = re.search(r"\((\d+)\)", path.name)
    if match:
        return int(match.group(1))
    fallback = re.findall(r"\d+", path.stem)
    if fallback:
        return int(fallback[-1])
    raise ValueError(f"Cannot determine frame index from {path.name}")


def discover_frames(study_dir: Path) -> list[Path]:
    files = [
        path
        for path in study_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".bmp", ".raw"}
    ]
    return sorted(files, key=lambda path: (extract_frame_index(path), path.suffix.lower(), path.name.lower()))


def load_grayscale_frame(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".raw":
        data = path.read_bytes()
        expected = IMAGE_SIZE_PX * IMAGE_SIZE_PX
        if len(data) != expected:
            raise ValueError(
                f"RAW frame {path.name} has {len(data)} bytes; expected {expected} for a single 384x384 HRT-III frame."
            )
        frame = np.frombuffer(data, dtype=np.uint8).reshape((IMAGE_SIZE_PX, IMAGE_SIZE_PX))
        return frame.astype(np.float32)

    image = Image.open(path).convert("L")
    data = np.asarray(image, dtype=np.float32)
    return data[:IMAGE_SIZE_PX, :IMAGE_SIZE_PX]
