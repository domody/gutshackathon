from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from game.audio import sound_bank
from game.assets import get_font

if TYPE_CHECKING:
    from game.tracking import CameraTracker


@dataclass(frozen=True)
class Action:
    """One of a minigame's two actions, as shown in its tutorial."""

    name: str
    description: str


class Minigame(ABC):
    """Base class for minigames. Subclasses implement the logic and expose two actions."""

    BASE_SCORE = 1000
    MIN_SCORE = 200
    title: str = "Minigame"
    objective: str = "Complete the task before time runs out."
    tracker_cls: type[CameraTracker] | None = None  # Set this to enable camera tracking.

    def __init__(self, screen: pygame.Surface, tracker: CameraTracker | None = None) -> None:
        self.screen = screen
        self.finished = False
        self.won = False
        self._score = 0
        self.day_strikes = 0
        self.strike_limit = 3
        self.strike_earned = False
        self.combo = 0
        self.combo_message = ""
        self.combo_until = 0

        pygame.font.init()
        self.font = get_font(36)
        self.small_font = get_font(24)
        self.big_font = get_font(72)

        # A shared tracker can be passed in when minigames use the same camera.
        self.tracker = tracker
        self._owns_tracker = False
        if self.tracker_cls is not None:
            self._owns_tracker = tracker is None
            self.tracker = tracker if tracker is not None else self.tracker_cls()
            self.tracker.start()

    @property
    @abstractmethod
    def actions(self) -> tuple[Action, Action]:
        """Exactly two actions; the tutorial is built from these."""

    def start(self) -> None:
        """Reset state when the minigame begins. Subclasses call super().start()."""
        self.finished = False
        self.won = False
        self._score = 0
        self.strike_earned = False
        self.combo = 0
        self.combo_message = ""
        self.combo_until = 0

    def register_combo_success(self) -> None:
        self.combo += 1
        if self.combo < 2:
            return
        if self.combo >= 8:
            label = "OFFICE PRODIGY"
        elif self.combo >= 5:
            label = "SUSPICIOUSLY COMPETENT"
        elif self.combo >= 3:
            label = "ON A ROLL"
        else:
            label = "NICE WORK"
        self.combo_message = f"{label}  x{self.combo}"
        self.combo_until = pygame.time.get_ticks() + 1050
        sound_bank.play("combo")

    def reset_combo(self) -> None:
        self.combo = 0
        self.combo_message = ""
        self.combo_until = 0

    def draw_combo(self, screen: pygame.Surface) -> None:
        if not self.combo_message or pygame.time.get_ticks() >= self.combo_until:
            return
        art = get_font(max(28, min(42, screen.get_height() // 19))).render(
            self.combo_message, True, (255, 215, 90)
        )
        panel = art.get_rect(midtop=(screen.get_width() // 2, int(screen.get_height() * 0.105))).inflate(34, 18)
        layer = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, (8, 34, 60, 220), layer.get_rect(), border_radius=14)
        pygame.draw.rect(layer, (82, 190, 145, 230), layer.get_rect(), 2, border_radius=14)
        screen.blit(layer, panel)
        screen.blit(art, art.get_rect(center=panel.center))

    @property
    def negative_progress(self) -> float:
        return 0.0

    @property
    def score(self) -> int:
        return self._score

    def update(self, dt: float) -> None:
        pass

    def draw(self, screen: pygame.Surface) -> None:
        pass

    def close(self) -> None:
        """Release the camera, but only if this minigame created the tracker."""
        if self._owns_tracker and self.tracker is not None:
            self.tracker.stop()

    def finish(self, won: bool, *, score_override: int | None = None) -> None:
        if self.finished:
            return
        penalty = max(0.0, min(1.0, self.negative_progress))
        self._score = (
            min(self.BASE_SCORE, max(0, score_override))
            if score_override is not None
            else round(self.MIN_SCORE + (self.BASE_SCORE - self.MIN_SCORE) * (1 - penalty**3))
        )
        if not won:
            self.record_strike()
        self.finished = True
        self.won = won

    def record_strike(self) -> bool:
        if self.strike_earned:
            return False
        self.strike_earned = True
        self.day_strikes = min(self.strike_limit, self.day_strikes + 1)
        return True
