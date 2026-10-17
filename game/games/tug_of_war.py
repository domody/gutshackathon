from __future__ import annotations

import math
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import cv2
import mediapipe as mp
import numpy as np
import pygame
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from game.minigame import Action, Minigame


HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
MODEL_DIR = Path(__file__).resolve().parent
HAND_MODEL_PATH = MODEL_DIR / "hand_landmarker.task"
POSE_MODEL_PATH = MODEL_DIR / "pose_landmarker_lite.task"

LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
PREVIEW_SIZE = (160, 120)
STALE_SECONDS = 0.6
VISIBILITY_THRESHOLD = 0.45
TRACKING_FPS = 20
POSE_INTERVAL = 4

CALIBRATION_SECONDS = 1.2
CALIBRATION_TIMEOUT = 6.0
DISTANCE_TOLERANCE = 0.42
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


@dataclass(frozen=True)
class HandReading:
    side: str
    open_hand: bool
    fist: bool
    wrist_x: float
    wrist_y: float
    palm_size: float


@dataclass(frozen=True)
class TrackingReading:
    body_visible: bool = False
    shoulder_width: float = 0.0
    left_shoulder: tuple[float, float] = (0.0, 0.0)
    right_shoulder: tuple[float, float] = (0.0, 0.0)
    hands: tuple[HandReading, ...] = ()
    timestamp: float = 0.0


class PullTracker:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.error: str | None = None
        self._capture = None
        self._hands = None
        self._pose = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._reading = TrackingReading()
        self._preview: bytes | None = None
        self._cached_pose = None
        self._frame_number = 0

    def start(self) -> None:
        if self._running:
            return
        capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            capture.release()
            self.error = "Could not open webcam"
            return
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        capture.set(cv2.CAP_PROP_FPS, TRACKING_FPS)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._capture = capture
        try:
            self._download_model(HAND_MODEL_URL, HAND_MODEL_PATH)
            self._download_model(POSE_MODEL_URL, POSE_MODEL_PATH)
            self._hands = vision.HandLandmarker.create_from_options(
                vision.HandLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(HAND_MODEL_PATH)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=2,
                    min_hand_detection_confidence=0.55,
                    min_hand_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
            )
            self._pose = vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(POSE_MODEL_PATH)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_poses=1,
                    min_pose_detection_confidence=0.55,
                    min_pose_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
            )
        except Exception as exc:
            self.error = repr(exc)
            capture.release()
            self._capture = None
            self._hands = None
            self._pose = None
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if self._hands is not None:
            self._hands.close()
            self._hands = None
        if self._pose is not None:
            self._pose.close()
            self._pose = None

    @staticmethod
    def _download_model(url: str, path: Path) -> None:
        if path.exists():
            return
        part = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(url, part)
        os.replace(part, path)

    @staticmethod
    def _visible(point) -> bool:
        return (
            getattr(point, "visibility", 1.0) >= VISIBILITY_THRESHOLD
            and getattr(point, "presence", 1.0) >= VISIBILITY_THRESHOLD
            and -0.08 <= point.x <= 1.08
            and -0.08 <= point.y <= 1.08
        )

    @staticmethod
    def _distance(a, b) -> float:
        return math.hypot(a.x - b.x, a.y - b.y)

    def _classify_hand(self, points, side: str) -> HandReading:
        wrist = points[0]
        palm_size = self._distance(points[5], points[17])
        extended = 0
        curled = 0
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            tip_distance = self._distance(points[tip], wrist)
            pip_distance = self._distance(points[pip], wrist)
            if tip_distance > pip_distance * 1.17:
                extended += 1
            if tip_distance < pip_distance * 1.03:
                curled += 1
        return HandReading(
            side=side,
            open_hand=extended >= 3,
            fist=curled >= 3,
            wrist_x=wrist.x,
            wrist_y=wrist.y,
            palm_size=palm_size,
        )

    def _read_frame(
        self, frame, now: float, timestamp_ms: int
    ) -> tuple[TrackingReading, list[tuple[float, float, bool]]]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        hand_result = self._hands.detect_for_video(image, timestamp_ms)
        if self._cached_pose is None or self._frame_number % POSE_INTERVAL == 0:
            self._cached_pose = self._pose.detect_for_video(image, timestamp_ms)
        pose_result = self._cached_pose

        body_visible = False
        shoulder_width = 0.0
        left_shoulder = (0.0, 0.0)
        right_shoulder = (0.0, 0.0)
        marks: list[tuple[float, float, bool]] = []

        if pose_result.pose_landmarks:
            pose = pose_result.pose_landmarks[0]
            left = pose[LEFT_SHOULDER]
            right = pose[RIGHT_SHOULDER]
            left_shoulder = (left.x, left.y)
            right_shoulder = (right.x, right.y)
            shoulder_width = self._distance(left, right)
            body_visible = self._visible(left) and self._visible(right) and shoulder_width >= 0.055
            marks.extend(
                [
                    (left.x, left.y, self._visible(left)),
                    (right.x, right.y, self._visible(right)),
                ]
            )

        hands: list[HandReading] = []
        for index, points in enumerate(hand_result.hand_landmarks):
            category = hand_result.handedness[index][0]
            side = category.category_name.lower()
            hand = self._classify_hand(points, side)
            hands.append(hand)
            color_state = hand.open_hand or hand.fist
            marks.extend(
                (points[landmark].x, points[landmark].y, color_state)
                for landmark in (0, 5, 8, 9, 12, 13, 16, 17, 20)
            )

        return (
            TrackingReading(
                body_visible=body_visible,
                shoulder_width=shoulder_width,
                left_shoulder=left_shoulder,
                right_shoulder=right_shoulder,
                hands=tuple(hands),
                timestamp=now,
            ),
            marks,
        )

    def _loop(self) -> None:
        while self._running:
            frame_started = time.monotonic()
            ok, frame = self._capture.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)
            now = time.time()
            timestamp_ms = int(time.monotonic() * 1000)
            try:
                reading, marks = self._read_frame(frame, now, timestamp_ms)
            except Exception as exc:
                self.error = repr(exc)
                reading, marks = TrackingReading(timestamp=now), []
            small = cv2.resize(frame, PREVIEW_SIZE)
            for x, y, active in marks:
                color = (70, 235, 100) if active else (70, 90, 235)
                cv2.circle(
                    small,
                    (int(x * PREVIEW_SIZE[0]), int(y * PREVIEW_SIZE[1])),
                    3,
                    color,
                    -1,
                )
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()
            with self._lock:
                self._reading = reading
                self._preview = preview
            self._frame_number += 1
            remaining = 1 / TRACKING_FPS - (time.monotonic() - frame_started)
            if remaining > 0:
                time.sleep(remaining)

    @property
    def available(self) -> bool:
        return self._running and self._hands is not None and self._pose is not None

    @property
    def reading(self) -> TrackingReading:
        with self._lock:
            reading = self._reading
        if time.time() - reading.timestamp > STALE_SECONDS:
            return TrackingReading(timestamp=reading.timestamp)
        return reading

    def preview_surface(self) -> pygame.Surface | None:
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, PREVIEW_SIZE, "RGB")


class TugOfWar(Minigame):
    title = "Tug of War"

    def __init__(self, screen: pygame.Surface, tracker: PullTracker | None = None) -> None:
        super().__init__(screen)
        self.font = pygame.font.Font(None, 40)
        self.small_font = pygame.font.Font(None, 25)
        self.big_font = pygame.font.Font(None, 88)
        self._owns_tracker = tracker is None
        self.tracker = tracker if tracker is not None else PullTracker()
        self.tracker.start()
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Left Pull", "Reach, grab and pull with your left hand", self.pull_left),
            Action("Right Pull", "Reach, grab and pull with your right hand", self.pull_right),
        )

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.result: bool | None = None
        self.result_time = 0.0
        self.rope_position = 0.0
        self.mode = "calibrate" if self.tracker.available else "play"
        self.calibration_time = 0.0
        self.wait_time = 0.0
        self.width_samples: list[float] = []
        self.neutral_width: float | None = None
        self.expected_side: str | None = None
        self.armed_sides: set[str] = set()
        self.pull_side: str | None = None
        self.pull_size = 0.0
        self.pull_distance = 0.0
        self.pull_flash = 0.0
        self.last_pull_time = 0.0
        self.total_pulls = 0
        self.status = "Stand still with your shoulders visible"

    def close(self) -> None:
        if self._owns_tracker:
            self.tracker.stop()

    def pull_left(self) -> None:
        self._keyboard_pull("left")

    def pull_right(self) -> None:
        self._keyboard_pull("right")

    def _keyboard_pull(self, side: str) -> None:
        if self.mode != "play" or self.result is not None:
            return
        if self.expected_side is not None and side == self.expected_side:
            self._complete_pull(side)
        elif self.expected_side is None:
            self._complete_pull(side)
        else:
            self.status = f"Use your {self.expected_side} hand next"

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        left, right = self.actions
        if event.key in (pygame.K_a, pygame.K_LEFT):
            left.perform()
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            right.perform()
        elif event.key == pygame.K_c:
            self._begin_calibration()
        elif event.key == pygame.K_ESCAPE:
            self.finished = True

    def _begin_calibration(self) -> None:
        self.mode = "calibrate" if self.tracker.available else "play"
        self.calibration_time = 0.0
        self.wait_time = 0.0
        self.width_samples = []
        self.status = "Stand still at your playing distance"

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
            self._update_calibration(dt)
            return

        if self.tracker.available:
            reading = self.tracker.reading
            if not reading.body_visible:
                self.status = "Paused - keep both shoulders visible"
                return
            if not self._distance_ok(reading):
                self.status = "Paused - return to your calibrated distance"
                return
            self._update_gesture(reading)

        if time.time() - self.last_pull_time > 1.0:
            self.rope_position = max(LOSE_POSITION, self.rope_position - OPPONENT_SPEED * dt)

        if self.rope_position >= WIN_POSITION:
            self._set_result(True)
        elif self.rope_position <= LOSE_POSITION:
            self._set_result(False)

    def _update_calibration(self, dt: float) -> None:
        self.wait_time += dt
        reading = self.tracker.reading
        if reading.body_visible:
            self.calibration_time += dt
            self.width_samples.append(reading.shoulder_width)
            self.status = "Hold still - calibrating distance"
        else:
            self.status = "Show both shoulders to the camera"

        enough = self.calibration_time >= CALIBRATION_SECONDS and len(self.width_samples) >= 10
        if enough or self.wait_time >= CALIBRATION_TIMEOUT or not self.tracker.available:
            if self.width_samples:
                self.neutral_width = median(self.width_samples)
            self.mode = "play"
            self.status = "Reach forward with either open hand"
            self.last_pull_time = time.time()

    def _distance_ok(self, reading: TrackingReading) -> bool:
        if self.neutral_width is None:
            return True
        ratio = reading.shoulder_width / max(self.neutral_width, 1e-4)
        return 1.0 - DISTANCE_TOLERANCE <= ratio <= 1.0 + DISTANCE_TOLERANCE

    def _shoulder_for(self, reading: TrackingReading, side: str) -> tuple[float, float]:
        return reading.left_shoulder if side == "left" else reading.right_shoulder

    def _hand_distance(self, reading: TrackingReading, hand: HandReading) -> float:
        shoulder = self._shoulder_for(reading, hand.side)
        return math.hypot(hand.wrist_x - shoulder[0], hand.wrist_y - shoulder[1]) / max(
            reading.shoulder_width, 0.055
        )

    def _update_gesture(self, reading: TrackingReading) -> None:
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
        self.last_pull_time = time.time()
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

        preview = self.tracker.preview_surface() if self.tracker.available else None
        if preview is not None:
            pw, ph = preview.get_size()
            position = (w - pw - 10, 10)
            screen.blit(preview, position)
            pygame.draw.rect(screen, WHITE, (*position, pw, ph), 2)

        if self.tracker.available:
            info = "Reach open hand - make fist - pull to chest - alternate sides - C recalibrates"
        else:
            detail = self.tracker.error or "camera unavailable"
            info = f"{detail} - alternate A/D or arrow keys"
        screen.blit(self.small_font.render(info, True, MUTED), (10, h - 28))


if __name__ == "__main__":
    print("Run this game with: uv run main.py", file=sys.stderr)
