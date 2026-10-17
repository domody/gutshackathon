"""Eye-state camera tracker: how closed are the player's eyes right now?

Same shape as the other trackers (start / stop / available / backend / preview_surface),
so a Minigame can use it through `tracker_cls = EyeTracker`.

Reading the result:
    tracker.closed_for(0)   # 0.0 = wide open .. 1.0 = shut, or None if no face seen lately
    tracker.closed_for(1)   # second face (left-to-right on screen), if num_faces=2

Start-up is non-blocking: the camera opens on the calling (main) thread, but the face model
is downloaded/loaded on the background thread, so the game window never freezes. Until the
model is ready `closed_for` returns None and `backend` is None.

When game/tracking.py exists, move this class there (subclass CameraTracker).
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass

import cv2
import numpy as np
import pygame

try:
    import mediapipe as mp
    MP_ERROR = None
except Exception as exc:  # keep the real reason so it can be reported
    mp = None
    MP_ERROR = repr(exc)

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")

# FaceMesh landmark ids. Each eye: (outer corner, inner corner, top1, bottom1, top2, bottom2).
RIGHT_EYE = (33, 133, 159, 145, 158, 153)
LEFT_EYE = (263, 362, 386, 374, 385, 380)
NOSE_TIP = 1

# Eye aspect ratio (EAR) range mapped onto a 0..1 "closed score" (used when blendshapes are missing).
EAR_OPEN, EAR_CLOSED = 0.28, 0.14

STALE_SECONDS = 0.5      # no face for this long -> reading disappears
SMOOTHING = 0.6          # 0..1, higher = snappier, lower = smoother
PREVIEW_SIZE = (160, 120)


@dataclass
class EyeReading:
    """One tracked face. closed: 0.0 = wide open, 1.0 = fully closed. x: nose x (0..1, mirrored)."""
    closed: float
    x: float


def _ear_closed_score(pts, width: int, height: int) -> float:
    """Closed score (0..1) from landmark geometry: small eye-height / eye-width ratio = closed."""
    ears = []
    for outer, inner, top1, bot1, top2, bot2 in (RIGHT_EYE, LEFT_EYE):
        def dist(a: int, b: int) -> float:
            return math.hypot((pts[a].x - pts[b].x) * width, (pts[a].y - pts[b].y) * height)
        horizontal = dist(outer, inner)
        if horizontal < 1e-6:
            return 0.0
        ears.append((dist(top1, bot1) + dist(top2, bot2)) / (2.0 * horizontal))
    ear = sum(ears) / len(ears)
    return max(0.0, min(1.0, (EAR_OPEN - ear) / (EAR_OPEN - EAR_CLOSED)))


class EyeTracker:
    """Reads the webcam on a background thread and reports how closed each face's eyes are."""

    def __init__(self, camera_index: int = 0, num_faces: int = 1) -> None:
        self.camera_index = camera_index
        self.num_faces = num_faces
        self.backend: str | None = None     # set once the model is loaded
        self.error: str | None = MP_ERROR

        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._failed = False
        self._lock = threading.Lock()
        self._readings: list[EyeReading] = []
        self._readings_time = 0.0
        self._preview: bytes | None = None

        self._mesh = None
        self._landmarker = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running:
            return
        # Open the camera on the calling (main) thread: macOS wants that.
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            self.error = "could not open webcam"
            self._failed = True
            print("Eye tracking: OFF -", self.error)
            return
        self._cap = cap
        self._failed = False
        self._running = True
        # Model download/loading happens on the thread so the window stays responsive.
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _run(self) -> None:
        if not (self._init_tasks() or self._init_mesh()):
            print("Eye tracking: OFF -", self.error)
            print("Python being used:", sys.executable)
            self._failed = True
            self._running = False
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            return
        print(f"Eye tracking: ON ({self.backend} backend)")
        self._loop()

    # ------------------------------------------------------------- backends
    def _init_tasks(self) -> bool:
        """Preferred: FaceLandmarker with blendshapes (eyeBlinkLeft / eyeBlinkRight scores)."""
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
                num_faces=self.num_faces,
                output_face_blendshapes=True,
                running_mode=vision.RunningMode.IMAGE)
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
            self.backend = "mediapipe-tasks"
            return True
        except Exception as exc:
            self.error = f"FaceLandmarker failed: {exc!r}"
            return False

    def _init_mesh(self) -> bool:
        """Fallback: legacy FaceMesh, eye openness estimated from landmark geometry (EAR)."""
        if mp is None:
            return False
        try:
            self._mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=self.num_faces, refine_landmarks=False,
                min_detection_confidence=0.5, min_tracking_confidence=0.5)
            self.backend = "mediapipe-mesh"
            return True
        except Exception as exc:
            self.error = f"legacy FaceMesh unavailable: {exc!r}"
            return False

    # ---------------------------------------------------------- measurement
    @staticmethod
    def _blendshape_closed_score(categories) -> float | None:
        scores = {c.category_name: c.score for c in categories}
        if "eyeBlinkLeft" not in scores or "eyeBlinkRight" not in scores:
            return None
        return (scores["eyeBlinkLeft"] + scores["eyeBlinkRight"]) / 2.0

    def _measure(self, frame_bgr):
        """Returns [(nose_x, closed_score, [normalised (x, y) marks for the preview]), ...]."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        faces = []
        if self.backend == "mediapipe-mesh":
            res = self._mesh.process(rgb)
            for lm in (res.multi_face_landmarks or []):
                faces.append((lm.landmark, None))
        else:
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = self._landmarker.detect(img)
            for i, pts in enumerate(res.face_landmarks):
                shapes = res.face_blendshapes[i] if i < len(res.face_blendshapes) else []
                faces.append((pts, self._blendshape_closed_score(shapes)))

        out = []
        for pts, closed in faces:
            if closed is None:  # no blendshapes available: use landmark geometry
                closed = _ear_closed_score(pts, w, h)
            marks = [(pts[i].x, pts[i].y) for i in RIGHT_EYE + LEFT_EYE]
            out.append((pts[NOSE_TIP].x, closed, marks))
        return out

    def _loop(self) -> None:
        while self._running:
            cap = self._cap
            if cap is None:
                break
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror: your left on screen is your left
            try:
                faces = self._measure(frame)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                faces = []
            faces = sorted(faces, key=lambda f: f[0])[: self.num_faces]  # left-to-right = player order

            small = cv2.resize(frame, PREVIEW_SIZE)
            for _, _, marks in faces:
                for mx, my in marks:
                    cv2.circle(small, (int(mx * PREVIEW_SIZE[0]), int(my * PREVIEW_SIZE[1])),
                               1, (0, 255, 0), -1)
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()

            now = time.time()
            with self._lock:
                fresh = bool(self._readings) and now - self._readings_time < STALE_SECONDS
                new = []
                for i, (x, closed, _) in enumerate(faces):
                    if fresh and i < len(self._readings):
                        closed = self._readings[i].closed * (1 - SMOOTHING) + closed * SMOOTHING
                    new.append(EyeReading(closed, x))
                self._readings = new
                if new:
                    self._readings_time = now
                self._preview = preview

    # ------------------------------------------------------------ accessors
    @property
    def available(self) -> bool:
        """True once the camera is open and has not failed (the model may still be loading)."""
        return self._cap is not None and not self._failed

    def closed_for(self, index: int) -> float | None:
        """Smoothed closed score (0 open .. 1 closed) for player `index`, or None if no face seen lately."""
        with self._lock:
            if index >= len(self._readings) or time.time() - self._readings_time > STALE_SECONDS:
                return None
            return self._readings[index].closed

    def preview_surface(self) -> pygame.Surface | None:
        """Small mirrored camera image with tracking dots, for on-screen display."""
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, PREVIEW_SIZE, "RGB")
