from __future__ import annotations

import math
from collections.abc import Callable

import pygame

from game.assets import get_font
from game.ui.screen import Screen


SCHEDULE = {
    "Contract Signing Day": (540, "Onboarding", 1),
    "Act Natural": (550, "Run to the meeting", 2),
    "Who's Talking?": (570, "Team meeting", 3),
    "Any Volunteers?": (660, "Morning work", 4),
    "A Quick Favour": (680, "Extra paperwork", 4),
    "Merge Request Review": (780, "Merge reviews", 5),
    "Coffee Run": (930, "Coffee run", 6),
    "One Last Print": (1019, "Nearly home", 7),
}


class WorkdayClock:
    def __init__(self) -> None:
        self.minutes = 540
        self.chapter = "Onboarding"
        self.step = 1

    def enter(self, title: str) -> None:
        minutes, chapter, step = SCHEDULE.get(title, (self.minutes, self.chapter, self.step))
        self.minutes = max(self.minutes, minutes)
        if minutes >= self.minutes:
            self.chapter = chapter
            self.step = max(self.step, step)

    def complete(self) -> None:
        self.minutes = 1020
        self.chapter = "Home time"
        self.step = 7

    @property
    def stamp(self) -> str:
        return f"{self.minutes // 60:02d}:{self.minutes % 60:02d}"

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, (self.minutes - 540) / 480))

    def draw(self, surface: pygame.Surface) -> None:
        width, _ = surface.get_size()
        panel = pygame.Rect(width - 204, 176, 190, 82)
        pygame.draw.rect(surface, (8, 34, 60), panel, border_radius=13)
        pygame.draw.rect(surface, (72, 130, 170), panel, 2, border_radius=13)
        center = (panel.x + 27, panel.y + 27)
        pygame.draw.circle(surface, (248, 242, 220), center, 19)
        self._draw_hands(surface, center, 10, 15)
        surface.blit(get_font(28).render(self.stamp, True, (255, 215, 90)), (panel.x + 54, panel.y + 9))
        surface.blit(get_font(17).render(self.chapter.upper(), True, (224, 233, 237)), (panel.x + 54, panel.y + 38))
        bar = pygame.Rect(panel.x + 12, panel.bottom - 13, panel.width - 24, 5)
        pygame.draw.rect(surface, (48, 70, 88), bar, border_radius=3)
        pygame.draw.rect(surface, (82, 190, 145), (bar.x, bar.y, round(bar.width * self.progress), bar.height), border_radius=3)

    def _draw_hands(self, surface: pygame.Surface, center: tuple[int, int], hour_length: int, minute_length: int) -> None:
        for angle, length in (
            ((self.minutes / 60) * math.tau / 12, hour_length),
            ((self.minutes % 60) * math.tau / 60, minute_length),
        ):
            end = (
                round(center[0] + math.sin(angle) * length),
                round(center[1] - math.cos(angle) * length),
            )
            pygame.draw.line(surface, (8, 34, 60), center, end, 3)


class WorkdayChapterScreen(Screen):
    background = (8, 28, 50)
    suppress_corner_score = True
    fade_in = 0.4
    fade_out = 0.4
    DISPLAY_SECONDS = 1.8

    def __init__(self, clock: WorkdayClock, on_continue: Callable[[], None]) -> None:
        self.clock = clock
        self.on_continue = on_continue
        self.elapsed = 0.0
        self.continuing = False

    def update(self, dt: float) -> None:
        self.elapsed += dt
        if self.elapsed >= self.DISPLAY_SECONDS:
            self._continue()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._continue()

    def gesture_continue(self) -> None:
        self._continue()

    def _continue(self) -> None:
        if not self.continuing:
            self.continuing = True
            self.on_continue()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        clock_center = (width // 2, int(height * 0.37))
        radius = max(58, min(92, height // 7))
        pygame.draw.circle(surface, (247, 242, 221), clock_center, radius)
        pygame.draw.circle(surface, (62, 124, 167), clock_center, radius, 5)
        self.clock._draw_hands(surface, clock_center, int(radius * 0.48), int(radius * 0.68))
        time_art = get_font(max(64, min(96, height // 8))).render(self.clock.stamp, True, (255, 215, 90))
        surface.blit(time_art, time_art.get_rect(midtop=(width // 2, clock_center[1] + radius + 20)))
        chapter = get_font(max(30, min(48, height // 16))).render(self.clock.chapter.upper(), True, (242, 244, 236))
        surface.blit(chapter, chapter.get_rect(midtop=(width // 2, clock_center[1] + radius + 104)))
        label = get_font(23).render("STORY TIME", True, (161, 205, 231))
        surface.blit(label, label.get_rect(midbottom=(width // 2, clock_center[1] - radius - 24)))
        bar = pygame.Rect(0, 0, min(520, int(width * 0.42)), 8)
        bar.midtop = (width // 2, clock_center[1] + radius + 172)
        pygame.draw.rect(surface, (38, 72, 99), bar, border_radius=4)
        filled = bar.copy()
        filled.width = max(8, round(bar.width * self.clock.progress))
        pygame.draw.rect(surface, (82, 190, 145), filled, border_radius=4)
