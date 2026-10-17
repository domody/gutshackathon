from abc import ABC, abstractmethod

import pygame


BLANK = (20, 20, 30)  # shared plain backdrop for result and intro screens


class Screen(ABC):
    """A full-screen UI view (menu, intro, level cleared, ...)."""

    fade_in = 0.0   # seconds; 0 shows instantly
    fade_out = 0.0
    background: tuple[int, int, int] | None = None  # opaque backdrop behind the content

    overlay = False  # draws over the live game instead of a backdrop

    def on_enter(self) -> None:
        """Called when the screen becomes active."""

    def on_exit(self) -> None:
        """Called when the screen is replaced or cleared."""

    def draw_background(self, surface: pygame.Surface) -> None:
        if self.background:
            surface.fill(self.background)

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    @abstractmethod
    def draw(self, surface: pygame.Surface) -> None: ...
