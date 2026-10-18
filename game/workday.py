"""Story time, deliberately separate from the real-time round countdowns."""
import math

import pygame

from game.assets import get_font


SCHEDULE = {
    "Contract Signing Day": (540, "Onboarding", 1),
    "Act Natural": (550, "Morning rush", 2),
    "Who's Talking?": (570, "Team meeting", 3),
    "Any Volunteers?": (660, "Back to work", 4),
    "A Quick Favour": (680, "Extra paperwork", 4),
    "Merge Request Review": (780, "Afternoon work", 5),
    "Coffee Run": (930, "Coffee run", 6),
    "One Last Print": (1019, "Nearly home", 7),
}


class WorkdayClock:
    def __init__(self) -> None:
        self.minutes = 540
        self.chapter = "Onboarding"
        self.step = 1

    def enter(self, title: str) -> None:
        minutes, self.chapter, self.step = SCHEDULE.get(title, (self.minutes, self.chapter, self.step))
        self.minutes = max(self.minutes, minutes)

    def complete(self) -> None:
        self.minutes, self.chapter, self.step = 1020, "Home time!", 7

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, (self.minutes - 540) / 480))

    def draw(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        rect = pygame.Rect(w - 224, 176, 210, 94)
        if h < 500:
            rect.y = 12
            rect.x = 12
        pygame.draw.rect(surface, (12, 36, 59), rect, border_radius=14)
        center = (rect.x + 30, rect.y + 31)
        pygame.draw.circle(surface, (250, 243, 218), center, 21)
        for angle, length in ((self.minutes / 60 * math.tau / 12, 11),
                              (self.minutes % 60 * math.tau / 60, 16)):
            end = (round(center[0] + math.sin(angle) * length), round(center[1] - math.cos(angle) * length))
            pygame.draw.line(surface, (12, 36, 59), center, end, 3)
        stamp = f"{self.minutes // 60:02d}:{self.minutes % 60:02d}"
        surface.blit(get_font(30).render(stamp, True, (255, 215, 90)), (rect.x + 62, rect.y + 11))
        surface.blit(get_font(18).render(f"WORKDAY  {self.step}/7", True, (180, 211, 227)), (rect.x + 62, rect.y + 39))
        pygame.draw.rect(surface, (47, 68, 88), (rect.x + 12, rect.y + 64, 186, 5), border_radius=2)
        pygame.draw.rect(surface, (86, 192, 148), (rect.x + 12, rect.y + 64, round(186 * self.progress), 5), border_radius=2)
        surface.blit(get_font(18).render(self.chapter, True, (235, 237, 225)), (rect.x + 12, rect.y + 75))
