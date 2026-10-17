from typing import Callable

import pygame

from game.minigame import Action, Minigame
from game.ui.screen import Screen
from game.ui.typewriter import Typewriter


class MinigameIntro(Screen):
    """Pre-game screen: title, the two actions side by side, and an Okay button."""

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

    OVERLAY_COLOR = (12, 12, 22, 185)  # ~72% dark over the game's first frame

    fade_in = 0.4
    fade_out = 0.5
    overlay = True

    def __init__(self, minigame: Minigame, on_okay: Callable[[], None]) -> None:
        self.minigame = minigame
        self.on_okay = on_okay
        self._title_font = pygame.font.Font(None, self.TITLE_SIZE)
        self._subtitle_font = pygame.font.Font(None, self.SUBTITLE_SIZE)
        self._name_font = pygame.font.Font(None, self.NAME_SIZE)
        self._desc_font = pygame.font.Font(None, self.DESC_SIZE)
        self._button_font = pygame.font.Font(None, self.BUTTON_SIZE)
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
        if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            self.on_okay()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._button_rect.collidepoint(event.pos):
                self.on_okay()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        center_x = width // 2
        w = self._writer
        w.begin()

        title_rect = w.draw(surface, self._title_font, self.minigame.title, self.TITLE_COLOR,
                            midtop=(center_x, height // 8))
        subtitle_rect = w.draw(surface, self._subtitle_font, "Actions", self.TEXT_COLOR,
                               midtop=(center_x, title_rect.bottom + 30))

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
        desc_rect = w.draw(surface, self._desc_font, action.description, self.DESC_COLOR,
                           midtop=(center_x, name_rect.bottom + 12))
        return desc_rect.bottom

    def _draw_button(self, surface: pygame.Surface, center_x: int, top: int) -> None:
        text = self._button_font.render("Okay", True, self.BUTTON_TEXT)
        self._button_rect = text.get_rect().inflate(80, 30)
        self._button_rect.midtop = (center_x, top)
        hovered = self._button_rect.collidepoint(pygame.mouse.get_pos())
        color = self.BUTTON_HOVER if hovered else self.BUTTON_COLOR
        pygame.draw.rect(surface, color, self._button_rect, border_radius=12)
        surface.blit(text, text.get_rect(center=self._button_rect.center))
