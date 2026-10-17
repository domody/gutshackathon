import pygame


class Typewriter:
    """Reveals a sequence of strings one character at a time, in draw order."""

    def __init__(self, chars_per_sec: float = 30) -> None:
        self.chars_per_sec = chars_per_sec
        self.done = False
        self._typed = 0.0
        self._cursor = 0

    def update(self, dt: float) -> None:
        self._typed += dt * self.chars_per_sec

    def begin(self) -> None:
        """Call at the start of each draw."""
        self._cursor = 0

    def end(self) -> None:
        """Call at the end of each draw; sets `done` once every string is fully shown."""
        self.done = int(self._typed) >= self._cursor

    def draw(self, surface: pygame.Surface, font: pygame.font.Font, text: str,
             color: tuple[int, int, int], **anchor: tuple[int, int]) -> pygame.Rect:
        """Draw the typed part of `text`, positioned as if fully typed."""
        rect = font.render(text, True, color).get_rect(**anchor)
        shown = max(0, min(len(text), int(self._typed) - self._cursor))
        self._cursor += len(text)
        if shown:
            surface.blit(font.render(text[:shown], True, color), rect)
        return rect
