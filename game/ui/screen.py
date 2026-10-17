from abc import ABC, abstractmethod

import pygame


class Screen(ABC):
    """A full-screen UI view (menu, intro, level cleared, ...)."""

    def on_enter(self) -> None:
        """Called when the screen becomes active."""

    def on_exit(self) -> None:
        """Called when the screen is replaced or cleared."""

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    @abstractmethod
    def draw(self, surface: pygame.Surface) -> None: ...
