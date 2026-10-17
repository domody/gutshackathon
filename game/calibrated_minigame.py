from __future__ import annotations

import pygame

from game.minigame import Minigame
from game.ui import draw_bar, draw_text_centered

DONE_COLOR = (110, 210, 130)


class CalibratedMinigame(Minigame):
    """Minigame that samples the player for a moment before it starts to set a neutral."""

    calibrate_seconds = 1.2     # time spent sampling
    calibrate_timeout = 5.0     # give up waiting for the player after this long
    after_calibration = "play"  # mode entered once calibration ends
    distance_tolerance = 0.4    # allowed drift from the calibrated shoulder width

    def start(self) -> None:
        super().start()
        self.neutral = None
        self.begin_calibration()

    def begin_calibration(self) -> None:
        self.samples: list = []
        self.calib_time = 0.0
        self.wait_time = 0.0
        self.mode = "calibrate" if self.tracker.available else self.after_calibration

    def read_sample(self):
        """One measurement of the player, or None if they aren't visible."""
        return None

    def on_calibrated(self, samples: list) -> None:
        """Turn the collected samples into the neutral (and anything else)."""

    def calibration_prompt(self) -> str:
        return "Stand still..."

    def distance_ok(self, width: float) -> bool:
        """Whether a shoulder width is close enough to the calibrated one (neutral)."""
        if self.neutral is None:
            return True
        ratio = width / max(self.neutral, 1e-4)
        return 1.0 - self.distance_tolerance <= ratio <= 1.0 + self.distance_tolerance

    def update_calibration(self, dt: float) -> None:
        self.wait_time += dt
        sample = self.read_sample()
        if sample is not None:
            self.samples.append(sample)
            self.calib_time += dt

        enough = self.calib_time >= self.calibrate_seconds and len(self.samples) >= 10
        if enough or self.wait_time > self.calibrate_timeout or not self.tracker.available:
            if self.samples:
                self.on_calibrated(self.samples)
            self.mode = self.after_calibration

    def draw_calibration(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        draw_text_centered(screen, self.font, self.calibration_prompt(), (240, 240, 240),
                           (w // 2, h // 2 - 60))
        draw_bar(screen, (w // 2 - 120, h // 2 - 20, 240, 12),
                 self.calib_time / self.calibrate_seconds, DONE_COLOR)
