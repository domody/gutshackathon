from typing import Callable

import pygame

from game.assets import get_font
from game.minigame import Action, Minigame
from game.ui.screen import Screen
from game.ui.typewriter import Typewriter


class MinigameIntro(Screen):
    """Pre-game screen: title, the two actions side by side, and a pinch prompt."""

    TITLE_SIZE = 96
    SUBTITLE_SIZE = 56
    NAME_SIZE = 48
    DESC_SIZE = 32
    BUTTON_SIZE = 56
    TITLE_COLOR = (255, 215, 90)
    TEXT_COLOR = (240, 240, 240)
    DESC_COLOR = (170, 170, 185)
    BUTTON_COLOR = (80, 200, 120)
    BUTTON_HOVER = (110, 230, 150)
    BUTTON_TEXT = (20, 20, 30)

    OVERLAY_COLOR = (12, 12, 22, 185)  # Darken the first game frame by about 72 percent.

    fade_in = 0.4
    fade_out = 0.5
    overlay = True

    def __init__(self, minigame: Minigame, on_okay: Callable[[], None]) -> None:
        self.minigame = minigame
        self.on_okay = on_okay
        self._title_font = get_font(self.TITLE_SIZE)
        self._subtitle_font = get_font(self.SUBTITLE_SIZE)
        self._name_font = get_font(self.NAME_SIZE)
        self._desc_font = get_font(self.DESC_SIZE)
        self._button_font = get_font(self.BUTTON_SIZE)
        self._objective_font = get_font(31)
        self._button_rect = pygame.Rect(0, 0, 0, 0)
        self._writer = Typewriter(60)
        self._dim: pygame.Surface | None = None

    def update(self, dt: float) -> None:
        self._writer.update(dt)

    def draw_background(self, surface: pygame.Surface) -> None:
        if self._dim is None or self._dim.get_size() != surface.get_size():
            self._dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            self._dim.fill(self.OVERLAY_COLOR)
        surface.blit(self._dim, (0, 0))

    def handle_event(self, event: pygame.event.Event) -> None:
        if not self._writer.done:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.on_okay()

    def gesture_continue(self) -> None:
        if self._writer.done:
            self.on_okay()
        else:
            self._writer.finish()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        center_x = width // 2
        w = self._writer
        w.begin()

        title_rect = w.draw(surface, self._title_font, self.minigame.title, self.TITLE_COLOR,
                            midtop=(center_x, height // 8))
        objective_bottom = title_rect.bottom + 14
        for line in self._wrap_with_font(self.minigame.objective, width - 180, self._objective_font):
            objective_rect = w.draw(surface, self._objective_font, line, self.DESC_COLOR,
                                    midtop=(center_x, objective_bottom))
            objective_bottom = objective_rect.bottom + 3
        subtitle_rect = w.draw(surface, self._subtitle_font, "HOW TO PLAY", self.TEXT_COLOR,
                               midtop=(center_x, objective_bottom + 17))

        top = subtitle_rect.bottom + 40
        bottom = top
        for i, action in enumerate(self.minigame.actions):
            col_x = width * (2 * i + 1) // 4
            bottom = max(bottom, self._draw_action(surface, action, col_x, top))

        w.end()
        if w.done:
            self._draw_button(surface, center_x, bottom + 60)

    def _draw_action(
        self, surface: pygame.Surface, action: Action, center_x: int, top: int
    ) -> int:
        w = self._writer
        name_rect = w.draw(surface, self._name_font, action.name, self.TEXT_COLOR,
                           midtop=(center_x, top))
        bottom = name_rect.bottom + 12
        for line in self._wrap(action.description, surface.get_width() // 2 - 80):
            desc_rect = w.draw(surface, self._desc_font, line, self.DESC_COLOR,
                               midtop=(center_x, bottom))
            bottom = desc_rect.bottom + 5
        return bottom

    def _wrap(self, text: str, max_width: int) -> list[str]:
        return self._wrap_with_font(text, max_width, self._desc_font)

    def _wrap_with_font(self, text: str, max_width: int, font: pygame.font.Font) -> list[str]:
        lines: list[str] = []
        line = ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if line and font.size(trial)[0] > max_width:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        return lines

    def _draw_button(self, surface: pygame.Surface, center_x: int, top: int) -> None:
        text = self._button_font.render("PINCH TO BEGIN", True, self.BUTTON_COLOR)
        surface.blit(text, text.get_rect(midtop=(center_x, top)))
