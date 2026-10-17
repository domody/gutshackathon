"""Simon Says: a head pose flashes up; copy it before the bar empties. Simon with your head.

Single-file minigame (camera pose tracking + game + demo runner).

Poses:  TURN LEFT / TURN RIGHT / TILT LEFT / TILT RIGHT
Win:    copy 8 commands.   Lose: the time bar runs out.

Optional challenges (constructor kwargs or attributes, all default off):
  fast      shorter time for every command and a shorter hold
  opposite  some commands are red: do the OPPOSITE pose
  combo     commands are two poses in a row, in order

Install:  uv add pygame opencv-python mediapipe numpy
Try it:   python -m game.games.mirror_me        (run from the project root)

Demo keys: 1/2/3 toggle challenges, SPACE start, C recentre head, Esc quit.
Keyboard fallback: A/D turn, Q/E tilt.
"""

from __future__ import annotations

import math
import os
import random
import sys
import threading
import time
import urllib.request
from statistics import median

import cv2
import numpy as np
import pygame

from game.minigame import Action, Minigame

try:
    import mediapipe as mp
    MP_ERROR = None
except Exception as exc:  # keep the real reason so it can be reported
    mp = None
    MP_ERROR = repr(exc)


# =============================================================================
# Pose tracking (background thread; MediaPipe mesh -> MediaPipe tasks -> OpenCV Haar)
# Reports a yaw ratio (~0.5 facing forward) and a roll angle in degrees
# (positive = head tilted toward the right of the screen, as seen in the mirror).
# =============================================================================
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")

NOSE_TIP, CHEEK_A, CHEEK_B = 1, 234, 454   # FaceMesh landmark ids
STALE_SECONDS = 0.5      # no face for this long -> pose becomes None
SMOOTHING = 0.5          # 0..1, higher = snappier, lower = smoother
PREVIEW_SIZE = (160, 120)


class PoseTracker:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.backend: str | None = None
        self.error: str | None = MP_ERROR
        self.scale = 0.14  # yaw-ratio change that maps to "full turn"

        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._ratio: float | None = None
        self._roll = 0.0
        self._pose_time = 0.0
        self._preview: bytes | None = None

        self._mesh = None
        self._landmarker = None
        self._cascade = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running:
            return
        # Open the camera on the calling (main) thread: macOS wants that.
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            self.error = "could not open webcam"
            print("Pose tracking: OFF -", self.error)
            return
        self._cap = cap
        if not (self._init_mesh() or self._init_tasks() or self._init_haar()):
            print("Pose tracking: OFF -", self.error)
            print("Python being used:", sys.executable)
            cap.release()
            self._cap = None
            return
        print(f"Pose tracking: ON ({self.backend} backend)")
        if not self.has_roll:
            print("  (no MediaPipe: head tilt can't be detected, only left/right poses are used)")
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

    # ------------------------------------------------------------- backends
    def _init_mesh(self) -> bool:
        if mp is None:
            return False
        try:
            self._mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1, refine_landmarks=False,
                min_detection_confidence=0.5, min_tracking_confidence=0.5)
            self.backend, self.scale = "mediapipe-mesh", 0.14
            return True
        except Exception as exc:
            self.error = f"legacy FaceMesh unavailable: {exc!r}"
            return False

    def _init_tasks(self) -> bool:
        if mp is None:
            return False
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            if not os.path.exists(FACE_MODEL_PATH):
                print("Downloading face model (one time, ~4 MB)...")
                urllib.request.urlretrieve(FACE_MODEL_URL, FACE_MODEL_PATH + ".part")
                os.replace(FACE_MODEL_PATH + ".part", FACE_MODEL_PATH)
            options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=FACE_MODEL_PATH),
                num_faces=1,
                running_mode=vision.RunningMode.IMAGE)
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
            self.backend, self.scale = "mediapipe-tasks", 0.14
            return True
        except Exception as exc:
            self.error = f"FaceLandmarker failed: {exc!r}"
            return False

    def _init_haar(self) -> bool:
        try:
            path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            cascade = cv2.CascadeClassifier(path)
            if cascade.empty():
                raise RuntimeError("cascade file not found")
            self._cascade = cascade
            self.backend, self.scale = "opencv-haar", 0.12
            return True
        except Exception as exc:
            self.error = f"Haar fallback failed: {exc!r}"
            return False

    # ---------------------------------------------------------- measurement
    @staticmethod
    def _mesh_pose(pts, w: int, h: int):
        """Yaw ratio = nose position projected onto the cheek-to-cheek axis, so it
        stays put when the head tilts. Roll = angle of that axis in degrees."""
        ax, ay = pts[CHEEK_A].x * w, pts[CHEEK_A].y * h
        bx, by = pts[CHEEK_B].x * w, pts[CHEEK_B].y * h
        if ax > bx:
            ax, ay, bx, by = bx, by, ax, ay
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 < 1e-6:
            return None, None, []
        nx, ny = pts[NOSE_TIP].x * w, pts[NOSE_TIP].y * h
        ratio = ((nx - ax) * dx + (ny - ay) * dy) / length2
        roll = math.degrees(math.atan2(dy, dx))
        marks = [(pts[i].x, pts[i].y) for i in (NOSE_TIP, CHEEK_A, CHEEK_B)]
        return ratio, roll, marks

    def _measure(self, frame_bgr):
        """Returns (ratio, roll_degrees, preview marks) or (None, None, [])."""
        h, w = frame_bgr.shape[:2]
        if self.backend == "opencv-haar":
            small_w = 320
            small_h = int(h * small_w / w)
            gray = cv2.cvtColor(cv2.resize(frame_bgr, (small_w, small_h)), cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
            if len(faces) == 0:
                return None, None, []
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            cx, cy = (x + fw / 2) / small_w, (y + fh / 2) / small_h
            return cx, 0.0, [(cx, cy)]

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.backend == "mediapipe-mesh":
            res = self._mesh.process(rgb)
            if not res.multi_face_landmarks:
                return None, None, []
            return self._mesh_pose(res.multi_face_landmarks[0].landmark, w, h)

        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect(img)
        if not res.face_landmarks:
            return None, None, []
        return self._mesh_pose(res.face_landmarks[0], w, h)

    def _loop(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror: turning right moves you right
            try:
                ratio, roll, marks = self._measure(frame)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                ratio, roll, marks = None, None, []

            small = cv2.resize(frame, PREVIEW_SIZE)
            for mx, my in marks:
                cv2.circle(small, (int(mx * PREVIEW_SIZE[0]), int(my * PREVIEW_SIZE[1])),
                           3, (0, 255, 0), -1)
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()

            now = time.time()
            with self._lock:
                if ratio is not None:
                    fresh = self._ratio is not None and now - self._pose_time < STALE_SECONDS
                    if fresh:
                        self._ratio = self._ratio * (1 - SMOOTHING) + ratio * SMOOTHING
                        self._roll = self._roll * (1 - SMOOTHING) + roll * SMOOTHING
                    else:
                        self._ratio, self._roll = ratio, roll
                    self._pose_time = now
                self._preview = preview

    # ------------------------------------------------------------ accessors
    @property
    def available(self) -> bool:
        return self._running and self.backend is not None

    @property
    def has_roll(self) -> bool:
        """False for the Haar fallback, which can't measure head tilt."""
        return self.backend in ("mediapipe-mesh", "mediapipe-tasks")

    @property
    def pose(self) -> tuple[float, float] | None:
        """Smoothed (yaw_ratio, roll_degrees), or None if no face seen recently."""
        with self._lock:
            if self._ratio is None or time.time() - self._pose_time > STALE_SECONDS:
                return None
            return self._ratio, self._roll

    def preview_surface(self) -> pygame.Surface | None:
        """Small mirrored camera image with tracking dots, for on-screen display."""
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, PREVIEW_SIZE, "RGB")


# =============================================================================
# The minigame
# =============================================================================
TARGET_COMMANDS = 8

# Time per command ramps from START to END over the round.
TIME_START, TIME_END = 2.6, 1.6
FAST_TIME_START, FAST_TIME_END = 1.9, 1.2
COMBO_TIME_FACTOR = 0.85     # combo gets (poses x base x this) seconds
HOLD_TIME = 0.30             # how long a pose must be held to count
FAST_HOLD_TIME = 0.22
OPPOSITE_CHANCE = 0.4        # chance a command is "opposite" (once enabled, after 2 commands)

# Pose detection (relative to the calibrated neutral)
YAW_THRESH = 0.6             # fraction of a full turn (tracker.scale)
TILT_THRESH = 14.0           # degrees

CALIBRATE_SECONDS = 1.2
CALIBRATE_TIMEOUT = 5.0
READY_SECONDS = 1.0
FLASH_SECONDS = 0.35
SIM_SECONDS = 0.45           # keyboard fallback: how long a key press "holds" a pose

# pose id -> (label, avatar yaw -1..1, avatar roll degrees)
POSES = {
    "left": ("TURN LEFT", -1.0, 0.0),
    "right": ("TURN RIGHT", 1.0, 0.0),
    "tilt_left": ("TILT LEFT", 0.0, -28.0),
    "tilt_right": ("TILT RIGHT", 0.0, 28.0),
}
OPPOSITE = {"left": "right", "right": "left", "tilt_left": "tilt_right", "tilt_right": "tilt_left"}
FLASH_WORDS = ("NICE!", "YES!", "GOOD!", "BOOM!", "SMOOTH!")

# (attribute, label, description) for menus
CHALLENGES = (
    ("fast", "Fast", "Shorter time for every command"),
    ("opposite", "Opposite", "Red commands: do the OPPOSITE pose"),
    ("combo", "Combo", "Two poses in a row, in order"),
)

BG = (18, 18, 34)
TARGET_COLOR = (245, 205, 110)
OPPOSITE_COLOR = (250, 120, 120)
DONE_COLOR = (110, 210, 130)
YOU_COLOR = (125, 195, 255)
DARK = (25, 25, 35)


def classify(yaw_off: float, roll_off: float) -> str | None:
    """Turn offsets from neutral into a pose id (or None when roughly neutral)."""
    yn, rn = abs(yaw_off) / YAW_THRESH, abs(roll_off) / TILT_THRESH
    if max(yn, rn) < 1.0:
        return None
    if yn >= rn:
        return "right" if yaw_off > 0 else "left"
    return "tilt_right" if roll_off > 0 else "tilt_left"


class simonsays(Minigame):
    """Copy the pose on the left with your head before the time bar empties."""

    title = "simon says"

    def __init__(self, screen: pygame.Surface, tracker: PoseTracker | None = None, *,
                 fast: bool = False, opposite: bool = False, combo: bool = False) -> None:
        super().__init__(screen)
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.big_font = pygame.font.Font(None, 72)

        self.fast, self.opposite, self.combo = fast, opposite, combo

        # Pass a shared PoseTracker in if several minigames use the camera.
        self._owns_tracker = tracker is None
        self.tracker = tracker if tracker is not None else PoseTracker()
        self.tracker.start()
        self.start()

    # ------------------------------------------------------------------ API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Turn Head", "Turn your head left or right to match the pose (or A / D)",
                   self.turn_head),
            Action("Tilt Head", "Tilt your head left or right to match the pose (or Q / E)",
                   self.tilt_head),
        )

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.elapsed = 0.0
        self.done = 0

        self.neutral_yaw: float | None = None
        self.neutral_roll = 0.0
        self.samples: list[tuple[float, float]] = []
        self.calib_time = 0.0
        self.wait_time = 0.0
        self.ready_t = 0.0
        self.mode = "calibrate" if self.tracker.available else "ready"

        self.face_visible = False
        self.current: str | None = None      # pose the player is doing right now
        self.you_yaw = self.you_roll = 0.0   # live avatar target
        self.vis_yaw = self.vis_roll = 0.0   # avatar as drawn (smoothed)
        self.sim_pose: str | None = None
        self.sim_time = 0.0

        self.flash_t = 0.0
        self.flash_word = FLASH_WORDS[0]
        self.last_required: str | None = None
        self.cmd: dict = {"required": ["left"], "shown": ["left"], "opposite": False}
        self.idx = 0
        self.hold = 0.0
        self.time_left = self.time_limit = 1.0
        self._new_command()

    def close(self) -> None:
        """Release the camera (only if this minigame created the tracker)."""
        if self._owns_tracker:
            self.tracker.stop()

    # ---------------------------------------------------------------- input
    def turn_head(self) -> None:
        self._sim("right" if self.sim_pose == "left" else "left")

    def tilt_head(self) -> None:
        self._sim("tilt_right" if self.sim_pose == "tilt_left" else "tilt_left")

    def _sim(self, pose: str) -> None:
        self.sim_pose, self.sim_time = pose, SIM_SECONDS

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_a, pygame.K_LEFT):
            self._sim("left")
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            self._sim("right")
        elif event.key == pygame.K_q:
            self._sim("tilt_left")
        elif event.key == pygame.K_e:
            self._sim("tilt_right")
        elif event.key == pygame.K_c:  # recentre: "my current pose is neutral"
            sample = self.tracker.pose if self.tracker.available else None
            if sample is not None:
                self.neutral_yaw, self.neutral_roll = sample

    # ------------------------------------------------------------- commands
    def _pose_pool(self) -> tuple[str, ...]:
        if self.tracker.available and not self.tracker.has_roll:
            return ("left", "right")  # fallback tracker can't see tilt
        return tuple(POSES)

    def _new_command(self) -> None:
        progress = min(1.0, self.done / max(1, TARGET_COMMANDS - 1))
        t0, t1 = (FAST_TIME_START, FAST_TIME_END) if self.fast else (TIME_START, TIME_END)
        base = t0 + (t1 - t0) * progress

        count = 2 if self.combo and self.done >= 1 else 1
        pool = self._pose_pool()
        required: list[str] = []
        prev = self.last_required
        for _ in range(count):
            # never ask for the pose the player is probably already in
            pick = random.choice([p for p in pool if p != prev])
            required.append(pick)
            prev = pick

        opposite = self.opposite and self.done >= 2 and random.random() < OPPOSITE_CHANCE
        shown = [OPPOSITE[p] for p in required] if opposite else list(required)

        self.cmd = {"required": required, "shown": shown, "opposite": opposite}
        self.idx = 0
        self.hold = 0.0
        self.last_required = required[-1]
        self.time_limit = base * (1 if count == 1 else count * COMBO_TIME_FACTOR)
        self.time_left = self.time_limit

    # --------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.flash_t = max(0.0, self.flash_t - dt)
        blend = min(1.0, 14.0 * dt)
        self.vis_yaw += (self.you_yaw - self.vis_yaw) * blend
        self.vis_roll += (self.you_roll - self.vis_roll) * blend

        if self.mode == "calibrate":
            self._update_calibration(dt)
            return

        self._read_pose(dt)
        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        self._check_pose(dt)

    def _update_calibration(self, dt: float) -> None:
        self.wait_time += dt
        sample = self.tracker.pose if self.tracker.available else None
        if sample is not None:
            self.samples.append(sample)
            self.calib_time += dt

        enough = self.calib_time >= CALIBRATE_SECONDS and len(self.samples) >= 10
        if enough or self.wait_time > CALIBRATE_TIMEOUT or not self.tracker.available:
            if self.samples:
                self.neutral_yaw = median(s[0] for s in self.samples)
                self.neutral_roll = median(s[1] for s in self.samples)
            self.mode = "ready"

    def _read_pose(self, dt: float) -> None:
        if self.sim_time > 0 and self.sim_pose:        # keyboard fallback
            self.sim_time -= dt
            _, self.you_yaw, self.you_roll = POSES[self.sim_pose]
            self.current = self.sim_pose
            return

        sample = self.tracker.pose if self.tracker.available else None
        self.face_visible = sample is not None
        if sample is None:
            self.current = None
            self.you_yaw *= 0.9
            self.you_roll *= 0.9
            return

        ratio, roll = sample
        if self.neutral_yaw is None:   # camera found us late: calibrate on first sight
            self.neutral_yaw, self.neutral_roll = ratio, roll
        yaw_off = (ratio - self.neutral_yaw) / self.tracker.scale
        roll_off = roll - self.neutral_roll
        self.you_yaw = max(-1.0, min(1.0, yaw_off))
        self.you_roll = max(-30.0, min(30.0, roll_off))
        self.current = classify(yaw_off, roll_off)

    def _check_pose(self, dt: float) -> None:
        required = self.cmd["required"][self.idx]
        if self.current == required:
            self.hold += dt
        else:
            self.hold = max(0.0, self.hold - 3.0 * dt)  # forgive a flicker

        if self.hold >= (FAST_HOLD_TIME if self.fast else HOLD_TIME):
            self.idx += 1
            self.hold = 0.0
            self.flash_t = FLASH_SECONDS
            self.flash_word = random.choice(FLASH_WORDS)
            if self.idx >= len(self.cmd["required"]):
                self.done += 1
                if self.done >= TARGET_COMMANDS:
                    self.finish(True)
                else:
                    self._new_command()
            return

        self.time_left -= dt
        if self.time_left <= 0.0:
            self.time_left = 0.0
            self.finish(False)

    # ----------------------------------------------------------------- draw
    def _draw_face(self, screen: pygame.Surface, cx: int, cy: int, r: int,
                   yaw: float, roll: float, color: tuple[int, int, int]) -> None:
        """Cartoon head. yaw -1..1 shifts the features, roll tilts the whole head."""
        a = math.radians(roll)
        ca, sa = math.cos(a), math.sin(a)

        def pt(x: float, y: float) -> tuple[int, int]:
            px, py = x * r, y * r
            return int(cx + px * ca - py * sa), int(cy + px * sa + py * ca)

        shift = 0.38 * yaw
        pygame.draw.polygon(screen, DARK, [pt(-0.14, -0.96), pt(0.0, -1.28), pt(0.14, -0.96)])
        pygame.draw.circle(screen, color, (cx, cy), r)
        pygame.draw.circle(screen, DARK, (cx, cy), r, 4)
        for side in (-1, 1):
            ex, ey = pt(side * 0.35 + shift, -0.18)
            pygame.draw.circle(screen, DARK, (ex, ey), max(3, int(r * 0.13 * (1 + 0.3 * side * yaw))))
        nx, ny = pt(shift * 1.5, 0.08)
        pygame.draw.circle(screen, DARK, (nx, ny), max(3, int(r * 0.07)))
        mouth = [pt(shift + x * 0.3, 0.42 + 0.10 * (1 - x * x)) for x in (-1, -0.5, 0, 0.5, 1)]
        pygame.draw.lines(screen, DARK, False, mouth, max(2, int(r * 0.04)))

    def _text(self, screen: pygame.Surface, font: pygame.font.Font, text: str,
              color: tuple[int, int, int], center: tuple[int, int]) -> None:
        surf = font.render(text, True, color)
        screen.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        screen.fill(BG)
        self._draw_hud(screen, w, h)

        if self.mode == "calibrate":
            self._text(screen, self.font, "Look straight at the camera...", (240, 240, 240),
                       (w // 2, h // 2 - 60))
            frac = min(1.0, self.calib_time / CALIBRATE_SECONDS)
            pygame.draw.rect(screen, (50, 50, 60), (w // 2 - 120, h // 2 - 20, 240, 12), border_radius=4)
            pygame.draw.rect(screen, DONE_COLOR, (w // 2 - 120, h // 2 - 20, int(240 * frac), 12),
                             border_radius=4)
            return

        lx, rx, cy = int(w * 0.29), int(w * 0.72), 270

        # --- you ---
        required = self.cmd["required"][min(self.idx, len(self.cmd["required"]) - 1)]
        matching = self.mode == "play" and self.current == required
        self._draw_face(screen, rx, cy, 100, self.vis_yaw, self.vis_roll, YOU_COLOR)
        if matching:
            pygame.draw.circle(screen, DONE_COLOR, (rx, cy), 112, 6)
        self._text(screen, self.font, "YOU", (200, 200, 210), (rx, cy + 135))

        if self.mode == "ready":
            self._text(screen, self.big_font, "GET READY!", (240, 240, 240), (lx + 40, cy))
            return

        # --- target pose(s) ---
        shown, count = self.cmd["shown"], len(self.cmd["shown"])
        opposite = self.cmd["opposite"]
        radius = 100 if count == 1 else 72
        for i, pose in enumerate(shown):
            x = lx if count == 1 else lx - 85 + i * 170
            _, yaw, roll = POSES[pose]
            if i < self.idx:
                color = DONE_COLOR
            else:
                color = OPPOSITE_COLOR if opposite else TARGET_COLOR
            self._draw_face(screen, x, cy, radius, yaw, roll, color)
            if i == self.idx:
                pygame.draw.circle(screen, (255, 255, 255), (x, cy), radius + 12, 4)
        labels = "  >  ".join(POSES[p][0] for p in shown)
        self._text(screen, self.font, labels, OPPOSITE_COLOR if opposite else (240, 240, 240),
                   (lx, cy + 135))

        if opposite and int(self.elapsed * 6) % 2 == 0:
            self._text(screen, self.big_font, "DO THE OPPOSITE!", (255, 90, 90), (w // 2, 85))

        # "=" between the faces, slashed out when it's an opposite command
        mx = (lx + rx) // 2
        pygame.draw.line(screen, (230, 230, 230), (mx - 25, cy - 10), (mx + 25, cy - 10), 5)
        pygame.draw.line(screen, (230, 230, 230), (mx - 25, cy + 10), (mx + 25, cy + 10), 5)
        if opposite:
            pygame.draw.line(screen, (255, 90, 90), (mx - 30, cy + 32), (mx + 30, cy - 32), 6)

        # --- hold meter under you, time bar along the bottom ---
        need = FAST_HOLD_TIME if self.fast else HOLD_TIME
        pygame.draw.rect(screen, (50, 50, 60), (rx - 80, cy + 160, 160, 10), border_radius=4)
        pygame.draw.rect(screen, DONE_COLOR, (rx - 80, cy + 160, int(160 * min(1.0, self.hold / need)), 10),
                         border_radius=4)

        frac = max(0.0, self.time_left / self.time_limit)
        bar_color = DONE_COLOR if frac > 0.5 else (240, 180, 60) if frac > 0.25 else (235, 70, 70)
        bx, by, bw, bh = 120, h - 62, w - 240, 26
        pygame.draw.rect(screen, (50, 50, 60), (bx, by, bw, bh), border_radius=8)
        pygame.draw.rect(screen, bar_color, (bx, by, int(bw * frac), bh), border_radius=8)

        if self.flash_t > 0:
            self._text(screen, self.big_font, self.flash_word, DONE_COLOR, (rx, cy - 140))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        screen.blit(self.font.render(f"{self.done} / {TARGET_COMMANDS}", True, (240, 240, 240)), (10, 10))

        preview = self.tracker.preview_surface() if self.tracker.available else None
        if preview is not None:
            pw, ph = preview.get_size()
            pos = (w - pw - 10, 10)
            screen.blit(preview, pos)
            pygame.draw.rect(screen, (200, 200, 200), (*pos, pw, ph), 2)

        if self.tracker.available:
            info = f"Pose tracking: {self.tracker.backend}   (C = recentre)"
        else:
            info = "No camera tracking - keyboard: A/D turn, Q/E tilt"
        screen.blit(self.small_font.render(info, True, (140, 140, 160)), (10, h - 26))

        tags = [label.upper() for attr, label, _ in CHALLENGES if getattr(self, attr)]
        if tags:
            tag = self.small_font.render("  ".join(tags), True, (240, 180, 60))
            screen.blit(tag, (10, 40))

        if self.mode != "calibrate" and self.tracker.available and not self.face_visible:
            self._text(screen, self.font, "Face lost!", (255, 160, 60), (w // 2, 40))


# =============================================================================
# Demo runner
# =============================================================================
def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((960, 540))
    pygame.display.set_caption("simon says")
    clock = pygame.time.Clock()
    title_font = pygame.font.Font(None, 96)
    font = pygame.font.Font(None, 36)
    small = pygame.font.Font(None, 28)
    keys = (pygame.K_1, pygame.K_2, pygame.K_3)

    game = simonsays(screen)
    state = "menu"
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif state == "menu" and event.type == pygame.KEYDOWN:
                if event.key in keys:
                    attr = CHALLENGES[keys.index(event.key)][0]
                    setattr(game, attr, not getattr(game, attr))
                elif event.key == pygame.K_SPACE:
                    game.start()
                    state = "playing"
            elif state == "playing" and game.finished:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    state = "menu"
            else:
                game.handle_event(event)

        if state == "menu":
            screen.fill(BG)
            title = title_font.render("simon says", True, (245, 205, 110))
            screen.blit(title, (60, 50))
            screen.blit(font.render("Copy the head pose before the bar empties.", True, (230, 230, 230)), (64, 130))
            for i, (attr, label, desc) in enumerate(CHALLENGES):
                on = getattr(game, attr)
                row = f"[{i + 1}] {label}: {desc}   {'ON' if on else 'off'}"
                screen.blit(small.render(row, True, (110, 210, 130) if on else (150, 150, 165)),
                            (64, 210 + i * 42))
            screen.blit(font.render("Press SPACE to start", True, (125, 195, 255)), (64, 400))
            preview = game.tracker.preview_surface() if game.tracker.available else None
            if preview is not None:
                screen.blit(pygame.transform.scale(preview, (320, 240)), (600, 190))
            else:
                screen.blit(small.render("No camera: use A/D and Q/E", True, (150, 150, 165)), (600, 190))
        else:
            game.update(dt)
            game.draw(screen)
            if game.finished:
                shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
                shade.fill((0, 0, 0, 150))
                screen.blit(shade, (0, 0))
                msg, col = ("YOU MATCHED THEM ALL!", (110, 210, 130)) if game.won else ("TOO SLOW!", (240, 70, 70))
                text = title_font.render(msg, True, col)
                hint = font.render("Press SPACE for the menu", True, (230, 230, 230))
                cx, cy = screen.get_width() // 2, screen.get_height() // 2
                screen.blit(text, (cx - text.get_width() // 2, cy - 60))
                screen.blit(hint, (cx - hint.get_width() // 2, cy + 20))

        pygame.display.flip()

    game.close()
    pygame.quit()


if __name__ == "__main__":
    main()