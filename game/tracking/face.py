"""Head pose tracking: yaw ratio (~0.5 facing forward) and roll in degrees.

Backends, best first: MediaPipe FaceMesh -> MediaPipe FaceLandmarker -> OpenCV Haar.
Roll is positive when the head tilts toward the right of the screen (mirrored view).
"""

from __future__ import annotations

import math
import os
import time

import cv2
import numpy as np

from game.tracking.camera import MODELS_DIR, CameraTracker, ensure_model, mp

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_PATH = os.path.join(MODELS_DIR, "face_landmarker.task")

NOSE_TIP, CHEEK_A, CHEEK_B = 1, 234, 454   # FaceMesh landmark ids


class FaceTracker(CameraTracker):
    label = "Face tracking"

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__(camera_index)
        self.scale = 0.14  # yaw-ratio change that maps to "full turn"

        self._ratio: float | None = None
        self._roll = 0.0
        self._pose_time = 0.0

        self._mesh = None
        self._landmarker = None
        self._cascade = None

    # Backend setup and detection
    def _setup(self) -> bool:
        ok = self._init_mesh() or self._init_tasks() or self._init_haar()
        if ok and not self.has_roll:
            print("  (no MediaPipe: head tilt can't be detected, only left/right poses are used)")
        return ok

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
            path = ensure_model(FACE_MODEL_URL, FACE_MODEL_PATH, "face")
            options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=path),
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

    def _teardown(self) -> None:
        for detector in (self._mesh, self._landmarker):
            if detector is not None:
                detector.close()
        self._mesh = self._landmarker = None

    # Measure from detections
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

    def _process(self, frame_bgr):
        ratio, roll, marks = self._measure(frame_bgr)
        if ratio is not None:
            now = time.time()
            with self._lock:
                fresh = self._ratio is not None and self._is_fresh(self._pose_time, now)
                self._ratio = self._blend(self._ratio, ratio, fresh)
                self._roll = self._blend(self._roll, roll, fresh)
                self._pose_time = now
        return marks

    # Read tracked values
    @property
    def has_roll(self) -> bool:
        """False for the Haar fallback, which can't measure head tilt."""
        return self.backend in ("mediapipe-mesh", "mediapipe-tasks")

    @property
    def pose(self) -> tuple[float, float] | None:
        """Smoothed (yaw_ratio, roll_degrees), or None if no face seen recently."""
        with self._lock:
            if self._ratio is None or not self._is_fresh(self._pose_time):
                return None
            return self._ratio, self._roll
