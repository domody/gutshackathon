import pygame

from game.ui.screen import Screen


class ScreenManager:
    """Holds the active screen and forwards events, updates and drawing to it."""

    def __init__(self) -> None:
        self.current: Screen | None = None

    @property
    def active(self) -> bool:
        return self.current is not None

    def show(self, screen: Screen) -> None:
        self.clear()
        self.current = screen
        screen.on_enter()

    def clear(self) -> None:
        if self.current:
            self.current.on_exit()
        self.current = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.current:
            self.current.handle_event(event)

    def update(self, dt: float) -> None:
        if self.current:
            self.current.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        if self.current:
            self.current.draw(surface)
