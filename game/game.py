import pygame

from game.games import TugOfWar
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
        self.minigame: Minigame | None = None
        self.menu = Menu(
            self.settings.title,
            [
                MenuItem("Play", self.start_game),
                MenuItem("Tutorial", self.tutorial),
                MenuItem("Quit", self.quit),
            ],
        )

    def start_game(self) -> None:
        self.minigame = TugOfWar(self.screen)
        self.minigame.start()

    def tutorial(self) -> None:
        pass

    def quit(self) -> None:
        if self.minigame:
            self.minigame.close()
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
            elif self.minigame:
                self.minigame.handle_event(event)
            else:
                self.menu.handle_event(event)

    def update(self, dt: float) -> None:
        if self.minigame:
            self.minigame.update(dt)
            if self.minigame.finished:
                self.minigame.close()
                self.minigame = None

    def draw(self) -> None:
        self.screen.fill(self.settings.background)
        if self.minigame:
            self.minigame.draw(self.screen)
        else:
            self.menu.draw(self.screen)
        pygame.display.flip()
