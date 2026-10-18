from collections.abc import Callable

import pygame

from game.employee import EmployeeRecord
from game.games import MergeRequestReview, CoffeeRun, ContractSigningDay, RunToMeeting, DodgeTheManager, PaperSort, OneLastPrint, WhosTalking
from game.minigame import Minigame
from game.scenes import AFTER_SCENES, BEFORE_SCENES, Scene
from game.settings import Settings
from game.tracking import HandTracker
from game.ui import ScreenManager, draw_score
from game.ui.screens import BadgePhotoScreen, FailScreen, FinalScoreScreen, FiredScreen, Menu, MenuItem, MinigameIntro, PassScreen, SceneScreen
from game.workday import WorkdayChapterScreen, WorkdayClock


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
            ContractSigningDay, RunToMeeting, WhosTalking, DodgeTheManager, MergeRequestReview, CoffeeRun, OneLastPrint,
        ]
        self.remaining: list[type[Minigame]] = []
        self.minigame: Minigame | None = None
        self.strikes = 0
        self.total_score = 0
        self.day_results: list[tuple[str, int, bool]] = []
        self.employee_record: EmployeeRecord | None = None
        self.workday = WorkdayClock()
        self.photo_offered = False
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
        self.day_results = []
        self.employee_record = EmployeeRecord()
        self.workday = WorkdayClock()
        self.photo_offered = False
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
        self.workday.enter(self.minigame.title)
        if isinstance(self.minigame, ContractSigningDay):
            self.minigame.employee_record = self.employee_record
        self.minigame.day_strikes = self.strikes
        self.minigame.close()
        self.navigation_tracker.start()
        self.pinch_was_down = False
        self.show_workday_chapter(
            lambda: self._show_scene_sequence(BEFORE_SCENES.get(cls, ()), self.show_onboarding)
        )

    def show_onboarding(self) -> None:
        if isinstance(self.minigame, ContractSigningDay) and not self.photo_offered:
            self.photo_offered = True
            if self.employee_record is None:
                self.employee_record = EmployeeRecord()
                self.minigame.employee_record = self.employee_record
            self.ui.show(BadgePhotoScreen(
                self.navigation_tracker,
                self.employee_record,
                lambda: self.ui.dismiss(self.show_intro),
            ))
            return
        self.show_intro()

    def show_workday_chapter(self, after: Callable[[], None] | None = None) -> None:
        self.ui.show(WorkdayChapterScreen(
            self.workday,
            lambda: self.ui.dismiss(after or self.show_intro),
        ))

    def _show_scene_sequence(self, scenes: tuple[Scene, ...], after: Callable[[], None]) -> None:
        if not scenes:
            after()
            return
        scene = scenes[0]
        self.ui.show(SceneScreen(
            scene.image,
            scene.text,
            scene.speaker,
            lambda: self.ui.dismiss(
                lambda: self._show_scene_sequence(scenes[1:], after),
            ),
        ))

    def _after_result(self, game_type: type[Minigame], won: bool) -> None:
        scenes = AFTER_SCENES.get(game_type, ()) if won else ()
        after = self.next_minigame if self.remaining else self.show_final_score
        self._show_scene_sequence(scenes, after)

    def show_final_score(self) -> None:
        if self.strikes < 3:
            self.workday.complete()
        self.ui.show(FinalScoreScreen(
            lambda: self.ui.dismiss(self._return_to_menu),
            self.day_results,
            self.total_score,
            self.strikes,
            employee_record=self.employee_record,
        ))

    def _return_to_menu(self) -> None:
        self.minigame = None
        self.navigation_tracker.start()
        self.pinch_was_down = False
        self.ui.show(self.menu)

    def show_intro(self) -> None:
        """Show instructions before the minigame starts."""
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
                self.day_results.append((self.minigame.title, self.minigame.score, self.minigame.won))
                game_type = type(self.minigame)
                won = self.minigame.won
                if (game_type is DodgeTheManager and self.minigame.phase == "volunteered"
                        and self.strikes < self.minigame.strike_limit):
                    self.remaining.insert(0, PaperSort)
                    self.next_minigame()
                    return
                if self.strikes >= 3:
                    self.remaining.clear()
                    screen = FiredScreen(
                        lambda: self.ui.dismiss(self.show_final_score),
                        total_score=self.total_score,
                        round_score=self.minigame.score,
                    )
                else:
                    result = PassScreen if self.minigame.won else FailScreen
                    screen = result(
                        lambda: self.ui.dismiss(lambda: self._after_result(game_type, won)),
                        total_score=self.total_score,
                        round_score=self.minigame.score,
                    )
                    if not self.minigame.won:
                        screen.DESCRIPTION = f"Strike {self.strikes} of 3."
                    else:
                        screen.TITLE = self.minigame.success_title
                        screen.DESCRIPTION = self.minigame.success_description
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
            draw_combo = getattr(self.minigame, "draw_combo", None)
            if draw_combo:
                draw_combo(self.screen)
        if self.minigame and not getattr(self.ui.current, "suppress_corner_score", False):
            tracker = self.minigame.tracker
            result_screen = self.ui.current
            displayed_score = getattr(result_screen, "display_score", self.total_score)
            draw_score(
                self.screen,
                self.minigame.small_font,
                displayed_score,
                camera_available=tracker is not None and tracker.available,
            )
        if self.minigame and not isinstance(
            self.ui.current,
            (BadgePhotoScreen, FinalScoreScreen, MinigameIntro, WorkdayChapterScreen),
        ):
            self.workday.draw(self.screen)
        pygame.display.flip()
