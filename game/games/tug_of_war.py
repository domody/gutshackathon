from __future__ import annotations

import math
import time
from statistics import median

import pygame

from game.calibrated_minigame import CalibratedMinigame
from game.minigame import Action
from game.tracking import PullTracker
from game.tracking.pull import HandReading, PullReading
from game.ui import draw_camera_preview, draw_status_line

REACH_MINIMUM = 0.24
PULL_SIZE_RATIO = 0.79
PULL_CHEST_GAIN = 0.22
PULL_POINTS = 15.0
OPPONENT_SPEED = 2.5
WIN_POSITION = 100.0
LOSE_POSITION = -100.0
RESULT_SECONDS = 2.4

BG = (12, 14, 24)
FLOOR = (28, 30, 43)
ROPE = (192, 148, 92)
PLAYER = (92, 214, 132)
OPPONENT = (229, 79, 82)
WHITE = (242, 241, 235)
MUTED = (150, 155, 170)


class TugOfWar(CalibratedMinigame):
    """Reach, grab and pull with alternating hands to drag the rope your way."""

    title = "Tug of War"
    tracker_cls = PullTracker
    calibrate_timeout = 6.0
    distance_tolerance = 0.42

    def __init__(self, screen: pygame.Surface, tracker: PullTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Left Pull", "Reach, grab and pull with your left hand"),
            Action("Right Pull", "Reach, grab and pull with your right hand"),
        )

    def start(self) -> None:
        super().start()
        self.result: bool | None = None
        self.result_time = 0.0
        self.rope_position = 0.0
        self.body_visible = False
        self.expected_side: str | None = None
        self.armed_sides: set[str] = set()
        self.pull_side: str | None = None
        self.pull_size = 0.0
        self.pull_distance = 0.0
        self.pull_flash = 0.0
        self.idle_time = 0.0
        self.total_pulls = 0
        self.status = "Reach forward with either open hand"

    # Calibration
    def read_sample(self) -> float | None:
        """Shoulder width while both shoulders are in view."""
        reading = self.tracker.reading if self.tracker.available else None
        self.body_visible = reading is not None and reading.body_visible
        return reading.shoulder_width if self.body_visible else None

    def on_calibrated(self, samples: list[float]) -> None:
        self.neutral = median(samples)

    def calibration_prompt(self) -> str:
        if self.body_visible:
            return "Hold still - calibrating distance"
        return "Show both shoulders to the camera"

    def update(self, dt: float) -> None:
        if self.finished:
            return
        self.pull_flash = max(0.0, self.pull_flash - dt)

        if self.result is not None:
            self.result_time += dt
            if self.result_time >= RESULT_SECONDS:
                self.finish(self.result)
            return

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        if self.tracker.available:
            reading = self.tracker.reading
            if not reading.body_visible:
                self.status = "Paused - keep both shoulders visible"
                return
            if not self.distance_ok(reading.shoulder_width):
                self.status = "Paused - return to your calibrated distance"
                return
            self._update_gesture(reading)

        self.idle_time += dt
        if self.idle_time > 1.0:
            self.rope_position = max(LOSE_POSITION, self.rope_position - OPPONENT_SPEED * dt)

        if self.rope_position >= WIN_POSITION:
            self._set_result(True)
        elif self.rope_position <= LOSE_POSITION:
            self._set_result(False)

    def _shoulder_for(self, reading: PullReading, side: str) -> tuple[float, float]:
        return reading.left_shoulder if side == "left" else reading.right_shoulder

    def _hand_distance(self, reading: PullReading, hand: HandReading) -> float:
        shoulder = self._shoulder_for(reading, hand.side)
        return math.hypot(hand.wrist_x - shoulder[0], hand.wrist_y - shoulder[1]) / max(
            reading.shoulder_width, 0.055
        )

    def _update_gesture(self, reading: PullReading) -> None:
        hands = {hand.side: hand for hand in reading.hands}

        if self.pull_side is not None:
            hand = hands.get(self.pull_side)
            if hand is None:
                self.status = f"Keep your {self.pull_side} fist visible"
                return
            if hand.open_hand:
                self.pull_side = None
                self.status = f"Reach again with your {self.expected_side or hand.side} hand"
                return
            if not hand.fist:
                self.status = "Keep the grabbing hand closed"
                return

            current_distance = self._hand_distance(reading, hand)
            size_pull = hand.palm_size <= self.pull_size * PULL_SIZE_RATIO
            chest_pull = self.pull_distance - current_distance >= PULL_CHEST_GAIN
            if size_pull or chest_pull:
                self._complete_pull(hand.side)
            else:
                self.status = f"Pull your {hand.side} fist back to your chest"
            return

        valid_sides = {self.expected_side} if self.expected_side is not None else {"left", "right"}
        for side in valid_sides:
            hand = hands.get(side)
            if hand is None:
                continue
            distance = self._hand_distance(reading, hand)
            reach_ratio = hand.palm_size / max(reading.shoulder_width, 0.055)
            if hand.open_hand and (distance >= 0.58 or reach_ratio >= REACH_MINIMUM):
                self.armed_sides.add(side)
                self.status = f"Close your {side} hand to grab"
            elif hand.fist and side in self.armed_sides:
                self.pull_side = side
                self.pull_size = hand.palm_size
                self.pull_distance = distance
                self.armed_sides.clear()
                self.status = f"Pull your {side} fist back to your chest"
                return

        if self.expected_side is not None and self.expected_side not in hands:
            self.status = f"Reach forward with your {self.expected_side} open hand"
        elif not reading.hands:
            self.status = "Reach forward with an open hand"

    def _complete_pull(self, side: str) -> None:
        self.rope_position = min(WIN_POSITION, self.rope_position + PULL_POINTS)
        self.expected_side = "right" if side == "left" else "left"
        self.pull_side = None
        self.armed_sides.clear()
        self.pull_flash = 0.28
        self.idle_time = 0.0
        self.total_pulls += 1
        self.status = f"Good pull! Reach with your {self.expected_side} hand"

    def _set_result(self, won: bool) -> None:
        self.result = won
        self.result_time = 0.0
        self.status = "You won!" if won else "The other team pulled you over"

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        screen.fill(BG)
        ground_y = int(h * 0.68)
        pygame.draw.rect(screen, FLOOR, (0, ground_y, w, h - ground_y))
        self._draw_rope(screen, w, ground_y)
        self._draw_teams(screen, w, ground_y)
        self._draw_hud(screen, w, h)
        if self.mode == "calibrate":
            self.draw_calibration(screen)

        if self.result is not None:
            shade = pygame.Surface((w, h), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 165))
            screen.blit(shade, (0, 0))
            message = "YOU WIN" if self.result else "ELIMINATED"
            color = PLAYER if self.result else OPPONENT
            text = self.big_font.render(message, True, color)
            screen.blit(text, ((w - text.get_width()) // 2, h // 2 - 50))

    def _draw_rope(self, screen: pygame.Surface, w: int, ground_y: int) -> None:
        y = ground_y - 30
        shift = int(self.rope_position / WIN_POSITION * w * 0.2)
        left = int(w * 0.12) + shift
        right = int(w * 0.88) + shift
        pygame.draw.line(screen, (68, 47, 31), (left + 4, y + 5), (right + 4, y + 5), 14)
        pygame.draw.line(screen, ROPE, (left, y), (right, y), 12)
        center = w // 2 + shift
        ribbon = PLAYER if self.rope_position >= 0 else OPPONENT
        pygame.draw.polygon(
            screen,
            ribbon,
            [(center - 8, y - 17), (center + 8, y - 17), (center + 13, y + 24), (center, y + 14), (center - 13, y + 24)],
        )
        pygame.draw.line(screen, WHITE, (w // 2, y - 38), (w // 2, y + 42), 3)

    def _draw_person(self, screen: pygame.Surface, x: int, y: int, color, facing: int, phase: float) -> None:
        swing = int(math.sin(phase) * 13)
        pygame.draw.circle(screen, color, (x, y - 62), 15)
        pygame.draw.line(screen, color, (x, y - 47), (x - facing * 11, y - 8), 10)
        pygame.draw.line(screen, color, (x - facing * 5, y - 37), (x + facing * 31, y - 25 + swing), 8)
        pygame.draw.line(screen, color, (x - facing * 9, y - 8), (x - 24, y + 22), 9)
        pygame.draw.line(screen, color, (x - facing * 9, y - 8), (x + 16, y + 22), 9)

    def _draw_teams(self, screen: pygame.Surface, w: int, ground_y: int) -> None:
        phase = time.time() * 7 if self.pull_flash > 0 else 0.0
        for index in range(3):
            self._draw_person(screen, int(w * 0.12) + index * 58, ground_y - 35, OPPONENT, 1, phase + index)
            self._draw_person(screen, int(w * 0.88) - index * 58, ground_y - 35, PLAYER, -1, phase + index)

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        title = self.big_font.render("TUG OF WAR", True, WHITE)
        screen.blit(title, ((w - title.get_width()) // 2, 20))
        status = self.font.render(self.status, True, WHITE)
        screen.blit(status, ((w - status.get_width()) // 2, 112))

        bx, by, bw, bh = w // 2 - 180, 165, 360, 15
        pygame.draw.rect(screen, (52, 54, 66), (bx, by, bw, bh), border_radius=6)
        marker = int(bx + bw * (self.rope_position - LOSE_POSITION) / (WIN_POSITION - LOSE_POSITION))
        pygame.draw.circle(screen, PLAYER if self.rope_position >= 0 else OPPONENT, (marker, by + bh // 2), 12)
        pygame.draw.line(screen, WHITE, (bx + bw // 2, by - 6), (bx + bw // 2, by + bh + 6), 2)

        count = self.small_font.render(f"VALID PULLS  {self.total_pulls}", True, MUTED)
        screen.blit(count, (w // 2 - count.get_width() // 2, by + 27))

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = "Reach open hand - make fist - pull to chest - alternate sides - C recalibrates"
        else:
            detail = self.tracker.error or "camera unavailable"
            info = f"{detail} - alternate A/D or arrow keys"
        draw_status_line(screen, self.small_font, info, MUTED)
