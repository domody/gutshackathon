import random

import pygame

from game.games import CatchOrDrop, CoffeeRun, Dalgona, RedLightGreenLight, DodgeTheManager, TugOfWar, simonsays
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
            Dalgona, RedLightGreenLight, simonsays, DodgeTheManager, CatchOrDrop, TugOfWar, CoffeeRun,
        ]
        self.remaining: list[type[Minigame]] = []
        self.minigame: Minigame | None = None
        self.ui = ScreenManager()
        self.menu = Menu(
            self.settings.title,
            [
                MenuItem("Play", self.start_game),
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
        """Start the minigame and fade the intro out over it."""
        if not self.minigame:
            return
        self.minigame.start()
        self.ui.dismiss(self.ui.clear, fade_background=True, backdrop=self.minigame.draw)

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
            if self.ui.leaving and self.minigame:
                self.minigame.update(dt)  # runs under the fade-out
        elif self.minigame:
            self.minigame.update(dt)
            if self.minigame.finished:
                self.minigame.close()
                result = PassScreen if self.minigame.won else FailScreen
                screen = result(lambda: self.ui.dismiss(self.next_minigame))
                self.ui.show(screen, backdrop=self.minigame.draw)

    def draw(self) -> None:
        self.screen.fill(self.settings.background)
        if self.ui.active:
            self.ui.draw(self.screen)
        elif self.minigame:
            self.minigame.draw(self.screen)
        pygame.display.flip()
