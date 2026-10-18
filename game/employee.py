from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pygame


def data_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "InternSurvival"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "InternSurvival"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "intern-survival"


def normalize_signature(strokes) -> list[list[tuple[float, float]]]:
    paths = [[(float(point[0]), float(point[1])) for point in stroke] for stroke in strokes if stroke]
    points = [point for stroke in paths for point in stroke]
    if not points:
        return []
    left = min(point[0] for point in points)
    top = min(point[1] for point in points)
    width = max(1.0, max(point[0] for point in points) - left)
    height = max(1.0, max(point[1] for point in points) - top)
    scale = max(width, height)
    return [[((x - left) / scale, (y - top) / scale) for x, y in path] for path in paths]


def signature_image(strokes, size: tuple[int, int] = (640, 180)) -> pygame.Surface:
    image = pygame.Surface(size, pygame.SRCALPHA)
    points = [point for path in strokes for point in path]
    if not points:
        return image
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    source_width = max(max_x, 0.001)
    source_height = max(max_y, 0.001)
    scale = min((size[0] - 20) / source_width, (size[1] - 20) / source_height)
    offset_x = (size[0] - source_width * scale) / 2
    offset_y = (size[1] - source_height * scale) / 2
    line_width = max(2, size[1] // 48)
    for path in strokes:
        pixels = [(round(offset_x + x * scale), round(offset_y + y * scale)) for x, y in path]
        if len(pixels) > 1:
            pygame.draw.lines(image, (25, 74, 124), False, pixels, line_width)
        elif pixels:
            pygame.draw.circle(image, (25, 74, 124), pixels[0], line_width)
    return image


class EmployeeRecord:
    def __init__(self, root: Path | None = None) -> None:
        self.run_id = uuid4().hex
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.directory = (root if root is not None else data_root()) / "runs" / self.run_id
        self.signature: list[list[tuple[float, float]]] = []
        self.photo: pygame.Surface | None = None
        self.save_error: str | None = None
        self.save()

    def save(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            document = {
                "version": 1,
                "run_id": self.run_id,
                "started_at": self.started_at,
                "signature": self.signature,
                "photo": "photo.png" if self.photo is not None else None,
            }
            temporary = self.directory / "employee.json.tmp"
            temporary.write_text(json.dumps(document), encoding="utf-8")
            temporary.replace(self.directory / "employee.json")
        except OSError as exc:
            self.save_error = str(exc)

    def set_signature(self, strokes) -> None:
        self.signature = normalize_signature(strokes)
        self.save()
        if self.signature:
            self._save_image(signature_image(self.signature), "signature.png")

    def set_photo(self, photo: pygame.Surface) -> None:
        self.photo = photo.copy()
        self._save_image(self.photo, "photo.png")
        self.save()

    def _save_image(self, image: pygame.Surface, name: str) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / f"pending-{name}"
            pygame.image.save(image, str(temporary))
            temporary.replace(self.directory / name)
        except (OSError, pygame.error) as exc:
            self.save_error = str(exc)

    def signature_surface(self) -> pygame.Surface | None:
        return signature_image(self.signature) if self.signature else None
