import random

import pygame

from game.games import Dalgona, RedLightGreenLight, SpotlightDodge, simonsays
from game.intro import MinigameIntro
from game.menu import Menu, MenuItem
from game.minigame import Minigame
from game.settings import Settings


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
        self.minigames: list[type[Minigame]] = [Dalgona, RedLightGreenLight, simonsays, SpotlightDodge]
        self.remaining: list[type[Minigame]] = []
        self.minigame: Minigame | None = None
        self.intro: MinigameIntro | None = None
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
            return
        cls = self.remaining.pop(random.randrange(len(self.remaining)))
        self.minigame = cls(self.screen)
        self.intro = MinigameIntro(self.minigame, self.begin_minigame)

    def begin_minigame(self) -> None:
        self.intro = None
        if self.minigame:
            self.minigame.start()

    def tutorial(self) -> None:
        pass

    def quit(self) -> None:
        self.running = False

    def run(self) -> None:
        self.running = True
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
            elif self.intro:
                self.intro.handle_event(event)
            elif self.minigame:
                self.minigame.handle_event(event)
            else:
                self.menu.handle_event(event)

    def update(self, dt: float) -> None:
        if self.minigame and not self.intro:
            self.minigame.update(dt)
            if self.minigame.finished:
                self.minigame.close()
                self.next_minigame()

    def draw(self) -> None:
        self.screen.fill(self.settings.background)
        if self.intro:
            self.intro.draw(self.screen)
        elif self.minigame:
            self.minigame.draw(self.screen)
        else:
            self.menu.draw(self.screen)
        pygame.display.flip()
