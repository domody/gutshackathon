from typing import Callable

import pygame

from game.minigame import Action, Minigame


class MinigameIntro:
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

    def __init__(self, minigame: Minigame, on_okay: Callable[[], None]) -> None:
        self.minigame = minigame
        self.on_okay = on_okay
        self._title_font = pygame.font.Font(None, self.TITLE_SIZE)
        self._subtitle_font = pygame.font.Font(None, self.SUBTITLE_SIZE)
        self._name_font = pygame.font.Font(None, self.NAME_SIZE)
        self._desc_font = pygame.font.Font(None, self.DESC_SIZE)
        self._button_font = pygame.font.Font(None, self.BUTTON_SIZE)
        self._button_rect = pygame.Rect(0, 0, 0, 0)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (
            pygame.K_RETURN,
            pygame.K_SPACE,
        ):
            self.on_okay()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._button_rect.collidepoint(event.pos):
                self.on_okay()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        center_x = width // 2

        title = self._title_font.render(self.minigame.title, True, self.TITLE_COLOR)
        title_rect = title.get_rect(midtop=(center_x, height // 8))
        surface.blit(title, title_rect)

        subtitle = self._subtitle_font.render("Actions", True, self.TEXT_COLOR)
        subtitle_rect = subtitle.get_rect(midtop=(center_x, title_rect.bottom + 30))
        surface.blit(subtitle, subtitle_rect)

        top = subtitle_rect.bottom + 40
        bottom = top
        for i, action in enumerate(self.minigame.actions):
            col_x = width * (2 * i + 1) // 4
            bottom = max(bottom, self._draw_action(surface, action, col_x, top))

        self._draw_button(surface, center_x, bottom + 60)

    def _draw_action(
        self, surface: pygame.Surface, action: Action, center_x: int, top: int
    ) -> int:
        name = self._name_font.render(action.name, True, self.TEXT_COLOR)
        name_rect = name.get_rect(midtop=(center_x, top))
        surface.blit(name, name_rect)

        desc = self._desc_font.render(action.description, True, self.DESC_COLOR)
        desc_rect = desc.get_rect(midtop=(center_x, name_rect.bottom + 12))
        surface.blit(desc, desc_rect)
        return desc_rect.bottom

    def _draw_button(self, surface: pygame.Surface, center_x: int, top: int) -> None:
        text = self._button_font.render("Okay", True, self.BUTTON_TEXT)
        self._button_rect = text.get_rect().inflate(80, 30)
        self._button_rect.midtop = (center_x, top)
        hovered = self._button_rect.collidepoint(pygame.mouse.get_pos())
        color = self.BUTTON_HOVER if hovered else self.BUTTON_COLOR
        pygame.draw.rect(surface, color, self._button_rect, border_radius=12)
        surface.blit(text, text.get_rect(center=self._button_rect.center))
