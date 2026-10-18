from __future__ import annotations

import math
import os
import time

import cv2
import numpy as np

from game.tracking.camera import MODELS_DIR, CameraTracker, ensure_model, mp

HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
HAND_MODEL_PATH = os.path.join(MODELS_DIR, "hand_landmarker.task")

WRIST = 0
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
TAP_SPEED = 0.7
RESET_SPEED = -0.22
TAP_COOLDOWN = 0.1
ACTIVE_SECONDS = 0.48
INFERENCE_INTERVAL = 1 / 18
INPUT_SIZE = (400, 300)


class TypingTracker(CameraTracker):
    label = "Typing tracking"
    stale_seconds = 0.5

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__(camera_index)
        self._landmarker = None
        self._previous: dict[str, tuple[float, float]] = {}
        self._armed = {"left": True, "right": True}
        self._last_side_tap = {"left": 0.0, "right": 0.0}
        self._last_tap = 0.0
        self._last_side = ""
        self._tap_count = 0
        self._hands_visible = 0
        self._time = 0.0
        self._last_inference = 0.0
        self._last_marks: list[tuple[float, float]] = []

    def _setup(self) -> bool:
        if mp is None:
            return False
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            path = ensure_model(HAND_MODEL_URL, HAND_MODEL_PATH, "hand")
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=path),
                num_hands=2,
                running_mode=vision.RunningMode.IMAGE,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._landmarker = vision.HandLandmarker.create_from_options(options)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FPS, 20)
            self.backend = "mediapipe-two-hand"
            return True
        except Exception as exc:
            self.error = f"HandLandmarker failed: {exc!r}"
            return False

    def _teardown(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def _process(self, frame_bgr):
        now = time.time()
        if now - self._last_inference < INFERENCE_INTERVAL:
            return self._last_marks
        self._last_inference = now
        frame_bgr = cv2.resize(frame_bgr, INPUT_SIZE, interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect(image)
        seen: set[str] = set()
        marks: list[tuple[float, float]] = []

        for index, points in enumerate(result.hand_landmarks):
            side = result.handedness[index][0].category_name.lower()
            seen.add(side)
            tip = points[INDEX_TIP]
            wrist = points[WRIST]
            middle = points[MIDDLE_MCP]
            palm = max(1e-4, math.hypot(wrist.x - middle.x, wrist.y - middle.y))
            previous = self._previous.get(side)

            if previous is not None:
                previous_y, previous_time = previous
                dt = now - previous_time
                if 1 / 120 <= dt <= 0.2:
                    speed = (tip.y - previous_y) / palm / dt
                    if speed <= RESET_SPEED:
                        self._armed[side] = True
                    elif (
                        speed >= TAP_SPEED
                        and self._armed[side]
                        and now - self._last_side_tap[side] >= TAP_COOLDOWN
                    ):
                        self._armed[side] = False
                        self._last_side_tap[side] = now
                        with self._lock:
                            self._last_tap = now
                            self._last_side = side
                            self._tap_count += 1

            self._previous[side] = (tip.y, now)
            marks.extend(
                [
                    (points[INDEX_MCP].x, points[INDEX_MCP].y),
                    (points[INDEX_PIP].x, points[INDEX_PIP].y),
                    (tip.x, tip.y),
                ]
            )

        self._previous = {side: value for side, value in self._previous.items() if side in seen}
        with self._lock:
            self._hands_visible = len(seen)
            self._time = now
        self._last_marks = marks
        return marks

    @property
    def typing(self) -> tuple[int, bool, str, int] | None:
        now = time.time()
        with self._lock:
            if not self._is_fresh(self._time, now):
                return None
            return (
                self._hands_visible,
                now - self._last_tap <= ACTIVE_SECONDS,
                self._last_side,
                self._tap_count,
            )
