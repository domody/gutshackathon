"""Shared asset loading, scaling and font helpers."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pygame

GAME_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games", "assets")
ROOT_ASSETS = Path(__file__).resolve().parents[1] / "assets"
SCENES_DIR = ROOT_ASSETS / "scenes"
MENU_DIR = ROOT_ASSETS / "menu"


def load_image(name: str | os.PathLike, alpha: bool = True, base: str | os.PathLike = GAME_ASSETS) -> pygame.Surface:
    """Load an image (relative to `base`), converting if a display exists."""
    image = pygame.image.load(os.path.join(base, name))
    if pygame.display.get_surface():
        image = image.convert_alpha() if alpha else image.convert()
    return image


def key_pink(image: pygame.Surface, min_rb: int = 80, ratio: float = 0.70, max_diff: int = 100) -> np.ndarray:
    """Make magenta chroma-key pixels transparent in place; returns the RGB array."""
    rgb = pygame.surfarray.array3d(image)
    alpha = pygame.surfarray.pixels_alpha(image)
    red = rgb[:, :, 0].astype(np.int16)
    green = rgb[:, :, 1].astype(np.int16)
    blue = rgb[:, :, 2].astype(np.int16)
    pink = ((red > min_rb) & (blue > min_rb) & (green < np.minimum(red, blue) * ratio)
            & (np.abs(red - blue) < max_diff))
    alpha[pink] = 0
    del alpha
    return rgb


def crop_to_alpha(image: pygame.Surface) -> tuple[pygame.Surface, pygame.Rect]:
    """Crop to the non-transparent bounds; returns (surface, bounds)."""
    bounds = image.get_bounding_rect(min_alpha=8)
    if not (bounds.width and bounds.height):
        return image, image.get_rect()
    return image.subsurface(bounds).copy(), bounds


def load_chroma(name: str, **key_args) -> tuple[pygame.Surface, pygame.Rect]:
    """Load a pink-keyed image, cropped to its visible bounds."""
    image = load_image(name)
    key_pink(image, **key_args)
    return crop_to_alpha(image)


def scale_to_height(image: pygame.Surface, height: int) -> pygame.Surface:
    width = max(1, round(image.get_width() * height / image.get_height()))
    return pygame.transform.smoothscale(image, (width, height))


def scale_to_width(image: pygame.Surface, width: int) -> pygame.Surface:
    height = max(1, round(image.get_height() * width / image.get_width()))
    return pygame.transform.smoothscale(image, (width, height))


def cover(image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    """Scale to fill `size`, cropped to the centre."""
    iw, ih = image.get_size()
    scale = max(size[0] / iw, size[1] / ih)
    big = pygame.transform.smoothscale(
        image, (max(size[0], round(iw * scale)), max(size[1], round(ih * scale))))
    crop = pygame.Rect(0, 0, *size)
    crop.center = big.get_rect().center
    return big.subsurface(crop).copy()


@lru_cache(maxsize=None)
def get_font(size: int) -> pygame.font.Font:
    """Shared default font; don't mutate it (italic/bold), build your own instead."""
    return pygame.font.Font(None, size)
