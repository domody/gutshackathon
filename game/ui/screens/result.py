from typing import Callable

import pygame

from game.ui.screen import BLANK, Screen
from game.ui.typewriter import Typewriter


class ResultScreen(Screen):
    """Title and description; a pinch continues."""

    TITLE_SIZE = 120
    DESC_SIZE = 56
    HINT_SIZE = 32
    DESC_COLOR = (240, 240, 240)
    HINT_COLOR = (170, 170, 185)
    TITLE_COLOR = (255, 215, 90)
    TITLE = ""
    DESCRIPTION = ""

    fade_in = 0.4
    fade_out = 0.4
    background = BLANK
    SCORE_STAGE_SECONDS = 0.3

    def __init__(self, on_continue: Callable[[], None], total_score: int | None = None,
                 round_score: int = 0) -> None:
        self.on_continue = on_continue
        self.total_score = total_score
        self.round_score = round_score
        self._score_elapsed = 0.0
        self._writer = Typewriter()
        self._title_font = pygame.font.Font(None, self.TITLE_SIZE)
        self._desc_font = pygame.font.Font(None, self.DESC_SIZE)
        self._hint_font = pygame.font.Font(None, self.HINT_SIZE)
        self._score_font = pygame.font.Font(None, 42)

    @property
    def display_score(self) -> int | None:
        if self.total_score is None:
            return None
        if self._score_elapsed < self.SCORE_STAGE_SECONDS * 2:
            return self.total_score - self.round_score
        return self.total_score

    def handle_event(self, event: pygame.event.Event) -> None:
        if not self._writer.done:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.on_continue()

    def gesture_continue(self) -> None:
        if self._writer.done:
            self.on_continue()
        else:
            self._writer.finish()

    def update(self, dt: float) -> None:
        self._writer.update(dt)
        self._score_elapsed += dt

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        w = self._writer
        w.begin()
        title_rect = w.draw(surface, self._title_font, self.TITLE, self.TITLE_COLOR,
                            midbottom=(width // 2, height // 2))
        description_rect = w.draw(surface, self._desc_font, self.DESCRIPTION, self.DESC_COLOR,
                                  midtop=(width // 2, title_rect.bottom + 20))
        w.end()
        if self.total_score is not None:
            score_y = description_rect.bottom + 28
            if self._score_elapsed < self.SCORE_STAGE_SECONDS:
                score = self._score_font.render(
                    f"Score: {self.total_score - self.round_score:,}", True, self.DESC_COLOR
                )
                surface.blit(score, score.get_rect(midtop=(width // 2, score_y)))
            elif self._score_elapsed < self.SCORE_STAGE_SECONDS * 2:
                before = self._score_font.render(
                    f"Score: {self.total_score - self.round_score:,}", True, self.DESC_COLOR
                )
                earned = self._score_font.render(f"+{self.round_score:,}", True, (100, 230, 130))
                before_rect = before.get_rect(midright=(width // 2 - 8, score_y + before.get_height() // 2))
                earned_rect = earned.get_rect(midleft=(width // 2 + 8, score_y + earned.get_height() // 2))
                surface.blit(before, before_rect)
                surface.blit(earned, earned_rect)
            else:
                score = self._score_font.render(f"Total Score: {self.total_score:,}", True, self.DESC_COLOR)
                surface.blit(score, score.get_rect(midtop=(width // 2, score_y)))
        if w.done:
            hint = self._hint_font.render("Pinch your fingers together to continue", True, self.HINT_COLOR)
            surface.blit(hint, hint.get_rect(midbottom=(width // 2, height - 40)))


class PassScreen(ResultScreen):
    TITLE = "You Pass"
    DESCRIPTION = "Onto the next level."
    TITLE_COLOR = (110, 230, 150)


class FailScreen(ResultScreen):
    TITLE = "You Fail"
    DESCRIPTION = "Better luck next time."
    TITLE_COLOR = (235, 90, 90)


class FiredScreen(ResultScreen):
    TITLE = "You're Fired"
    DESCRIPTION = "Three strikes. Pack up your desk."
    TITLE_COLOR = (235, 90, 90)
