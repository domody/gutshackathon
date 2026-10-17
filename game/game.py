import pygame

from game.games import CatchOrDrop, CoffeeRun, Dalgona, RedLightGreenLight, DodgeTheManager, TugOfWar, simonsays
from game.minigame import Minigame
from game.scenes import SCENES
from game.settings import Settings
from game.tracking import HandTracker
from game.ui import ScreenManager
from game.ui.screens import FailScreen, FiredScreen, Menu, MenuItem, MinigameIntro, PassScreen, SceneScreen


class Game:
    """Owns the window, the main loop, and top-level lifecycle."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        pygame.init()
        if self.settings.fullscreen:
            # A size of (0, 0) selects the desktop resolution.
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.settings.window_size)
        pygame.display.set_caption(self.settings.title)
        self.clock = pygame.time.Clock()
        self.running = False
        self.minigames: list[type[Minigame]] = [
            Dalgona, RedLightGreenLight, simonsays, DodgeTheManager, CatchOrDrop, CoffeeRun, TugOfWar,
        ]
        self.remaining: list[type[Minigame]] = []
        self.minigame: Minigame | None = None
        self.strikes = 0
        self.navigation_tracker = HandTracker()
        self.pinch_was_down = False
        self.ui = ScreenManager()
        self.menu = Menu(
            self.settings.title,
            [
                MenuItem("Play", self.start_game),
            ],
        )

    def start_game(self) -> None:
        self.strikes = 0
        self.total_score = 0
        self.remaining = self.minigames.copy()
        self.next_minigame()

    def next_minigame(self) -> None:
        """Start the next minigame in order, or return to the menu when none are left."""
        self.navigation_tracker.stop()
        if self.minigame:
            self.minigame.close()
        if not self.remaining:
            self.minigame = None
            self.navigation_tracker.start()
            self.pinch_was_down = False
            self.ui.show(self.menu)
            return
        cls = self.remaining.pop(0)
        self.minigame = cls(self.screen)
        self.minigame.day_strikes = self.strikes
        self.minigame.close()
        self.navigation_tracker.start()
        self.pinch_was_down = False
        scene = SCENES.get(cls)
        if scene is None:
            self.show_intro()
            return
        minigame = self.minigame
        self.ui.show(SceneScreen(
            scene.image, scene.text, scene.speaker,
            lambda: self.ui.dismiss(self.show_intro, fade_background=True, backdrop=minigame.draw),
        ))

    def show_intro(self) -> None:
        """Overlay the intro on the minigame's first frame."""
        if self.minigame:
            self.ui.show(MinigameIntro(self.minigame, self.begin_minigame))

    def begin_minigame(self) -> None:
        """Start the minigame and fade the intro out over it."""
        if not self.minigame:
            return
        self.navigation_tracker.stop()
        if self.minigame.tracker is not None:
            self.minigame.tracker.start()
        self.minigame.start()
        self.ui.dismiss(self.ui.clear, fade_background=True, backdrop=self.minigame.draw)

    def quit(self) -> None:
        self.navigation_tracker.stop()
        if self.minigame:
            self.minigame.close()
        self.running = False

    def run(self) -> None:
        self.running = True
        self.navigation_tracker.start()
        self.pinch_was_down = False
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
            elif (self.minigame and event.type == pygame.KEYDOWN
                  and event.key == pygame.K_k):
                self.minigame.finish(True, score_override=self.minigame.BASE_SCORE)

    def update(self, dt: float) -> None:
        if self.ui.active:
            self.ui.update(dt)
            self._update_pinch_navigation()
            if self.ui.leaving and self.minigame:
                self.minigame.update(dt)  # Keep the game updating under the closing fade.
        elif self.minigame:
            self.minigame.update(dt)
            if self.minigame.finished:
                self.minigame.close()
                self.navigation_tracker.start()
                self.pinch_was_down = False
                self.strikes = self.minigame.day_strikes
                self.total_score += self.minigame.score
                if self.strikes >= 3:
                    self.remaining.clear()
                    screen = FiredScreen(
                        lambda: self.ui.dismiss(self.next_minigame),
                        total_score=self.total_score,
                        round_score=self.minigame.score,
                    )
                else:
                    result = PassScreen if self.minigame.won else FailScreen
                    screen = result(
                        lambda: self.ui.dismiss(self.next_minigame),
                        total_score=self.total_score,
                        round_score=self.minigame.score,
                    )
                    if not self.minigame.won:
                        screen.DESCRIPTION = f"Strike {self.strikes} of 3."
                self.ui.show(screen, backdrop=self.minigame.draw)

    def _update_pinch_navigation(self) -> None:
        if self.ui.leaving or not self.navigation_tracker.available:
            return
        hand = self.navigation_tracker.hand
        pinching = bool(hand and hand[2])
        if pinching and not self.pinch_was_down and self.ui.current:
            self.ui.current.gesture_continue()
        self.pinch_was_down = pinching

    def draw(self) -> None:
        self.screen.fill(self.settings.background)
        if self.minigame and self.ui.current and self.ui.current.overlay:
            self.minigame.draw(self.screen)
        if self.ui.active:
            self.ui.draw(self.screen)
        elif self.minigame:
            self.minigame.draw(self.screen)
        if self.minigame:
            tracker = self.minigame.tracker
            result_screen = self.ui.current
            displayed_score = getattr(result_screen, "display_score", self.total_score)
            draw_score(
                self.screen,
                self.minigame.small_font,
                displayed_score,
                camera_available=tracker is not None and tracker.available,
            )
        pygame.display.flip()
