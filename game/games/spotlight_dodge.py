"""Dodge the Spotlight: turn your head to slide left/right and stay in the shadow.

Single-file minigame (camera head tracking + game + demo runner).

Install:  uv add pygame opencv-python mediapipe numpy
Try it:   python -m game.games.spotlight_dodge      (run from the project root)

In the demo: SPACE = restart, C = recentre head, Esc = quit. Keyboard fallback: A/D or arrows.
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
# Head tracking (background thread; MediaPipe mesh -> MediaPipe tasks -> OpenCV Haar)
# =============================================================================
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")

# FaceMesh landmark ids: nose tip and the two outer cheek points.
NOSE_TIP, CHEEK_A, CHEEK_B = 1, 234, 454

STALE_SECONDS = 0.5      # no face for this long -> ratio becomes None
SMOOTHING = 0.5          # 0..1, higher = snappier, lower = smoother
PREVIEW_SIZE = (160, 120)


class HeadTracker:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.backend: str | None = None
        self.error: str | None = MP_ERROR
        self.scale = 0.14  # ratio change that maps to "full left/right"

        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._ratio: float | None = None
        self._ratio_time = 0.0
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
            print("Head tracking: OFF -", self.error)
            return
        self._cap = cap
        if not (self._init_mesh() or self._init_tasks() or self._init_haar()):
            print("Head tracking: OFF -", self.error)
            print("Python being used:", sys.executable)
            cap.release()
            self._cap = None
            return
        print(f"Head tracking: ON ({self.backend} backend)")
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
    def _mesh_ratio(pts):
        """Nose position between the cheek edges: ~0.5 facing forward."""
        a, b = pts[CHEEK_A].x, pts[CHEEK_B].x
        lo, hi = min(a, b), max(a, b)
        if hi - lo < 1e-4:
            return None, []
        marks = [(pts[i].x, pts[i].y) for i in (NOSE_TIP, CHEEK_A, CHEEK_B)]
        return (pts[NOSE_TIP].x - lo) / (hi - lo), marks

    def _measure(self, frame_bgr):
        """Returns (ratio or None, [normalised (x, y) marks for the preview])."""
        if self.backend == "opencv-haar":
            h, w = frame_bgr.shape[:2]
            small_w = 320
            small_h = int(h * small_w / w)
            gray = cv2.cvtColor(cv2.resize(frame_bgr, (small_w, small_h)), cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
            if len(faces) == 0:
                return None, []
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            cx, cy = (x + fw / 2) / small_w, (y + fh / 2) / small_h
            return cx, [(cx, cy)]

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.backend == "mediapipe-mesh":
            res = self._mesh.process(rgb)
            if not res.multi_face_landmarks:
                return None, []
            return self._mesh_ratio(res.multi_face_landmarks[0].landmark)

        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect(img)
        if not res.face_landmarks:
            return None, []
        return self._mesh_ratio(res.face_landmarks[0])

    def _loop(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror: turning right moves you right
            try:
                ratio, marks = self._measure(frame)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                ratio, marks = None, []

            small = cv2.resize(frame, PREVIEW_SIZE)
            for mx, my in marks:
                cv2.circle(small, (int(mx * PREVIEW_SIZE[0]), int(my * PREVIEW_SIZE[1])),
                           3, (0, 255, 0), -1)
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()

            now = time.time()
            with self._lock:
                if ratio is not None:
                    fresh = self._ratio is not None and now - self._ratio_time < STALE_SECONDS
                    self._ratio = (self._ratio * (1 - SMOOTHING) + ratio * SMOOTHING) if fresh else ratio
                    self._ratio_time = now
                self._preview = preview

    # ------------------------------------------------------------ accessors
    @property
    def available(self) -> bool:
        return self._running and self.backend is not None

    @property
    def ratio(self) -> float | None:
        """Smoothed head ratio, or None if no face has been seen recently."""
        with self._lock:
            if self._ratio is None or time.time() - self._ratio_time > STALE_SECONDS:
                return None
            return self._ratio

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
SURVIVE_SECONDS = 15.0

# Control
CALIBRATE_SECONDS = 1.2     # time spent looking straight ahead to set "centre"
CALIBRATE_TIMEOUT = 5.0     # give up waiting for a face after this long
DEAD_ZONE = 0.08            # ignore tiny head movements (fraction of full turn)
PLAYER_SPEED = 2.2          # max player speed, screen-widths per second
KEY_STEP = 0.25             # keyboard fallback: screen fraction per key press
EDGE_MARGIN = 0.04
PLAYER_HALF_W = 16

# Searchlight
BEAM_HALF_W = 0.11          # beam half-width, fraction of screen width
WARN_SECONDS = 0.9
EXPOSURE_UP_TIME = 0.22     # seconds in light before you're caught
EXPOSURE_DOWN_TIME = 0.6    # seconds to cool down when back in shadow

BG = (12, 14, 26)
FLOOR = (28, 30, 46)


class SpotlightDodge(Minigame):
    """A searchlight sweeps in from an edge. Stay in shadow for 15 seconds."""

    title = "Dodge the Spotlight"

    def __init__(self, screen: pygame.Surface, tracker: HeadTracker | None = None) -> None:
        super().__init__(screen)
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.big_font = pygame.font.Font(None, 56)
        self._overlay: pygame.Surface | None = None

        # Pass a shared HeadTracker in if several minigames use the camera.
        self._owns_tracker = tracker is None
        self.tracker = tracker if tracker is not None else HeadTracker()
        self.tracker.start()
        self.start()

    # ------------------------------------------------------------------ API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Lean Left", "Turn your head left to slide left (or A / Left)", self.move_left),
            Action("Lean Right", "Turn your head right to slide right (or D / Right)", self.move_right),
        )

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.elapsed = 0.0

        self.player_u = 0.5     # player position, 0..1 across the screen
        self.target_u = 0.5
        self.neutral: float | None = None
        self.samples: list[float] = []
        self.calib_time = 0.0
        self.wait_time = 0.0
        self.face_visible = False
        self.mode = "calibrate" if self.tracker.available else "play"

        self.light_phase = "idle"   # idle -> warn -> sweep -> idle ...
        self.light_t = 0.0
        self.idle_dur = 0.8
        self.side = -1              # -1: enters from left, +1: from right
        self.reach = 0.6            # how far the leading edge gets (0..1)
        self.sweep_dur = 2.4
        self.beam_u: float | None = None
        self.exposure = 0.0
        self.lit = False

    def close(self) -> None:
        """Release the camera (only if this minigame created the tracker)."""
        if self._owns_tracker:
            self.tracker.stop()

    # ---------------------------------------------------------------- input
    def move_left(self) -> None:
        self.target_u = max(0.0, self.target_u - KEY_STEP)

    def move_right(self) -> None:
        self.target_u = min(1.0, self.target_u + KEY_STEP)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        left, right = self.actions
        if event.key in (pygame.K_a, pygame.K_LEFT):
            left.perform()
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            right.perform()
        elif event.key == pygame.K_c:  # recentre: "my current pose is straight ahead"
            ratio = self.tracker.ratio if self.tracker.available else None
            if ratio is not None:
                self.neutral = ratio

    # --------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        if self.finished:
            return

        if self.mode == "calibrate":
            self._update_calibration(dt)
            self._move_player(dt)
            return

        self.elapsed += dt
        self._update_control()
        self._move_player(dt)
        self._update_light(dt)
        self._update_exposure(dt)

        if self.exposure >= 1.0:
            self.finish(False)
        elif self.elapsed >= SURVIVE_SECONDS:
            self.finish(True)

    def _update_calibration(self, dt: float) -> None:
        self.wait_time += dt
        ratio = self.tracker.ratio if self.tracker.available else None
        if ratio is not None:
            self.samples.append(ratio)
            self.calib_time += dt

        done = self.calib_time >= CALIBRATE_SECONDS and len(self.samples) >= 10
        if done or self.wait_time > CALIBRATE_TIMEOUT or not self.tracker.available:
            if self.samples:
                self.neutral = median(self.samples)
            self.mode = "play"

    def _update_control(self) -> None:
        ratio = self.tracker.ratio if self.tracker.available else None
        self.face_visible = ratio is not None
        if ratio is None:
            return  # face lost (or keyboard only): keep current target
        if self.neutral is None:
            self.neutral = ratio  # camera found us late: calibrate on first sight
        off = max(-1.0, min(1.0, (ratio - self.neutral) / self.tracker.scale))
        if abs(off) < DEAD_ZONE:
            off = 0.0
        else:
            off = math.copysign((abs(off) - DEAD_ZONE) / (1 - DEAD_ZONE), off)
        self.target_u = 0.5 + 0.5 * off

    def _move_player(self, dt: float) -> None:
        target = max(EDGE_MARGIN, min(1 - EDGE_MARGIN, self.target_u))
        delta = (target - self.player_u) * min(1.0, 14.0 * dt)
        step = PLAYER_SPEED * dt
        self.player_u += max(-step, min(step, delta))

    def _begin_warn(self) -> None:
        progress = min(1.0, self.elapsed / SURVIVE_SECONDS)
        # Usually enter from the side the player is on, forcing them to cross.
        on_side = -1 if self.player_u < 0.5 else 1
        self.side = on_side if random.random() < 0.7 else -on_side
        self.reach = random.uniform(0.50 + 0.10 * progress, 0.68 + 0.12 * progress)
        self.sweep_dur = 2.4 - 0.7 * progress
        self.light_phase = "warn"
        self.light_t = 0.0

    def _update_light(self, dt: float) -> None:
        self.light_t += dt
        if self.light_phase == "idle":
            self.beam_u = None
            if self.light_t >= self.idle_dur:
                self._begin_warn()
        elif self.light_phase == "warn":
            if self.light_t >= WARN_SECONDS:
                self.light_phase, self.light_t = "sweep", 0.0
        else:
            p = self.light_t / self.sweep_dur
            if p >= 1.0:
                self.light_phase, self.light_t = "idle", 0.0
                self.idle_dur = random.uniform(0.4, 0.8)
                self.beam_u = None
            else:
                lead = self.reach * math.sin(math.pi * p)  # out and back
                if self.side < 0:
                    self.beam_u = lead - BEAM_HALF_W
                else:
                    self.beam_u = 1.0 - lead + BEAM_HALF_W

    def _update_exposure(self, dt: float) -> None:
        w = self.screen.get_width()
        self.lit = (
            self.beam_u is not None
            and abs(self.player_u * w - self.beam_u * w) < BEAM_HALF_W * w + PLAYER_HALF_W * 0.5
        )
        if self.lit:
            self.exposure = min(1.0, self.exposure + dt / EXPOSURE_UP_TIME)
        else:
            self.exposure = max(0.0, self.exposure - dt / EXPOSURE_DOWN_TIME)

    # ----------------------------------------------------------------- draw
    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        ground_y = h - 110
        screen.fill(BG)
        pygame.draw.rect(screen, FLOOR, (0, ground_y + 40, w, h - ground_y - 40))

        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay = self._overlay
        overlay.fill((0, 0, 0, 0))

        playing = self.mode == "play"
        if playing and self.light_phase in ("warn", "sweep"):
            zone_w = int(self.reach * w)
            x0 = 0 if self.side < 0 else w - zone_w
            alpha = 35
            if self.light_phase == "warn":
                alpha += int(25 * math.sin(self.light_t * 10))
            pygame.draw.rect(overlay, (255, 40, 40, alpha), (x0, 0, zone_w, h))

        if self.beam_u is not None:
            cx, hw = int(self.beam_u * w), int(BEAM_HALF_W * w)
            floor_c = ground_y + 55
            top = ground_y - 40
            pygame.draw.polygon(overlay, (255, 248, 200, 70), [
                (cx - 14, 0), (cx + 14, 0), (cx + hw, top),
                (cx + hw, floor_c), (cx - hw, floor_c), (cx - hw, top)])
            pygame.draw.ellipse(overlay, (255, 250, 210, 130), (cx - hw, floor_c - 30, 2 * hw, 60))
        screen.blit(overlay, (0, 0))

        if playing and self.light_phase == "warn":
            self._draw_warning(screen, w, h)
        self._draw_player(screen, ground_y, w)
        self._draw_hud(screen, w, h)

    def _draw_warning(self, screen: pygame.Surface, w: int, h: int) -> None:
        if int(self.light_t * 8) % 2:
            return
        for i in range(3):
            if self.side < 0:
                x = 20 + i * 26
                pts = [(x, h // 2 - 20), (x + 20, h // 2), (x, h // 2 + 20)]
            else:
                x = w - 20 - i * 26
                pts = [(x, h // 2 - 20), (x - 20, h // 2), (x, h // 2 + 20)]
            pygame.draw.polygon(screen, (255, 90, 90), pts)
        text = "SEARCHLIGHT FROM THE " + ("LEFT" if self.side < 0 else "RIGHT")
        surf = self.font.render(text, True, (255, 120, 120))
        screen.blit(surf, ((w - surf.get_width()) // 2, 60))

    def _draw_player(self, screen: pygame.Surface, ground_y: int, w: int) -> None:
        px = int(self.player_u * w)
        e = self.exposure
        color = (80 + int(175 * e), 200 - int(130 * e), 120 - int(80 * e))
        pygame.draw.ellipse(screen, (6, 6, 10), (px - 24, ground_y + 22, 48, 14))
        pygame.draw.rect(screen, color, (px - PLAYER_HALF_W, ground_y - 14, PLAYER_HALF_W * 2, 44),
                         border_radius=8)
        pygame.draw.circle(screen, color, (px, ground_y - 30), 14)

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        remaining = max(0.0, SURVIVE_SECONDS - self.elapsed)
        screen.blit(self.font.render(f"{remaining:.1f}s", True, (240, 240, 240)), (10, 10))

        # detection meter
        bx, by, bw, bh = w // 2 - 100, 14, 200, 12
        pygame.draw.rect(screen, (50, 50, 60), (bx, by, bw, bh), border_radius=4)
        pygame.draw.rect(screen, (230, 60, 60), (bx, by, int(bw * self.exposure), bh), border_radius=4)
        label = self.small_font.render("DETECTION", True, (200, 200, 200))
        screen.blit(label, (w // 2 - label.get_width() // 2, by + bh + 4))

        # camera preview
        preview = self.tracker.preview_surface() if self.tracker.available else None
        if preview is not None:
            pw, ph = preview.get_size()
            pos = (w - pw - 10, 10)
            screen.blit(preview, pos)
            pygame.draw.rect(screen, (200, 200, 200), (*pos, pw, ph), 2)

        if self.tracker.available:
            info = f"Head tracking: {self.tracker.backend}   (C = recentre)"
        else:
            info = "No camera tracking - keyboard: A/D or arrows"
        screen.blit(self.small_font.render(info, True, (140, 140, 160)), (10, h - 28))

        if self.mode == "calibrate":
            text = self.font.render("Look straight at the camera...", True, (240, 240, 240))
            screen.blit(text, ((w - text.get_width()) // 2, h // 2 - 80))
            frac = min(1.0, self.calib_time / CALIBRATE_SECONDS)
            pygame.draw.rect(screen, (50, 50, 60), (w // 2 - 120, h // 2 - 40, 240, 12), border_radius=4)
            pygame.draw.rect(screen, (80, 200, 120),
                             (w // 2 - 120, h // 2 - 40, int(240 * frac), 12), border_radius=4)
        elif self.tracker.available and not self.face_visible:
            text = self.font.render("Face lost!", True, (255, 160, 60))
            screen.blit(text, ((w - text.get_width()) // 2, h // 2 - 20))


# =============================================================================
# Demo runner
# =============================================================================
def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((960, 540))
    pygame.display.set_caption("Dodge the Spotlight")
    clock = pygame.time.Clock()
    big = pygame.font.Font(None, 80)
    small = pygame.font.Font(None, 32)

    game = SpotlightDodge(screen)
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE and game.finished:
                game.start()
            else:
                game.handle_event(event)

        game.update(dt)
        game.draw(screen)

        if game.finished:
            shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 150))
            screen.blit(shade, (0, 0))
            msg, col = ("YOU SURVIVED!", (90, 230, 120)) if game.won else ("CAUGHT!", (240, 70, 70))
            text = big.render(msg, True, col)
            hint = small.render("Press SPACE to play again", True, (230, 230, 230))
            cx, cy = screen.get_width() // 2, screen.get_height() // 2
            screen.blit(text, (cx - text.get_width() // 2, cy - 50))
            screen.blit(hint, (cx - hint.get_width() // 2, cy + 20))

        pygame.display.flip()

    game.close()
    pygame.quit()


if __name__ == "__main__":
    main()
