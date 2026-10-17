from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Game-wide configuration."""

    title: str = "My First Day at JPMorganChase"
    window_size: tuple[int, int] = (800, 600)
    fullscreen: bool = True
    fps: int = 60
    background: tuple[int, int, int] = (20, 20, 30)
