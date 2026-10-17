import random

import pygame

from game.games import CatchOrDrop, Dalgona, RedLightGreenLight, SpotlightDodge, TugOfWar, simonsays
from game.minigame import Minigame
from game.settings import Settings
from game.ui import ScreenManager
from game.ui.screens import FailScreen, Menu, MenuItem, MinigameIntro, PassScreen


class Game:
    """Owns the window, the main loop, and top-level lifecycle."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        pygame.init()
        if self.settings.fullscreen:
            # (0, 0) uses the desktop resolution
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.settings.window_size)
        pygame.display.set_caption(self.settings.title)
        self.clock = pygame.time.Clock()
        self.running = False
        self.minigames: list[type[Minigame]] = [
            Dalgona, RedLightGreenLight, simonsays, SpotlightDodge, CatchOrDrop, TugOfWar,
        ]
        self.remaining: list[type[Minigame]] = []
        self.minigame: Minigame | None = None
        self.ui = ScreenManager()
        self.menu = Menu(
            self.settings.title,
            [
                MenuItem("Play", self.start_game),
                MenuItem("Tutorial", self.tutorial),
                MenuItem("Quit", self.quit),
            ],
        )

    def start_game(self) -> None:
        self.remaining = self.minigames.copy()
        self.next_minigame()

    def next_minigame(self) -> None:
        """Start a random remaining minigame, or return to the menu when none are left."""
        if not self.remaining:
            self.minigame = None
            self.ui.show(self.menu)
            return
        cls = self.remaining.pop(random.randrange(len(self.remaining)))
        self.minigame = cls(self.screen)
        self.ui.show(MinigameIntro(self.minigame, self.begin_minigame))

    def begin_minigame(self) -> None:
        self.ui.clear()
        if self.minigame:
            self.minigame.start()

    def tutorial(self) -> None:
        pass

    def quit(self) -> None:
        self.running = False

    def run(self) -> None:
        self.running = True
        self.ui.show(self.menu)
        while self.running:
            dt = self.clock.tick(self.settings.fps) / 1000
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()
            elif self.ui.active:
                self.ui.handle_event(event)
            elif self.minigame:
                self.minigame.handle_event(event)

    def update(self, dt: float) -> None:
        if self.ui.active:
            self.ui.update(dt)
        elif self.minigame:
            self.minigame.update(dt)
            if self.minigame.finished:
                self.minigame.close()
                result = PassScreen if self.minigame.won else FailScreen
                self.ui.show(result(self.next_minigame))

    def draw(self) -> None:
        self.screen.fill(self.settings.background)
        if self.ui.active:
            self.ui.draw(self.screen)
        elif self.minigame:
            self.minigame.draw(self.screen)
        pygame.display.flip()
