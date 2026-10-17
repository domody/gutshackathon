from typing import Callable

import pygame

from game.ui.screen import Screen


class ResultScreen(Screen):
    """Title and description; any key or click continues."""

    TITLE_SIZE = 120
    DESC_SIZE = 56
    HINT_SIZE = 32
    DESC_COLOR = (240, 240, 240)
    HINT_COLOR = (170, 170, 185)
    TITLE_COLOR = (255, 215, 90)
    TITLE = ""
    DESCRIPTION = ""

    def __init__(self, on_continue: Callable[[], None]) -> None:
        self.on_continue = on_continue
        self._title_font = pygame.font.Font(None, self.TITLE_SIZE)
        self._desc_font = pygame.font.Font(None, self.DESC_SIZE)
        self._hint_font = pygame.font.Font(None, self.HINT_SIZE)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self.on_continue()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.on_continue()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        title = self._title_font.render(self.TITLE, True, self.TITLE_COLOR)
        title_rect = title.get_rect(midbottom=(width // 2, height // 2))
        surface.blit(title, title_rect)

        desc = self._desc_font.render(self.DESCRIPTION, True, self.DESC_COLOR)
        desc_rect = desc.get_rect(midtop=(width // 2, title_rect.bottom + 20))
        surface.blit(desc, desc_rect)

        hint = self._hint_font.render("Press Enter to continue", True, self.HINT_COLOR)
        surface.blit(hint, hint.get_rect(midbottom=(width // 2, height - 40)))


class PassScreen(ResultScreen):
    TITLE = "You Pass"
    DESCRIPTION = "Onto the next level."
    TITLE_COLOR = (110, 230, 150)


class FailScreen(ResultScreen):
    TITLE = "You Fail"
    DESCRIPTION = "Better luck next time."
    TITLE_COLOR = (235, 90, 90)
