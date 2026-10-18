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
        self.frame = pygame.Surface((480, 360))
        self.frame.fill((40, 100, 180))

    def snapshot_surface(self):
        return self.frame.copy() if self.frame is not None else None


class EmployeeDayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1280, 720))

    def test_ink_and_photo_survive_on_disk_and_new_player_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = EmployeeRecord(root)
            ink = [[(100, 100, True), (200, 130, False)], [(220, 110, True)]]
            record.set_signature(ink)
            record.set_photo(FakeCamera().frame)
            document = json.loads((record.directory / "employee.json").read_text())
            self.assertEqual(document["signature"], json.loads(json.dumps(normalize_signature(ink))))
            self.assertEqual(len(document["signature"]), 2)  # Do not join pen-up strokes.
            self.assertEqual(pygame.image.load(record.directory / "photo.png").get_size(), (480, 360))
            self.assertGreater(pygame.image.load(record.directory / "signature.png").get_bounding_rect().width, 0)
            following = EmployeeRecord(root)
            self.assertNotEqual(record.directory, following.directory)
            self.assertEqual(following.signature, [])
            self.assertIsNone(following.photo)

    def test_read_only_storage_keeps_memory_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "not-a-directory"
            blocked.write_text("occupied")
            record = EmployeeRecord(blocked)
            record.set_photo(FakeCamera().frame)
            record.set_signature([[(1, 2, True), (3, 4, True)]])
            self.assertIsNotNone(record.save_error)
            self.assertIsNotNone(record.photo)
            self.assertTrue(record.signature)

    def test_photo_requires_confirmation_and_supports_retake(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = EmployeeRecord(Path(tmp))
            continued = []
            camera = FakeCamera()
            screen = BadgePhotoScreen(camera, record, lambda: continued.append(True))
            screen.gesture_continue()
            screen.update(3.1)
            self.assertEqual(screen.mode, "review")
            self.assertIsNone(record.photo)
            target = pygame.Surface((1280, 720))
            screen.draw(target)
            screen.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                                   pos=screen.buttons["Retake"].center))
            self.assertEqual(screen.mode, "ready")
            screen.gesture_continue()
            screen.update(3.1)
            screen.gesture_continue()
            self.assertEqual(continued, [True])
            self.assertIsNotNone(record.photo)

    def test_photo_does_not_capture_when_camera_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            camera = FakeCamera()
            record = EmployeeRecord(Path(tmp))
            screen = BadgePhotoScreen(camera, record, lambda: None)
            screen.gesture_continue()
            camera.frame = None
            screen.update(4)
            self.assertEqual(screen.mode, "ready")
            self.assertIsNone(record.photo)

    def test_snapshot_rejects_old_and_stopped_camera(self):
        # Exercise the actual snapshot reader without opening a webcam.
        camera = object.__new__(type("CameraStub", (CameraTracker,), {"_setup": lambda self: True,
                                                                  "_process": lambda self, f: []}))
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
        for title in ("Contract Signing Day", "Act Natural", "Who's Talking?", "Any Volunteers?",
                      "A Quick Favour", "Merge Request Review", "Coffee Run", "One Last Print"):
            before = clock.minutes
            clock.enter(title)
            self.assertGreaterEqual(clock.minutes, before)
        clock.complete()
        self.assertEqual(clock.minutes, 17 * 60)
        self.assertEqual(clock.progress, 1)

    def test_final_review_renders_missing_and_present_keepsakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = EmployeeRecord(Path(tmp))
            for populated in (False, True):
                if populated:
                    record.set_photo(FakeCamera().frame)
                    record.set_signature([[(10, 20, True), (200, 50, True)]])
                screen = FinalScoreScreen(lambda: None, [("One Last Print", 900, True)], 900, 0,
                                          employee_record=record)
                for size in ((1280, 720), (1920, 1080)):
                    screen.draw(pygame.Surface(size))

    def test_actual_signing_and_game_flow_share_the_same_record(self):
        from game.game import Game
        from game.settings import Settings
        with tempfile.TemporaryDirectory() as tmp, patch("game.employee.data_root", lambda: Path(tmp)), \
                patch.object(CameraTracker, "start", lambda self: None), \
                patch.object(CameraTracker, "stop", lambda self: None):
            game = Game(Settings(fullscreen=False, window_size=(1280, 720)))
            game.start_game()
            signing = game.minigame
            signing.state = "signing"
            signing.signature_index = 0
            signing.covered = [True] * len(signing.samples)
            signing.strokes = [[(200, 300, True), (240, 320, True), (290, 280, True)]]
            signing.update(0.01)
            self.assertTrue(game.employee_record.signature)
            game.show_onboarding()
            self.assertIsInstance(game.ui.current, BadgePhotoScreen)
            game.show_final_score()
            self.assertIs(game.ui.current.employee_record, game.employee_record)
            self.assertEqual(game.workday.minutes, 1020)
            # Verify all actual asset-backed rounds still construct and render.
            for cls in game.minigames:
                level = cls(game.screen)
                level.draw(game.screen)


if __name__ == "__main__":
    unittest.main()
