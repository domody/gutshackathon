"""Two-hand and shoulder tracking for Tug of War: open hand / fist per side plus shoulders.

Runs MediaPipe HandLandmarker (two hands) and PoseLandmarker (shoulders only).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

from game.tracking.body import LEFT_SHOULDER, POSE_MODEL_PATH, POSE_MODEL_URL, RIGHT_SHOULDER, landmark_visible
from game.tracking.camera import CameraTracker, ensure_model, mp
from game.tracking.hand import HAND_MODEL_PATH, HAND_MODEL_URL

MIN_SHOULDER_WIDTH = 0.055  # Reject smaller widths because the player is too far from the camera.
POSE_INTERVAL = 4  # Run the pose model once every four camera frames.
FINGER_PAIRS = ((8, 6), (12, 10), (16, 14), (20, 18))  # Landmark ID pairs: fingertip and middle finger joint.
HAND_MARKS = (0, 5, 8, 9, 12, 13, 16, 17, 20)


@dataclass(frozen=True)
class HandReading:
    side: str
    open_hand: bool
    fist: bool
    wrist_x: float
    wrist_y: float
    palm_size: float


@dataclass(frozen=True)
class PullReading:
    body_visible: bool = False
    shoulder_width: float = 0.0
    left_shoulder: tuple[float, float] = (0.0, 0.0)
    right_shoulder: tuple[float, float] = (0.0, 0.0)
    hands: tuple[HandReading, ...] = ()
    timestamp: float = 0.0


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


class PullTracker(CameraTracker):
    label = "Pull tracking"
    stale_seconds = 0.6
    max_fps = 20

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__(camera_index)
        self._hands = None
        self._pose = None
        self._cached_pose = None
        self._frame = 0
        self._reading = PullReading()

    def _configure_capture(self, cap) -> None:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, self.max_fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _setup(self) -> bool:
        if mp is None:
            return False
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            hand_path = ensure_model(HAND_MODEL_URL, HAND_MODEL_PATH, "hand")
            pose_path = ensure_model(POSE_MODEL_URL, POSE_MODEL_PATH, "pose")
            self._hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=hand_path),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=0.55,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5))
            self._pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=pose_path),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=0.55,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5))
            self.backend = "mediapipe-hand+pose"
            return True
        except Exception as exc:
            self.error = f"Hand/Pose landmarkers failed: {exc!r}"
            self._teardown()
            return False

    def _teardown(self) -> None:
        for detector in (self._hands, self._pose):
            if detector is not None:
                detector.close()
        self._hands = self._pose = self._cached_pose = None

    @staticmethod
    def _classify_hand(points, side: str) -> HandReading:
        wrist = points[0]
        extended = curled = 0
        for tip, pip in FINGER_PAIRS:
            tip_dist, pip_dist = _dist(points[tip], wrist), _dist(points[pip], wrist)
            extended += tip_dist > pip_dist * 1.17
            curled += tip_dist < pip_dist * 1.03
        return HandReading(side, extended >= 3, curled >= 3, wrist.x, wrist.y,
                           _dist(points[5], points[17]))

    def _process(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        stamp = int(time.monotonic() * 1000)
        hand_result = self._hands.detect_for_video(image, stamp)
        if self._cached_pose is None or self._frame % POSE_INTERVAL == 0:
            self._cached_pose = self._pose.detect_for_video(image, stamp)
        self._frame += 1

        marks: list[tuple[float, float]] = []
        body_visible = False
        width = 0.0
        left_pos = right_pos = (0.0, 0.0)
        if self._cached_pose.pose_landmarks:
            pose = self._cached_pose.pose_landmarks[0]
            left, right = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
            left_pos, right_pos = (left.x, left.y), (right.x, right.y)
            width = _dist(left, right)
            body_visible = landmark_visible(left) and landmark_visible(right) and width >= MIN_SHOULDER_WIDTH
            marks += [left_pos, right_pos]

        hands = []
        for points, handedness in zip(hand_result.hand_landmarks, hand_result.handedness):
            hands.append(self._classify_hand(points, handedness[0].category_name.lower()))
            marks += [(points[i].x, points[i].y) for i in HAND_MARKS]

        reading = PullReading(body_visible, width, left_pos, right_pos, tuple(hands), time.time())
        with self._lock:
            self._reading = reading
        return marks

    @property
    def reading(self) -> PullReading:
        """Latest shoulders and hands; empty if nothing was seen recently."""
        with self._lock:
            reading = self._reading
        if not self._is_fresh(reading.timestamp):
            return PullReading(timestamp=reading.timestamp)
        return reading
