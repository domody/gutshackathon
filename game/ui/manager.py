from typing import Callable

import pygame

from game.ui.screen import Screen

Backdrop = Callable[[pygame.Surface], None]


class ScreenManager:
    """Holds the active screen, forwards input, and fades screens in and out."""

    def __init__(self) -> None:
        self.current: Screen | None = None
        self._backdrop: Backdrop | None = None
        self._state = "idle"  # Current transition: "in", "idle" or "out".
        self._t = 0.0
        self._after: Callable[[], None] | None = None
        self._fade_bg = False
        self._layer: pygame.Surface | None = None

    @property
    def active(self) -> bool:
        return self.current is not None

    def show(self, screen: Screen, backdrop: Backdrop | None = None) -> None:
        """Show a screen, fading in over an optional backdrop drawn beneath it."""
        self.clear()
        self.current = screen
        self._backdrop = backdrop
        self._state = "in" if screen.fade_in > 0 else "idle"
        self._t = 0.0
        screen.on_enter()

    def clear(self) -> None:
        if self.current:
            self.current.on_exit()
        self.current = None
        self._backdrop = None
        self._state = "idle"
        self._after = None

    @property
    def leaving(self) -> bool:
        return self._state == "out"

    def dismiss(self, after: Callable[[], None], fade_background: bool = False,
                backdrop: Backdrop | None = None) -> None:
        """Fade the content out (and the background too, if asked), then call `after`."""
        if self._state == "out":
            return
        if not self.current or self.current.fade_out <= 0:
            after()
            return
        self._state = "out"
        self._t = 0.0
        self._after = after
        self._fade_bg = fade_background
        if backdrop:
            self._backdrop = backdrop

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.current and self._state == "idle":
            self.current.handle_event(event)

    def update(self, dt: float) -> None:
        if not self.current:
            return
        if self._state == "in":
            self._t += dt
            if self._t >= self.current.fade_in:
                self._state = "idle"
                self._backdrop = None  # The screen is opaque now, so the old backdrop is no longer needed.
        elif self._state == "out":
            self._t += dt
            if self._t >= self.current.fade_out:
                after, self._after = self._after, None
                self._state = "idle"
                if after:
                    after()
        else:
            self.current.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        cur = self.current
        if not cur:
            return
        if self._backdrop:
            self._backdrop(surface)
        if self._state == "in":
            alpha = self._t / cur.fade_in
            bg_alpha = alpha
        elif self._state == "out":
            alpha = 1 - self._t / cur.fade_out
            bg_alpha = alpha if self._fade_bg else 1.0
        else:
            alpha = bg_alpha = 1.0
        self._draw_faded(surface, cur.draw_background, bg_alpha)
        self._draw_faded(surface, cur.draw, alpha)

    def _draw_faded(self, surface: pygame.Surface, draw: Callable[[pygame.Surface], None],
                    alpha: float) -> None:
        alpha = max(0.0, min(1.0, alpha))
        if alpha >= 1:
            draw(surface)
            return
        if alpha <= 0:
            return
        if self._layer is None or self._layer.get_size() != surface.get_size():
            self._layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        self._layer.fill((0, 0, 0, 0))
        draw(self._layer)
        self._layer.set_alpha(int(255 * alpha))
        surface.blit(self._layer, (0, 0))
