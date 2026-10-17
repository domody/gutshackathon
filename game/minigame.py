from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import pygame

if TYPE_CHECKING:
    from game.tracking import CameraTracker


@dataclass(frozen=True)
class Action:
    """One of a minigame's two actions, as shown in its tutorial."""

    name: str
    description: str
    perform: Callable[[], None]


class Minigame(ABC):
    """Base class for minigames. Subclasses implement the logic and expose two actions."""

    title: str = "Minigame"
    tracker_cls: type[CameraTracker] | None = None  # set to use the camera

    def __init__(self, screen: pygame.Surface, tracker: CameraTracker | None = None) -> None:
        self.screen = screen
        self.finished = False
        self.won = False

        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.big_font = pygame.font.Font(None, 72)

        # Pass a shared tracker in if several minigames use the camera.
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

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self, screen: pygame.Surface) -> None:
        pass

    def close(self) -> None:
        """Release the camera, but only if this minigame created the tracker."""
        if self._owns_tracker and self.tracker is not None:
            self.tracker.stop()

    def finish(self, won: bool) -> None:
        self.finished = True
        self.won = won
