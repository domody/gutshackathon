from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from abc import ABC, abstractmethod

import cv2
import pygame

try:
    import mediapipe as mp
    MP_ERROR = None
except Exception as exc:  # keep the real reason so it can be reported
    mp = None
    MP_ERROR = repr(exc)

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def ensure_model(url: str, path: str, label: str) -> str:
    """Download a MediaPipe model once and return its path."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(f"Downloading {label} model (one time)...")
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)
    return path


class CameraTracker(ABC):
    """Reads the webcam on a worker thread. Subclasses set up a backend and measure frames."""

    label = "Tracking"
    stale_seconds = 0.5      # no detection for this long -> reading becomes None
    smoothing = 0.5          # 0..1, higher = snappier
    preview_size = (160, 120)
    max_fps: float | None = None   # cap the capture loop (None = as fast as frames arrive)

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.backend: str | None = None
        self.error: str | None = MP_ERROR

        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._preview: bytes | None = None

    # Start and stop the camera thread
    def start(self) -> None:
        if self._running:
            return
        # Open the camera on the calling (main) thread: macOS wants that.
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            self.error = "could not open webcam"
            print(f"{self.label}: OFF -", self.error)
            return
        self._configure_capture(cap)
        self._cap = cap
        if not self._setup():
            print(f"{self.label}: OFF -", self.error)
            print("Python being used:", sys.executable)
            cap.release()
            self._cap = None
            return
        print(f"{self.label}: ON ({self.backend} backend)")
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
        self._teardown()

    # Subclass hooks
    @abstractmethod
    def _setup(self) -> bool:
        """Create the detector and set self.backend. Return False if unavailable."""

    def _configure_capture(self, cap) -> None:
        """Optionally set resolution, buffering, etc. on the opened camera."""

    def _teardown(self) -> None:
        """Release detectors created in _setup()."""

    @abstractmethod
    def _process(self, frame_bgr) -> list[tuple[float, float]]:
        """Measure one mirrored frame, store results under self._lock, return preview marks."""

    # Capture loop
    def _loop(self) -> None:
        pw, ph = self.preview_size
        while self._running:
            started = time.monotonic()
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror so it feels like a mirror
            try:
                marks = self._process(frame)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                marks = []

            small = cv2.resize(frame, self.preview_size)
            for mx, my in marks:
                cv2.circle(small, (int(mx * pw), int(my * ph)), 3, (0, 255, 0), -1)
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()
            with self._lock:
                self._preview = preview

            if self.max_fps:
                time.sleep(max(0.0, 1 / self.max_fps - (time.monotonic() - started)))

    def _is_fresh(self, stamp: float, now: float | None = None) -> bool:
        return (time.time() if now is None else now) - stamp < self.stale_seconds

    def _blend(self, old: float, new: float, fresh: bool) -> float:
        return old + (new - old) * self.smoothing if fresh else new

    # Read tracked values
    @property
    def available(self) -> bool:
        return self._running and self.backend is not None

    def preview_surface(self) -> pygame.Surface | None:
        """Small mirrored camera image with tracking dots, for on-screen display."""
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, self.preview_size, "RGB")
