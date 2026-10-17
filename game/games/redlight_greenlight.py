from __future__ import annotations

import math
import os
import random
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from statistics import median

import cv2
import numpy as np
import pygame

from game.minigame import Action, Minigame

try:
    import mediapipe as mp

    MP_ERROR = None
except Exception as exc:  # Keep the actual import error for the fallback UI.
    mp = None
    MP_ERROR = repr(exc)


# MediaPipe pose landmark ids.
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16

POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
POSE_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pose_landmarker_lite.task"
)

VISIBILITY_THRESHOLD = 0.48
STALE_SECONDS = 0.55
SMOOTHING = 0.35
PREVIEW_SIZE = (160, 120)


@dataclass(frozen=True)
class PoseReading:
    """Thread-safe measurements consumed by the Pygame loop."""

    body_visible: bool = False
    hands_visible: bool = False
    pump: float = 0.0
    motion: float = 0.0
    shoulder_width: float = 0.0
    timestamp: float = 0.0


class PoseTracker:
    """Read the webcam on a worker thread and expose upper-body motion."""

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.backend: str | None = None
        self.error: str | None = MP_ERROR

        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._reading = PoseReading()
        self._preview: bytes | None = None

        self._pose = None
        self._landmarker = None
        self._previous: dict[int, tuple[float, float]] | None = None
        self._previous_time = 0.0
        self._smooth_pump = 0.0
        self._smooth_motion = 0.0

    def start(self) -> None:
        if self._running:
            return

        # Opening the camera on the main thread is more reliable on macOS.
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            self.error = "could not open webcam"
            print("Pose tracking: OFF -", self.error)
            return

        self._cap = cap
        if not (self._init_legacy_pose() or self._init_tasks_pose()):
            print("Pose tracking: OFF -", self.error)
            print("Python being used:", sys.executable)
            cap.release()
            self._cap = None
            return

        print(f"Pose tracking: ON ({self.backend} backend)")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._pose = None
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def _init_legacy_pose(self) -> bool:
        if mp is None:
            return False
        try:
            solutions = getattr(mp, "solutions", None)
            if solutions is None:
                return False
            self._pose = solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=0,
                enable_segmentation=False,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.5,
            )
            self.backend = "mediapipe-pose"
            return True
        except Exception as exc:
            self.error = f"legacy Pose unavailable: {exc!r}"
            return False

    def _init_tasks_pose(self) -> bool:
        if mp is None:
            return False
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            if not os.path.exists(POSE_MODEL_PATH):
                print("Downloading pose model (one time, ~6 MB)...")
                urllib.request.urlretrieve(POSE_MODEL_URL, POSE_MODEL_PATH + ".part")
                os.replace(POSE_MODEL_PATH + ".part", POSE_MODEL_PATH)

            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=POSE_MODEL_PATH),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.55,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._landmarker = vision.PoseLandmarker.create_from_options(options)
            self.backend = "mediapipe-tasks"
            return True
        except Exception as exc:
            self.error = f"PoseLandmarker failed: {exc!r}"
            return False

    def _detect(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.backend == "mediapipe-pose":
            result = self._pose.process(rgb)
            if not result.pose_landmarks:
                return None
            return result.pose_landmarks.landmark

        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect(image)
        return result.pose_landmarks[0] if result.pose_landmarks else None

    @staticmethod
    def _visible(point) -> bool:
        visibility = getattr(point, "visibility", 1.0)
        presence = getattr(point, "presence", 1.0)
        return (
            visibility >= VISIBILITY_THRESHOLD
            and presence >= VISIBILITY_THRESHOLD
            and -0.08 <= point.x <= 1.08
            and -0.08 <= point.y <= 1.08
        )

    def _measure(self, points, now: float) -> tuple[PoseReading, list[tuple[float, float, bool]]]:
        if points is None or len(points) <= RIGHT_WRIST:
            self._previous = None
            return PoseReading(timestamp=now), []

        # Keep the framing requirement achievable at laptop distance: head and
        # shoulders establish that the player is present, while hands may leave
        # the frame and still count as frozen.
        body_ids = (NOSE, LEFT_SHOULDER, RIGHT_SHOULDER)
        body_visible = all(self._visible(points[index]) for index in body_ids)
        hands_visible = all(self._visible(points[index]) for index in (LEFT_WRIST, RIGHT_WRIST))
        shoulder_width = math.hypot(
            points[LEFT_SHOULDER].x - points[RIGHT_SHOULDER].x,
            points[LEFT_SHOULDER].y - points[RIGHT_SHOULDER].y,
        )
        body_visible = body_visible and shoulder_width >= 0.055

        tracked_ids = (
            LEFT_SHOULDER,
            RIGHT_SHOULDER,
            LEFT_ELBOW,
            RIGHT_ELBOW,
            LEFT_WRIST,
            RIGHT_WRIST,
        )
        current = {
            index: (points[index].x, points[index].y)
            for index in tracked_ids
            if self._visible(points[index])
        }
        motion = 0.0
        pump = 0.0
        dt = now - self._previous_time

        if self._previous is not None and 1 / 120 <= dt <= 0.2 and body_visible:
            # Broad upper-body speed is used to judge stillness on red. When a
            # wrist is off-screen, shoulders and any visible elbows still count.
            stable_ids = [
                index
                for index in tracked_ids
                if index in current and index in self._previous
            ]
            if stable_ids:
                motion = sum(
                    math.hypot(
                        current[index][0] - self._previous[index][0],
                        current[index][1] - self._previous[index][1],
                    )
                    for index in stable_ids
                ) / len(stable_ids) / max(shoulder_width, 0.055) / dt

            if hands_visible and LEFT_WRIST in self._previous and RIGHT_WRIST in self._previous:
                left_speed = (current[LEFT_WRIST][1] - self._previous[LEFT_WRIST][1]) / dt
                right_speed = (current[RIGHT_WRIST][1] - self._previous[RIGHT_WRIST][1]) / dt
                opposite = left_speed * right_speed < 0
                if opposite:
                    pump = abs(left_speed - right_speed) / max(shoulder_width, 0.055)

        if body_visible:
            self._previous = current
            self._previous_time = now
        else:
            self._previous = None

        self._smooth_pump += (pump - self._smooth_pump) * SMOOTHING
        self._smooth_motion += (motion - self._smooth_motion) * SMOOTHING

        preview_ids = (
            NOSE,
            LEFT_SHOULDER,
            RIGHT_SHOULDER,
            LEFT_ELBOW,
            RIGHT_ELBOW,
            LEFT_WRIST,
            RIGHT_WRIST,
        )
        marks = [
            (points[index].x, points[index].y, self._visible(points[index]))
            for index in preview_ids
        ]
        return (
            PoseReading(
                body_visible=body_visible,
                hands_visible=hands_visible,
                pump=self._smooth_pump,
                motion=self._smooth_motion,
                shoulder_width=shoulder_width,
                timestamp=now,
            ),
            marks,
        )

    def _loop(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            frame = cv2.flip(frame, 1)
            now = time.time()
            try:
                points = self._detect(frame)
                reading, marks = self._measure(points, now)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                reading, marks = PoseReading(timestamp=now), []

            small = cv2.resize(frame, PREVIEW_SIZE)
            for x, y, visible in marks:
                color = (60, 230, 80) if visible else (50, 80, 230)
                cv2.circle(
                    small,
                    (int(x * PREVIEW_SIZE[0]), int(y * PREVIEW_SIZE[1])),
                    4,
                    color,
                    -1,
                )
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()

            with self._lock:
                self._reading = reading
                self._preview = preview

    @property
    def available(self) -> bool:
        return self._running and self.backend is not None

    @property
    def reading(self) -> PoseReading:
        with self._lock:
            reading = self._reading
        if time.time() - reading.timestamp > STALE_SECONDS:
            return PoseReading(timestamp=reading.timestamp)
        return reading

    def preview_surface(self) -> pygame.Surface | None:
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, PREVIEW_SIZE, "RGB")


# Game tuning.
CALIBRATE_SECONDS = 1.25
CALIBRATE_TIMEOUT = 6.0
GREEN_SECONDS = 2.8
RED_SECONDS = 2.6
STOP_GRACE = 0.65
COURSE_PER_SECOND = 4.5
PUMP_THRESHOLD = 0.9
DEFAULT_FREEZE_THRESHOLD = 0.38
CAUGHT_AFTER = 0.18
DISTANCE_TOLERANCE = 0.38

BG = (11, 16, 20)
GREEN = (91, 210, 102)
RED = (238, 74, 79)
WHITE = (242, 242, 235)
MUTED = (155, 164, 170)


class RedLightGreenLight(Minigame):
    """Advance by alternating arms on green and freeze on red."""

    title = "Red Light, Green Light"

    def __init__(self, screen: pygame.Surface, tracker: PoseTracker | None = None) -> None:
        super().__init__(screen)
        pygame.font.init()
        self.font = pygame.font.Font(None, 38)
        self.small_font = pygame.font.Font(None, 25)
        self.big_font = pygame.font.Font(None, 72)
        self.huge_font = pygame.font.Font(None, 108)

        self._owns_tracker = tracker is None
        self.tracker = tracker if tracker is not None else PoseTracker()
        self.tracker.start()
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Pump Left", "Pump the left arm (A / Left)", self.pump_left),
            Action("Pump Right", "Pump the right arm (D / Right)", self.pump_right),
        )

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.mode = "calibrate" if self.tracker.available else "play"
        self.course = 0.0
        self.phase = "green"
        self.phase_time = 0.0
        self.red_exposure = 0.0
        self.total_time = 0.0
        self.running_detected = False
        self.status = "Look straight ahead and stand still"

        self.calib_time = 0.0
        self.wait_time = 0.0
        self.motion_samples: list[float] = []
        self.width_samples: list[float] = []
        self.neutral_width: float | None = None
        self.freeze_threshold = DEFAULT_FREEZE_THRESHOLD

        self.last_keyboard_arm = 0
        self.keyboard_pulse = 0.0
        self.keyboard_motion = 0.0

    def close(self) -> None:
        if self._owns_tracker:
            self.tracker.stop()

    def pump_left(self) -> None:
        self._keyboard_action(-1)

    def pump_right(self) -> None:
        self._keyboard_action(1)

    def _keyboard_action(self, arm: int) -> None:
        self.keyboard_motion = 0.24
        if arm != self.last_keyboard_arm:
            self.keyboard_pulse = 0.2
            self.last_keyboard_arm = arm

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

    def _begin_calibration(self) -> None:
        self.mode = "calibrate" if self.tracker.available else "play"
        self.calib_time = 0.0
        self.wait_time = 0.0
        self.motion_samples = []
        self.width_samples = []
        self.status = "Stand still while distance is calibrated"

    def update(self, dt: float) -> None:
        if self.finished:
            return

        self.keyboard_pulse = max(0.0, self.keyboard_pulse - dt)
        self.keyboard_motion = max(0.0, self.keyboard_motion - dt)

        if self.mode == "calibrate":
            self._update_calibration(dt)
            return

        reading = self.tracker.reading if self.tracker.available else PoseReading()
        camera_active = self.tracker.available

        if camera_active and not reading.body_visible:
            self.running_detected = False
            self.status = "Paused - keep head, shoulders and torso visible"
            return

        if camera_active and not self._distance_ok(reading):
            self.running_detected = False
            self.status = "Paused - return to your calibrated distance"
            return

        self.total_time += dt
        self.phase_time += dt
        self._advance_phase()

        keyboard_running = self.keyboard_pulse > 0
        camera_running = reading.hands_visible and reading.pump >= PUMP_THRESHOLD
        running = keyboard_running or camera_running
        self.running_detected = self.phase == "green" and running

        if self.phase == "green":
            self.red_exposure = max(0.0, self.red_exposure - dt * 3)
            if running:
                intensity = max(1.0, min(1.75, reading.pump / PUMP_THRESHOLD)) if camera_running else 1.0
                self.course = min(100.0, self.course + COURSE_PER_SECOND * intensity * dt)
                self.status = "Running detected - keep alternating"
            elif camera_active and not reading.hands_visible:
                self.status = "GREEN - bring both hands into view"
            else:
                self.status = "GREEN - alternate your arms"
        else:
            self.running_detected = False
            in_grace = self.phase_time < STOP_GRACE
            camera_motion = reading.motion > self.freeze_threshold
            keyboard_motion = self.keyboard_motion > 0
            moving = camera_motion or keyboard_motion

            if in_grace:
                self.red_exposure = max(0.0, self.red_exposure - dt * 2)
                self.status = "RED - stop!"
            elif moving:
                self.red_exposure = min(CAUGHT_AFTER, self.red_exposure + dt)
                self.status = "Movement detected..."
            else:
                self.red_exposure = max(0.0, self.red_exposure - dt * 2)
                if camera_active and not reading.hands_visible:
                    self.status = "Frozen - hands lowered, body still visible"
                else:
                    self.status = "Frozen - good"

            if self.red_exposure >= CAUGHT_AFTER:
                self.finish(False)

        if self.course >= 100.0:
            self.finish(True)

    def _update_calibration(self, dt: float) -> None:
        self.wait_time += dt
        reading = self.tracker.reading
        if reading.body_visible:
            self.calib_time += dt
            self.motion_samples.append(reading.motion)
            self.width_samples.append(reading.shoulder_width)
            self.status = "Hold still - calibrating distance and movement"
        else:
            self.status = "Show your head, shoulders and upper body"

        enough = self.calib_time >= CALIBRATE_SECONDS and len(self.width_samples) >= 10
        timed_out = self.wait_time >= CALIBRATE_TIMEOUT
        if enough or timed_out or not self.tracker.available:
            if self.width_samples:
                self.neutral_width = median(self.width_samples)
            if self.motion_samples:
                baseline = median(self.motion_samples)
                self.freeze_threshold = max(DEFAULT_FREEZE_THRESHOLD, baseline * 3.2)
            self.mode = "play"
            self.phase = "green"
            self.phase_time = 0.0
            self.status = "GREEN - alternate your arms"

    def _distance_ok(self, reading: PoseReading) -> bool:
        if self.neutral_width is None:
            return True
        ratio = reading.shoulder_width / max(self.neutral_width, 1e-4)
        return 1.0 - DISTANCE_TOLERANCE <= ratio <= 1.0 + DISTANCE_TOLERANCE

    def _advance_phase(self) -> None:
        duration = GREEN_SECONDS if self.phase == "green" else RED_SECONDS
        if self.phase_time < duration:
            return
        self.phase = "red" if self.phase == "green" else "green"
        self.phase_time = 0.0
        self.red_exposure = 0.0

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        color = GREEN if self.phase == "green" else RED
        screen.fill(BG)

        # Strong full-screen light cue, readable from several metres away.
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
            screen,
            (39, 45, 48),
            [(near_left, near_y), (near_right, near_y), (far_right, far_y), (far_left, far_y)],
        )
        pygame.draw.line(screen, (97, 104, 107), (near_left, near_y), (far_left, far_y), 4)
        pygame.draw.line(screen, (97, 104, 107), (near_right, near_y), (far_right, far_y), 4)

        # Distance markers bunch together toward the horizon.
        for index in range(1, 9):
            progress = index / 9
            depth = progress * progress
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
        # Ease the depth so early movement is easy to see.
        depth = progress ** 0.72
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
            swing = int(math.sin(self.total_time * 15) * limb * 0.55)

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

        title = self.huge_font.render(heading, True, color)
        screen.blit(title, ((w - title.get_width()) // 2, 22))
        status = self.font.render(self.status, True, WHITE)
        screen.blit(status, ((w - status.get_width()) // 2, 125))

        # Course bar.
        bx, by, bw, bh = w // 2 - 180, 178, 360, 16
        pygame.draw.rect(screen, (52, 58, 63), (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(screen, GREEN, (bx, by, int(bw * self.course / 100), bh), border_radius=6)
        course_text = self.small_font.render(f"COURSE  {self.course:.0f}%", True, WHITE)
        screen.blit(course_text, (w // 2 - course_text.get_width() // 2, by + 23))

        # Red-light motion exposure.
        if self.phase == "red" and self.mode == "play":
            ex = min(1.0, self.red_exposure / CAUGHT_AFTER)
            ex_y = by + 58
            pygame.draw.rect(screen, (52, 58, 63), (bx, ex_y, bw, 10), border_radius=5)
            pygame.draw.rect(screen, RED, (bx, ex_y, int(bw * ex), 10), border_radius=5)

        preview = self.tracker.preview_surface() if self.tracker.available else None
        if preview is not None:
            pw, ph = preview.get_size()
            pos = (w - pw - 12, 12)
            screen.blit(preview, pos)
            pygame.draw.rect(screen, WHITE, (*pos, pw, ph), 2)

        reading = self.tracker.reading if self.tracker.available else PoseReading()
        if self.tracker.available:
            tracking = (
                f"Pose: {self.tracker.backend} | hands: "
                f"{'visible' if reading.hands_visible else 'lowered/off-screen'} | C = recalibrate"
            )
        else:
            tracking = "Camera unavailable - alternate A/D or arrow keys"
        screen.blit(self.small_font.render(tracking, True, MUTED), (12, h - 29))


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((1100, 680))
    pygame.display.set_caption("Red Light, Green Light")
    clock = pygame.time.Clock()
    result_font = pygame.font.Font(None, 92)
    hint_font = pygame.font.Font(None, 32)

    game = RedLightGreenLight(screen)
    running = True
    while running:
        dt = min(0.1, clock.tick(60) / 1000.0)
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
            ):
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE and game.finished:
                game.start()
            else:
                game.handle_event(event)

        game.update(dt)
        game.draw(screen)

        if game.finished:
            shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 165))
            screen.blit(shade, (0, 0))
            message = "YOU MADE IT!" if game.won else "ELIMINATED"
            color = GREEN if game.won else RED
            text = result_font.render(message, True, color)
            hint = hint_font.render("Press SPACE to play again", True, WHITE)
            cx, cy = screen.get_width() // 2, screen.get_height() // 2
            screen.blit(text, (cx - text.get_width() // 2, cy - 60))
            screen.blit(hint, (cx - hint.get_width() // 2, cy + 35))

        pygame.display.flip()

    game.close()
    pygame.quit()


if __name__ == "__main__":
    main()
