import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.employee import EmployeeRecord, normalize_signature
from game.tracking.camera import CameraTracker
from game.ui.screens.badge_photo import BadgePhotoScreen
from game.ui.screens.final_score import FinalScoreScreen
from game.workday import WorkdayClock


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
