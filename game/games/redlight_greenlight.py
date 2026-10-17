from __future__ import annotations

import math
from statistics import median

import pygame

from game.calibrated_minigame import CalibratedMinigame
from game.minigame import Action
from game.tracking import BodyTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

GREEN_SECONDS = 2.8
RED_SECONDS = 2.6
STOP_GRACE = 0.65
COURSE_PER_SECOND = 4.5
PUMP_THRESHOLD = 0.9
DEFAULT_FREEZE_THRESHOLD = 0.38
CAUGHT_AFTER = 0.18
DISTANCE_TOLERANCE = 0.38
KEY_PULSE = 0.2             # keyboard fallback: how long a new arm "runs"
KEY_MOTION = 0.24           # keyboard fallback: how long a key press counts as movement

BG = (11, 16, 20)
GREEN = (91, 210, 102)
RED = (238, 74, 79)
WHITE = (242, 242, 235)
BAR_BACK = (52, 58, 63)


class RedLightGreenLight(CalibratedMinigame):
    """Advance by alternating arms on green and freeze on red."""

    title = "Red Light, Green Light"
    tracker_cls = BodyTracker

    def __init__(self, screen: pygame.Surface, tracker: BodyTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.start()

    # Public API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Pump Left", "Pump the left arm (A / Left)", self.pump_left),
            Action("Pump Right", "Pump the right arm (D / Right)", self.pump_right),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.course = 0.0
        self.phase = "green"
        self.phase_time = 0.0
        self.exposure = 0.0
        self.running_detected = False
        self.body_visible = False
        self.freeze_threshold = DEFAULT_FREEZE_THRESHOLD
        self.status = "GREEN - alternate your arms"

        self.last_key_arm = 0
        self.key_pulse = 0.0
        self.key_motion = 0.0

    # Handle input
    def pump_left(self) -> None:
        self._pump(-1)

    def pump_right(self) -> None:
        self._pump(1)

    def _pump(self, arm: int) -> None:
        self.key_motion = KEY_MOTION
        if arm != self.last_key_arm:
            self.key_pulse = KEY_PULSE
            self.last_key_arm = arm

    def handle_event(self, event: pygame.event.Event) -> None:
        super().handle_event(event)
        if event.type != pygame.KEYDOWN:
            return
        left, right = self.actions
        if event.key in (pygame.K_a, pygame.K_LEFT):
            left.perform()
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            right.perform()

    # Calibration
    def read_sample(self) -> tuple[float, float] | None:
        """(shoulder width, motion) while the player is in view."""
        body = self.tracker.body if self.tracker.available else None
        self.body_visible = body is not None
        return None if body is None else (body[2], body[1])

    def on_calibrated(self, samples: list[tuple[float, float]]) -> None:
        self.neutral = median(s[0] for s in samples)
        self.freeze_threshold = max(DEFAULT_FREEZE_THRESHOLD, median(s[1] for s in samples) * 3.2)
        self.phase, self.phase_time = "green", 0.0
        self.status = "GREEN - alternate your arms"

    def calibration_prompt(self) -> str:
        if self.body_visible:
            return "Hold still - calibrating distance and movement"
        return "Show your head, shoulders and upper body"

    def _distance_ok(self, width: float) -> bool:
        if self.neutral is None:
            return True
        ratio = width / max(self.neutral, 1e-4)
        return 1.0 - DISTANCE_TOLERANCE <= ratio <= 1.0 + DISTANCE_TOLERANCE

    # Update state
    def update(self, dt: float) -> None:
        if self.finished:
            return

        self.key_pulse = max(0.0, self.key_pulse - dt)
        self.key_motion = max(0.0, self.key_motion - dt)

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        camera = self.tracker.available
        body = self.tracker.body if camera else None
        if camera and body is None:
            self.running_detected = False
            self.status = "Paused - keep head, shoulders and torso visible"
            return
        pump, motion, width, hands_visible = body if camera else (0.0, 0.0, 0.0, False)

        if camera and not self._distance_ok(width):
            self.running_detected = False
            self.status = "Paused - return to your calibrated distance"
            return

        self.elapsed += dt
        self.phase_time += dt
        self._update_phase()

        camera_running = hands_visible and pump >= PUMP_THRESHOLD
        running = self.key_pulse > 0 or camera_running
        self.running_detected = self.phase == "green" and running

        if self.phase == "green":
            self.exposure = max(0.0, self.exposure - dt * 3)
            if running:
                intensity = max(1.0, min(1.75, pump / PUMP_THRESHOLD)) if camera_running else 1.0
                self.course = min(100.0, self.course + COURSE_PER_SECOND * intensity * dt)
                self.status = "Running detected - keep alternating"
            elif camera and not hands_visible:
                self.status = "GREEN - bring both hands into view"
            else:
                self.status = "GREEN - alternate your arms"
        else:
            self.running_detected = False
            moving = motion > self.freeze_threshold or self.key_motion > 0

            if self.phase_time < STOP_GRACE:
                self.exposure = max(0.0, self.exposure - dt * 2)
                self.status = "RED - stop!"
            elif moving:
                self.exposure = min(CAUGHT_AFTER, self.exposure + dt)
                self.status = "Movement detected..."
            else:
                self.exposure = max(0.0, self.exposure - dt * 2)
                if camera and not hands_visible:
                    self.status = "Frozen - hands lowered, body still visible"
                else:
                    self.status = "Frozen - good"

            if self.exposure >= CAUGHT_AFTER:
                self.finish(False)

        if self.course >= 100.0:
            self.finish(True)

    def _update_phase(self) -> None:
        duration = GREEN_SECONDS if self.phase == "green" else RED_SECONDS
        if self.phase_time < duration:
            return
        self.phase = "red" if self.phase == "green" else "green"
        self.phase_time = 0.0
        self.exposure = 0.0

    # Draw the scene
    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        color = GREEN if self.phase == "green" else RED
        screen.fill(BG)

        # Full-screen light cue, readable from several metres away.
        tint = pygame.Surface((w, h), pygame.SRCALPHA)
        tint.fill((*color, 52 if self.mode == "play" else 18))
        screen.blit(tint, (0, 0))

        horizon = int(h * 0.66)
        pygame.draw.rect(screen, (27, 33, 37), (0, horizon, w, h - horizon))
        self._draw_course(screen, w, h, horizon)
        self._draw_doll(screen, w, horizon, color)
        self._draw_player(screen, w, h, horizon)
        self._draw_hud(screen, w, h, color)

    def _draw_course(self, screen: pygame.Surface, w: int, h: int, horizon: int) -> None:
        """Perspective course: the player runs away from us toward the doll."""
        near_y = h + 25
        far_y = horizon + 15
        near_left, near_right = int(w * 0.13), int(w * 0.87)
        far_left, far_right = int(w * 0.44), int(w * 0.56)

        pygame.draw.polygon(
            screen, (39, 45, 48),
            [(near_left, near_y), (near_right, near_y), (far_right, far_y), (far_left, far_y)])
        pygame.draw.line(screen, (97, 104, 107), (near_left, near_y), (far_left, far_y), 4)
        pygame.draw.line(screen, (97, 104, 107), (near_right, near_y), (far_right, far_y), 4)

        # Distance markers bunch together toward the horizon.
        for index in range(1, 9):
            depth = (index / 9) ** 2
            y = int(near_y + (far_y - near_y) * depth)
            left = int(near_left + (far_left - near_left) * depth)
            right = int(near_right + (far_right - near_right) * depth)
            pygame.draw.line(screen, (68, 75, 78), (left, y), (right, y), 2)

        # Finish line directly in front of the doll.
        pygame.draw.line(screen, WHITE, (far_left - 12, far_y + 8), (far_right + 12, far_y + 8), 5)

    def _draw_doll(self, screen: pygame.Surface, w: int, horizon: int, color) -> None:
        x, y = w // 2, int(horizon * 0.42)
        facing_player = self.phase == "red" and self.mode == "play"
        pygame.draw.circle(screen, (230, 188, 148), (x, y), 45)
        hair = (50, 35, 31)
        pygame.draw.arc(screen, hair, (x - 48, y - 49, 96, 92), math.pi, math.pi * 2, 13)
        pygame.draw.rect(screen, (236, 155, 76), (x - 42, y + 38, 84, 92), border_radius=14)
        if facing_player:
            pygame.draw.circle(screen, color, (x - 16, y - 2), 6)
            pygame.draw.circle(screen, color, (x + 16, y - 2), 6)
        else:
            pygame.draw.arc(screen, hair, (x - 29, y - 10, 58, 36), 0, math.pi, 8)

    def _draw_player(self, screen: pygame.Surface, w: int, h: int, horizon: int) -> None:
        progress = max(0.0, min(1.0, self.course / 100))
        near_y, far_y = h - 68, horizon + 34
        depth = progress ** 0.72   # eased so early movement is easy to see
        x = w // 2
        y = int(near_y + (far_y - near_y) * depth)
        scale = 1.0 - 0.62 * depth
        head = max(5, int(13 * scale))
        torso = max(12, int(35 * scale))
        limb = max(8, int(27 * scale))
        width = max(3, int(7 * scale))
        color = (108, 194, 225)

        swing = 0
        if self.running_detected:
            swing = int(math.sin(self.elapsed * 15) * limb * 0.55)

        shoulder_y = y - torso
        hip_y = y
        pygame.draw.circle(screen, color, (x, shoulder_y - head - 2), head)
        pygame.draw.line(screen, color, (x, shoulder_y), (x, hip_y), width)
        pygame.draw.line(screen, color, (x, shoulder_y + 3), (x - limb // 2, shoulder_y + limb + swing), width)
        pygame.draw.line(screen, color, (x, shoulder_y + 3), (x + limb // 2, shoulder_y + limb - swing), width)
        pygame.draw.line(screen, color, (x, hip_y), (x - limb // 3, hip_y + limb - swing // 2), width)
        pygame.draw.line(screen, color, (x, hip_y), (x + limb // 3, hip_y + limb + swing // 2), width)

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int, color) -> None:
        if self.mode == "calibrate":
            heading = "CALIBRATING"
        elif self.phase == "green":
            heading = "GREEN LIGHT"
        elif self.phase_time < STOP_GRACE:
            heading = "STOP!"
        else:
            heading = "RED LIGHT"
        draw_text_centered(screen, self.big_font, heading, color, (w // 2, 50))

        if self.mode == "calibrate":
            self.draw_calibration(screen)
        else:
            draw_text_centered(screen, self.font, self.status, WHITE, (w // 2, 100))

            bx, by, bw = w // 2 - 180, 135, 360
            draw_bar(screen, (bx, by, bw, 16), self.course / 100, GREEN, back=BAR_BACK, radius=6)
            draw_text_centered(screen, self.small_font, f"COURSE  {self.course:.0f}%", WHITE,
                               (w // 2, by + 32))
            if self.phase == "red":
                draw_bar(screen, (bx, by + 58, bw, 10), self.exposure / CAUGHT_AFTER, RED,
                         back=BAR_BACK, radius=5)

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            body = self.tracker.body
            hands = "visible" if body and body[3] else "lowered/off-screen"
            info = f"Body tracking: {self.tracker.backend}   hands: {hands}   (C = recalibrate)"
        else:
            info = "No camera tracking - keyboard: alternate A/D or arrows"
        draw_status_line(screen, self.small_font, info)
