import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.employee import EmployeeRecord, normalize_signature
from game.game import Game
from game.games import ContractSigningDay
from game.games.one_last_print import OneLastPrint
from game.minigame import Action
from game.scenes import AFTER_SCENES, BEFORE_SCENES
from game.tracking.camera import CameraTracker
from game.ui.screens.badge_photo import BadgePhotoScreen
from game.ui.screens.final_score import FinalScoreScreen
from game.ui.screens.intro import MinigameIntro
from game.ui.screens.scene import SceneScreen
from game.workday import WorkdayChapterScreen, WorkdayClock


class FakeCamera:
    def __init__(self):
        self.frame = pygame.Surface((640, 480))
        self.frame.fill((40, 100, 180))
        self.gesture = None

    def snapshot_surface(self):
        return self.frame.copy() if self.frame is not None else None


class EmployeeDayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1280, 720))

    def test_keepsakes_survive_on_disk_and_new_player_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = EmployeeRecord(root)
            strokes = [[(100, 100, True), (200, 130, False)], [(220, 110, True)]]
            record.set_signature(strokes)
            record.set_photo(FakeCamera().frame)
            document = json.loads((record.directory / "employee.json").read_text())
            expected = json.loads(json.dumps(normalize_signature(strokes)))
            self.assertEqual(document["signature"], expected)
            self.assertEqual(len(document["signature"]), 2)
            self.assertEqual(pygame.image.load(record.directory / "photo.png").get_size(), (640, 480))
            self.assertGreater(pygame.image.load(record.directory / "signature.png").get_bounding_rect().width, 0)
            following = EmployeeRecord(root)
            self.assertNotEqual(record.directory, following.directory)
            self.assertEqual(following.signature, [])
            self.assertIsNone(following.photo)

    def test_signature_normalization_preserves_aspect_and_pen_gaps(self):
        signature = normalize_signature([
            [(0, 0, True), (400, 40, True)],
            [(450, 20, True), (600, 60, True)],
        ])
        self.assertEqual(len(signature), 2)
        points = [point for stroke in signature for point in stroke]
        self.assertAlmostEqual(max(point[0] for point in points), 1.0)
        self.assertAlmostEqual(max(point[1] for point in points), 0.1)

    def test_failed_storage_keeps_memory_usable(self):
        with tempfile.TemporaryDirectory() as temporary:
            blocked = Path(temporary) / "not-a-directory"
            blocked.write_text("occupied")
            record = EmployeeRecord(blocked)
            record.set_photo(FakeCamera().frame)
            record.set_signature([[(1, 2, True), (3, 4, True)]])
            self.assertIsNotNone(record.save_error)
            self.assertIsNotNone(record.photo)
            self.assertTrue(record.signature)

    def test_photo_requires_confirmation_and_supports_retake(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = EmployeeRecord(Path(temporary))
            continued = []
            camera = FakeCamera()
            screen = BadgePhotoScreen(camera, record, lambda: continued.append(True))
            screen.gesture_continue()
            screen.update(3.1)
            self.assertEqual(screen.mode, "review")
            self.assertIsNone(record.photo)
            camera.gesture = "palm"
            screen.update(screen.REVIEW_GESTURE_DELAY)
            screen.update(screen.RETAKE_HOLD_SECONDS)
            self.assertEqual(screen.mode, "ready")
            camera.gesture = None
            screen.gesture_continue()
            screen.update(3.1)
            screen.gesture_continue()
            self.assertEqual(continued, [True])
            self.assertIsNotNone(record.photo)

    def test_photo_does_not_capture_when_camera_frame_is_lost(self):
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera()
            record = EmployeeRecord(Path(temporary))
            screen = BadgePhotoScreen(camera, record, lambda: None)
            screen.gesture_continue()
            camera.frame = None
            screen.update(4)
            self.assertEqual(screen.mode, "ready")
            self.assertIsNone(record.photo)

    def test_open_hand_skips_when_camera_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera()
            camera.frame = None
            camera.gesture = "palm"
            continued = []
            record = EmployeeRecord(Path(temporary))
            screen = BadgePhotoScreen(camera, record, lambda: continued.append(True))
            screen.update(screen.RETAKE_HOLD_SECONDS)
            self.assertEqual(continued, [True])
            self.assertIsNone(record.photo)

    def test_photo_open_hand_retakes_and_pinch_confirms(self):
        with tempfile.TemporaryDirectory() as temporary:
            camera = FakeCamera()
            record = EmployeeRecord(Path(temporary))
            continued = []
            screen = BadgePhotoScreen(camera, record, lambda: continued.append(True))
            screen.gesture_continue()
            screen.update(3.1)
            self.assertEqual(screen.mode, "review")
            camera.gesture = "palm"
            screen.update(screen.REVIEW_GESTURE_DELAY)
            screen.update(screen.RETAKE_HOLD_SECONDS)
            self.assertEqual(screen.mode, "ready")
            camera.gesture = None
            screen.gesture_continue()
            screen.update(3.1)
            screen.gesture_continue()
            self.assertEqual(continued, [True])
            self.assertIsNotNone(record.photo)

    def test_snapshot_rejects_old_and_stopped_camera(self):
        camera = object.__new__(type(
            "CameraStub",
            (CameraTracker,),
            {"_setup": lambda self: True, "_process": lambda self, frame: []},
        ))
        camera._lock = threading.Lock()
        camera._running = True
        camera._snapshot = (bytes([100, 50, 20]) * 4, (2, 2), time.monotonic())
        self.assertEqual(camera.snapshot_surface().get_at((0, 0))[:3], (100, 50, 20))
        camera._snapshot = (camera._snapshot[0], (2, 2), time.monotonic() - 10)
        self.assertIsNone(camera.snapshot_surface())
        camera._running = False
        self.assertIsNone(camera.snapshot_surface())

    def test_optional_paperwork_never_rewinds_day(self):
        clock = WorkdayClock()
        titles = (
            "Contract Signing Day",
            "Act Natural",
            "Who's Talking?",
            "Any Volunteers?",
            "A Quick Favour",
            "Merge Request Review",
            "Coffee Run",
            "One Last Print",
        )
        for title in titles:
            before = clock.minutes
            clock.enter(title)
            self.assertGreaterEqual(clock.minutes, before)
        clock.complete()
        self.assertEqual(clock.minutes, 1020)
        self.assertEqual(clock.progress, 1)

    def test_instructions_hide_gameplay_and_clock_until_they_finish(self):
        from game.settings import Settings

        game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
        minigame = SimpleNamespace(
            title="Test round",
            actions=(Action("Action one", "First action"), Action("Action two", "Second action")),
            small_font=pygame.font.Font(None, 24),
            tracker=None,
            draw=Mock(),
        )
        game.minigame = minigame
        game.workday.draw = Mock()
        game.ui.show(MinigameIntro(minigame, lambda: None))

        game.draw()

        self.assertFalse(game.ui.current.overlay)
        self.assertTrue(game.ui.current.suppress_corner_score)
        minigame.draw.assert_not_called()
        game.workday.draw.assert_not_called()

        game.ui.clear()
        game.draw()

        minigame.draw.assert_called_once_with(game.screen)
        game.workday.draw.assert_called_once_with(game.screen)

    def test_next_round_shows_clock_before_scenes_and_onboarding(self):
        from game.settings import Settings

        with patch.object(CameraTracker, "start", lambda self: None), \
                patch.object(CameraTracker, "stop", lambda self: None):
            game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
            game.remaining = [ContractSigningDay]

            game.next_minigame()

            self.assertIsInstance(game.ui.current, WorkdayChapterScreen)
            self.assertEqual(game.workday.stamp, "09:00")

            game.ui.current.gesture_continue()
            game.ui.update(0.5)
            self.assertIsInstance(game.ui.current, SceneScreen)

            game.ui.current.gesture_continue()
            game.ui.current.draw(game.screen)
            game.ui.current.gesture_continue()
            game.ui.update(0.5)
            self.assertIsInstance(game.ui.current, BadgePhotoScreen)

            game.ui.current.on_continue()
            game.ui.update(0.31)
            self.assertIsInstance(game.ui.current, MinigameIntro)

    def test_opening_scenes_never_reveal_gameplay_when_dismissed(self):
        from game.settings import Settings

        game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
        for scenes in BEFORE_SCENES.values():
            minigame_draw = Mock()
            game.minigame = SimpleNamespace(
                small_font=pygame.font.Font(None, 24),
                tracker=None,
                draw=minigame_draw,
            )
            continued = Mock()
            game._show_scene_sequence(scenes, continued)

            scene = game.ui.current
            self.assertIsInstance(scene, SceneScreen)
            scene.gesture_continue()
            scene.draw(game.screen)
            scene.gesture_continue()

            self.assertTrue(game.ui.leaving)
            self.assertIsNone(game.ui._backdrop)
            game.draw()
            minigame_draw.assert_not_called()

            game.ui.update(scene.fade_out)
            continued.assert_called_once_with()
            game.ui.clear()

    def test_after_scenes_do_not_reveal_finished_minigame(self):
        from game.settings import Settings

        game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
        for game_type, scenes in AFTER_SCENES.items():
            minigame_draw = Mock()
            game.minigame = SimpleNamespace(
                small_font=pygame.font.Font(None, 24),
                tracker=None,
                draw=minigame_draw,
            )
            game.remaining = []
            show_final_score = Mock()
            game.show_final_score = show_final_score

            game._after_result(game_type, won=True)

            scene = game.ui.current
            self.assertIsInstance(scene, SceneScreen)
            scene.gesture_continue()
            scene.draw(game.screen)
            scene.gesture_continue()

            self.assertTrue(game.ui.leaving)
            self.assertIsNone(game.ui._backdrop)
            game.draw()
            minigame_draw.assert_not_called()

            game.ui.update(scene.fade_out)
            show_final_score.assert_called_once_with()
            game.ui.clear()

    def test_final_printer_pass_screen_marks_end_of_day(self):
        from game.settings import Settings

        game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
        minigame = object.__new__(OneLastPrint)
        minigame.close = Mock()
        minigame.finished = True
        minigame.day_strikes = 0
        minigame._score = 900
        minigame.won = True
        minigame.title = "One Last Print"
        minigame.strike_limit = 3
        minigame.draw = Mock()
        minigame.tracker = None
        game.minigame = minigame
        game.navigation_tracker.start = Mock()

        game.update(0.01)

        self.assertEqual(game.ui.current.TITLE, "You Passed!")
        self.assertEqual(game.ui.current.DESCRIPTION, "Great job today!")

    def test_final_review_renders_missing_and_present_keepsakes(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = EmployeeRecord(Path(temporary))
            for populated in (False, True):
                if populated:
                    record.set_photo(FakeCamera().frame)
                    record.set_signature([[(10, 20, True), (200, 50, True)]])
                review = FinalScoreScreen(
                    lambda: None,
                    [("One Last Print", 900, True)],
                    900,
                    0,
                    employee_record=record,
                )
                for size in ((1280, 720), (1920, 1080)):
                    review.draw(pygame.Surface(size))

    def test_game_flow_shares_one_fresh_record(self):
        from game.game import Game
        from game.settings import Settings

        with tempfile.TemporaryDirectory() as temporary, \
                patch("game.employee.data_root", lambda: Path(temporary)), \
                patch.object(CameraTracker, "start", lambda self: None), \
                patch.object(CameraTracker, "stop", lambda self: None):
            game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
            game.start_game()
            first_record = game.employee_record
            signing = game.minigame
            signing.state = "name"
            signing.covered = [True] * len(signing.samples)
            signing.strokes = [
                [(200, 300, True), (240, 380, True), (280, 300, True)],
                [(320, 380, True), (320, 300, True), (360, 340, True), (400, 300, True), (400, 380, True)],
            ]
            signing.update(0.01)
            self.assertTrue(first_record.signature)
            saved_signature = [stroke.copy() for stroke in first_record.signature]
            for _ in range(12):
                signing.update(0.1)
            self.assertEqual(signing.state, "sliding")
            self.assertEqual(first_record.signature, saved_signature)
            game.show_onboarding()
            self.assertIsInstance(game.ui.current, BadgePhotoScreen)
            game.show_final_score()
            self.assertIs(game.ui.current.employee_record, first_record)
            game.start_game()
            self.assertIsNot(game.employee_record, first_record)
            self.assertFalse(game.employee_record.signature)
            self.assertIsNone(game.employee_record.photo)


if __name__ == "__main__":
    unittest.main()
