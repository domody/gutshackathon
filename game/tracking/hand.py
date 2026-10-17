"""Hand tracking: index-fingertip position, thumb-index pinch and open palm / fist (MediaPipe)."""

from __future__ import annotations

import math
import os
import time
from collections import Counter, deque

import cv2
import numpy as np

from game.tracking.camera import MODELS_DIR, CameraTracker, ensure_model, mp

HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
HAND_MODEL_PATH = os.path.join(MODELS_DIR, "hand_landmarker.task")

# Hand landmark IDs used by MediaPipe.
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP = 0, 4, 8, 9

PINCH_ON = 0.30  # Thumb-index gap divided by palm size required to start a pinch.
PINCH_OFF = 0.45  # Larger release threshold prevents the pinch reading from flickering.
FRAME_MARGIN = 0.01  # Camera border excluded when mapping hand position to the screen.

# Each finger uses (fingertip ID, knuckle ID, extension ratio); straight fingers are near 1.0 and curled fingers near 0.4.
FINGERS = ((8, 5, 0.80), (12, 9, 0.85), (16, 13, 0.80), (20, 17, 0.62))
CURLED_RATIO = 0.55
VOTE_FRAMES = 5  # Require a gesture in 3 of 5 frames to reduce flicker.
VOTES_NEEDED = 3


def classify_gesture(pts, w: int, h: int) -> str | None:
    """'palm', 'fist', or None when the hand is ambiguous (mid-transition)."""
    def dist(a, b):
        return math.hypot((a.x - b.x) * w, (a.y - b.y) * h)

    palm_size = dist(pts[WRIST], pts[MIDDLE_MCP])
    if palm_size < 1e-3:
        return None
    extended = curled = 0
    for tip, knuckle, threshold in FINGERS:
        ratio = dist(pts[tip], pts[knuckle]) / palm_size
        extended += ratio > threshold
        curled += ratio < CURLED_RATIO
    if extended >= 4 or (extended == 3 and curled == 0):
        return "palm"
    if curled >= 3 and extended == 0:
        return "fist"
    return None


class HandTracker(CameraTracker):
    label = "Hand tracking"
    stale_seconds = 0.4
    smoothing = 0.4

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__(camera_index)
        self._landmarker = None
        self._pos: tuple[float, float] | None = None
        self._pinch = False
        self._time = 0.0
        self._votes: deque = deque(maxlen=VOTE_FRAMES)
        self._gesture: str | None = None
        self._gesture_time = 0.0

    def _setup(self) -> bool:
        if mp is None:
            return False
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            path = ensure_model(HAND_MODEL_URL, HAND_MODEL_PATH, "hand")
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=path),
                num_hands=1,
                running_mode=vision.RunningMode.IMAGE)
            self._landmarker = vision.HandLandmarker.create_from_options(options)
            self.backend = "mediapipe-hand"
            return True
        except Exception as exc:
            self.error = f"HandLandmarker failed: {exc!r}"
            return False

    def _teardown(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def _process(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect(img)
        if not res.hand_landmarks:
            self._vote(None)
            return []
        pts = res.hand_landmarks[0]
        h, w = frame_bgr.shape[:2]
        self._vote(classify_gesture(pts, w, h))
        palm = math.dist((pts[WRIST].x, pts[WRIST].y), (pts[MIDDLE_MCP].x, pts[MIDDLE_MCP].y))
        gap = math.dist((pts[THUMB_TIP].x, pts[THUMB_TIP].y), (pts[INDEX_TIP].x, pts[INDEX_TIP].y))
        ratio = gap / max(palm, 1e-4)
        x, y = pts[INDEX_TIP].x, pts[INDEX_TIP].y

        now = time.time()
        with self._lock:
            fresh = self._pos is not None and self._is_fresh(self._time, now)
            if fresh:
                x = self._blend(self._pos[0], x, True)
                y = self._blend(self._pos[1], y, True)
            self._pos = (x, y)
            self._time = now
            self._pinch = ratio < (PINCH_OFF if self._pinch else PINCH_ON)
        return [(pts[i].x, pts[i].y) for i in (THUMB_TIP, INDEX_TIP)]

    def _vote(self, label: str | None) -> None:
        self._votes.append(label)
        top, count = Counter(self._votes).most_common(1)[0]
        with self._lock:
            self._gesture = top if top is not None and count >= VOTES_NEEDED else None
            self._gesture_time = time.time()

    @property
    def gesture(self) -> str | None:
        """Debounced 'palm' / 'fist', or None (no hand, unclear pose, or stale)."""
        with self._lock:
            if not self._is_fresh(self._gesture_time):
                return None
            return self._gesture

    @property
    def hand(self) -> tuple[float, float, bool] | None:
        """(x, y, pinching) with x, y in 0..1 over the playable camera area, or None."""
        with self._lock:
            if self._pos is None or not self._is_fresh(self._time):
                return None
            x, y = self._pos
            pinch = self._pinch
        span = 1 - 2 * FRAME_MARGIN
        return (min(1.0, max(0.0, (x - FRAME_MARGIN) / span)),
                min(1.0, max(0.0, (y - FRAME_MARGIN) / span)),
                pinch)
