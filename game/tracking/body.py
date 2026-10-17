"""Upper-body tracking: how fast the player moves and whether they pump their arms.

Backends, best first: MediaPipe Pose -> MediaPipe PoseLandmarker.
"""

from __future__ import annotations

import math
import os
import time

import cv2
import numpy as np

from game.tracking.camera import MODELS_DIR, CameraTracker, ensure_model, mp

POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
POSE_MODEL_PATH = os.path.join(MODELS_DIR, "pose_landmarker_lite.task")

# Pose landmark ids
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16

BODY_IDS = (NOSE, LEFT_SHOULDER, RIGHT_SHOULDER)
HAND_IDS = (LEFT_WRIST, RIGHT_WRIST)
TRACKED_IDS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST)
MARK_IDS = (NOSE, *TRACKED_IDS)

VISIBILITY_THRESHOLD = 0.48
MIN_SHOULDER_WIDTH = 0.055   # smaller than this and the player is too far away


def landmark_visible(point) -> bool:
    """True if a pose landmark is confidently inside (or just outside) the frame."""
    return (getattr(point, "visibility", 1.0) >= VISIBILITY_THRESHOLD
            and getattr(point, "presence", 1.0) >= VISIBILITY_THRESHOLD
            and -0.08 <= point.x <= 1.08
            and -0.08 <= point.y <= 1.08)


class BodyTracker(CameraTracker):
    label = "Body tracking"

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__(camera_index)
        self._pose = None
        self._landmarker = None

        self._previous: dict[int, tuple[float, float]] | None = None
        self._previous_time = 0.0
        self._pump = 0.0
        self._motion = 0.0
        self._width: float | None = None
        self._hands = False
        self._time = 0.0

    # Backend setup and detection
    def _setup(self) -> bool:
        return self._init_pose() or self._init_tasks()

    def _init_pose(self) -> bool:
        if mp is None:
            return False
        try:
            solutions = getattr(mp, "solutions", None)
            if solutions is None:
                return False
            self._pose = solutions.pose.Pose(
                static_image_mode=False, model_complexity=0, enable_segmentation=False,
                min_detection_confidence=0.55, min_tracking_confidence=0.5)
            self.backend = "mediapipe-pose"
            return True
        except Exception as exc:
            self.error = f"legacy Pose unavailable: {exc!r}"
            return False

    def _init_tasks(self) -> bool:
        if mp is None:
            return False
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            path = ensure_model(POSE_MODEL_URL, POSE_MODEL_PATH, "pose")
            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.55,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5)
            self._landmarker = vision.PoseLandmarker.create_from_options(options)
            self.backend = "mediapipe-tasks"
            return True
        except Exception as exc:
            self.error = f"PoseLandmarker failed: {exc!r}"
            return False

    def _teardown(self) -> None:
        for detector in (self._pose, self._landmarker):
            if detector is not None:
                detector.close()
        self._pose = self._landmarker = None

    # Measure from detections
    def _detect(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.backend == "mediapipe-pose":
            res = self._pose.process(rgb)
            return res.pose_landmarks.landmark if res.pose_landmarks else None
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect(img)
        return res.pose_landmarks[0] if res.pose_landmarks else None

    def _lose(self) -> None:
        """No usable body this frame: the reading is None until the next good one."""
        self._previous = None
        with self._lock:
            self._width = None

    def _process(self, frame_bgr):
        now = time.time()
        pts = self._detect(frame_bgr)
        if pts is None or len(pts) <= RIGHT_WRIST:
            self._lose()
            return []

        marks = [(pts[i].x, pts[i].y) for i in MARK_IDS if landmark_visible(pts[i])]
        width = math.dist((pts[LEFT_SHOULDER].x, pts[LEFT_SHOULDER].y),
                          (pts[RIGHT_SHOULDER].x, pts[RIGHT_SHOULDER].y))
        # Head and shoulders show the player is there; hands may leave the frame.
        if width < MIN_SHOULDER_WIDTH or not all(landmark_visible(pts[i]) for i in BODY_IDS):
            self._lose()
            return marks
        hands = all(landmark_visible(pts[i]) for i in HAND_IDS)

        current = {i: (pts[i].x, pts[i].y) for i in TRACKED_IDS if landmark_visible(pts[i])}
        motion = pump = 0.0
        dt = now - self._previous_time
        if self._previous is not None and 1 / 120 <= dt <= 0.2:
            # Mean speed of the joints seen in both frames, in shoulder widths per second.
            shared = [i for i in current if i in self._previous]
            if shared:
                motion = sum(math.dist(current[i], self._previous[i]) for i in shared) \
                    / len(shared) / width / dt
            # Pumping = wrists moving vertically in opposite directions.
            if hands and all(i in self._previous for i in HAND_IDS):
                left = (current[LEFT_WRIST][1] - self._previous[LEFT_WRIST][1]) / dt
                right = (current[RIGHT_WRIST][1] - self._previous[RIGHT_WRIST][1]) / dt
                if left * right < 0:
                    pump = abs(left - right) / width
        self._previous, self._previous_time = current, now

        with self._lock:
            fresh = self._width is not None and self._is_fresh(self._time, now)
            self._pump = self._blend(self._pump, pump, fresh)
            self._motion = self._blend(self._motion, motion, fresh)
            self._width, self._hands, self._time = width, hands, now
        return marks

    # Read tracked values
    @property
    def body(self) -> tuple[float, float, float, bool] | None:
        """(pump, motion, shoulder_width, hands_visible), or None if no body seen recently."""
        with self._lock:
            if self._width is None or not self._is_fresh(self._time):
                return None
            return self._pump, self._motion, self._width, self._hands
