from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

import pygame


@dataclass(frozen=True)
class Action:
    """One of a minigame's two actions, as shown in its tutorial."""

    name: str
    description: str
    perform: Callable[[], None]


class Minigame(ABC):
    """Base class for minigames. Subclasses implement the logic and expose two actions."""

    title: str = "Minigame"

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.finished = False
        self.won = False

    @property
    @abstractmethod
    def actions(self) -> tuple[Action, Action]:
        """Exactly two actions; the tutorial is built from these."""

    def start(self) -> None:
        """Reset state when the minigame begins."""

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self, screen: pygame.Surface) -> None:
        pass

    def close(self) -> None:
        """Release resources (e.g. the camera) when the minigame ends."""

    def finish(self, won: bool) -> None:
        self.finished = True
        self.won = won
