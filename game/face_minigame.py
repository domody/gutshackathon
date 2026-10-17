from __future__ import annotations

from statistics import median

import pygame

from game.calibrated_minigame import CalibratedMinigame
from game.tracking import FaceTracker
from game.ui import draw_text_centered


class FaceMinigame(CalibratedMinigame):
    """Minigame driven by head pose: neutral is (yaw ratio, roll degrees)."""

    tracker_cls = FaceTracker

    def start(self) -> None:
        self.face_visible = False
        super().start()

    def read_sample(self) -> tuple[float, float] | None:
        return self.tracker.pose if self.tracker.available else None

    def on_calibrated(self, samples: list[tuple[float, float]]) -> None:
        self.neutral = (median(s[0] for s in samples), median(s[1] for s in samples))

    def calibration_prompt(self) -> str:
        return "Look straight at the camera..."

    def recentre(self) -> None:
        """Treat the current pose as straight ahead."""
        sample = self.read_sample()
        if sample is not None:
            self.neutral = sample

    def read_offsets(self) -> tuple[float, float] | None:
        """(yaw offset in full turns, roll offset in degrees) from neutral, or None if no face."""
        sample = self.read_sample()
        self.face_visible = sample is not None
        if sample is None:
            return None
        if self.neutral is None:   # camera found us late: calibrate on first sight
            self.neutral = sample
        return ((sample[0] - self.neutral[0]) / self.tracker.scale,
                sample[1] - self.neutral[1])

    def draw_face_lost(self, screen: pygame.Surface, y: int) -> None:
        if self.mode != "calibrate" and self.tracker.available and not self.face_visible:
            draw_text_centered(screen, self.font, "Face lost!", (255, 160, 60),
                               (screen.get_width() // 2, y))
