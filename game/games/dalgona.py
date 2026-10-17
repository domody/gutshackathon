"""Dalgona: trace the cookie's outline with your index finger, pinch to crack along it.

Action 1 = move your hand (index fingertip is the pointer), Action 2 = pinch.
Crack too far off the line and the cookie breaks.

Try it:   python -m game.games.dalgona      (run from the project root)
Fallback: mouse to move, hold left button or SPACE to pinch. Esc quits the demo.
"""

from __future__ import annotations

import math
import os
import threading
import time
import urllib.request

import cv2
import numpy as np
import pygame

from game.minigame import Action, Minigame

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    MP_ERROR = None
except Exception as exc:
    mp = None
    MP_ERROR = repr(exc)


# =============================================================================
# Hand tracking (background thread; MediaPipe HandLandmarker)
# =============================================================================
HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
HAND_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")

# Hand landmark ids
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP = 0, 4, 8, 9

STALE_SECONDS = 0.4
SMOOTHING = 0.4            # 0..1, higher = snappier
PINCH_ON = 0.30            # thumb-index gap / palm size to start a pinch
PINCH_OFF = 0.45           # ...and to release it (hysteresis)
FRAME_MARGIN = 0.01        # camera border that maps to the screen edge
PREVIEW_SIZE = (160, 120)


class HandTracker:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.error: str | None = MP_ERROR
        self._cap = None
        self._landmarker = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._pos: tuple[float, float] | None = None
        self._pinch = False
        self._time = 0.0
        self._preview: bytes | None = None

    def start(self) -> None:
        if self._running:
            return
        if mp is None:
            print("Hand tracking: OFF -", self.error)
            return
        cap = cv2.VideoCapture(self.camera_index)  # open on the main thread
        if not cap.isOpened():
            cap.release()
            self.error = "could not open webcam"
            print("Hand tracking: OFF -", self.error)
            return
        try:
            if not os.path.exists(HAND_MODEL_PATH):
                print("Downloading hand model (one time, ~8 MB)...")
                urllib.request.urlretrieve(HAND_MODEL_URL, HAND_MODEL_PATH + ".part")
                os.replace(HAND_MODEL_PATH + ".part", HAND_MODEL_PATH)
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
                num_hands=1,
                running_mode=vision.RunningMode.IMAGE)
            self._landmarker = vision.HandLandmarker.create_from_options(options)
        except Exception as exc:
            self.error = f"HandLandmarker failed: {exc!r}"
            print("Hand tracking: OFF -", self.error)
            cap.release()
            return
        self._cap = cap
        print("Hand tracking: ON")
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

    def _measure(self, frame_bgr):
        """Returns ((x, y) normalised, pinching, preview marks) or None."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect(img)
        if not res.hand_landmarks:
            return None
        pts = res.hand_landmarks[0]
        palm = math.dist((pts[WRIST].x, pts[WRIST].y), (pts[MIDDLE_MCP].x, pts[MIDDLE_MCP].y))
        gap = math.dist((pts[THUMB_TIP].x, pts[THUMB_TIP].y), (pts[INDEX_TIP].x, pts[INDEX_TIP].y))
        ratio = gap / max(palm, 1e-4)
        marks = [(pts[i].x, pts[i].y) for i in (THUMB_TIP, INDEX_TIP)]
        return (pts[INDEX_TIP].x, pts[INDEX_TIP].y), ratio, marks

    def _loop(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror so it feels like a mirror
            try:
                found = self._measure(frame)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                found = None

            small = cv2.resize(frame, PREVIEW_SIZE)
            if found:
                for mx, my in found[2]:
                    cv2.circle(small, (int(mx * PREVIEW_SIZE[0]), int(my * PREVIEW_SIZE[1])),
                               3, (0, 255, 0), -1)
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()

            now = time.time()
            with self._lock:
                if found:
                    (x, y), ratio, _ = found
                    fresh = self._pos is not None and now - self._time < STALE_SECONDS
                    if fresh:
                        px, py = self._pos
                        x = px + (x - px) * SMOOTHING
                        y = py + (y - py) * SMOOTHING
                    self._pos = (x, y)
                    self._time = now
                    limit = PINCH_OFF if self._pinch else PINCH_ON
                    self._pinch = ratio < limit
                self._preview = preview

    @property
    def available(self) -> bool:
        return self._running

    @property
    def hand(self) -> tuple[float, float, bool] | None:
        """(x, y, pinching) with x, y in 0..1 over the playable camera area, or None."""
        with self._lock:
            if self._pos is None or time.time() - self._time > STALE_SECONDS:
                return None
            x, y = self._pos
            pinch = self._pinch
        span = 1 - 2 * FRAME_MARGIN
        return (min(1.0, max(0.0, (x - FRAME_MARGIN) / span)),
                min(1.0, max(0.0, (y - FRAME_MARGIN) / span)),
                pinch)

    def preview_surface(self) -> pygame.Surface | None:
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, PREVIEW_SIZE, "RGB")


# =============================================================================
# The minigame
# =============================================================================
TOLERANCE = 0.035          # on-line distance, fraction of screen height
MAX_OFF_LINE = 0.12        # off-line crack length allowed, fraction of screen height
WIN_COVERAGE = 0.95        # fraction of the outline to crack
SAMPLE_SPACING = 6         # px between outline sample points
END_DELAY = 1.5            # seconds the result stays up

BG = (30, 24, 20)
COOKIE = (214, 163, 84)
COOKIE_EDGE = (170, 120, 52)
LINE = (120, 78, 30)
CRACK_OK = (90, 50, 20)
CRACK_BAD = (200, 50, 40)
CUT_DONE = (250, 232, 170)


class Dalgona(Minigame):
    """Pinch and trace the shape without cracking outside the line."""

    title = "Dalgona"

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen)
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.big_font = pygame.font.Font(None, 72)

        self._owns_tracker = tracker is None
        self.tracker = tracker if tracker is not None else HandTracker()
        self.tracker.start()
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Move Hand", "Your index finger is the pointer (or the mouse)", self.move_hand),
            Action("Pinch", "Pinch thumb and index to crack (or hold click / SPACE)", self.pinch),
        )

    # Input is polled in update(); these exist for the tutorial.
    def move_hand(self) -> None:
        pass

    def pinch(self) -> None:
        pass

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.end_timer = 0.0
        self.result: bool | None = None

        w, h = self.screen.get_size()
        self.center = (w / 2, h / 2)
        radius = h * 0.26
        self.cookie_radius = radius * 1.55
        self.tolerance = TOLERANCE * h
        self.max_off = MAX_OFF_LINE * h
        self.verts = [
            (self.center[0] + radius * math.cos(math.radians(a)),
             self.center[1] + radius * math.sin(math.radians(a)))
            for a in (-90, 30, 150)
        ]
        self.samples = self._sample_outline()
        self.covered = [False] * len(self.samples)

        self.pointer = self.center
        self.prev_pointer: tuple[float, float] | None = None
        self.pinching = False
        self.face_lost = False
        self.off_length = 0.0
        self.cracks: list[list[tuple[float, float, bool]]] = []
        self._keys_pinch = False

    def close(self) -> None:
        if self._owns_tracker:
            self.tracker.stop()

    def _sample_outline(self) -> list[tuple[float, float]]:
        pts = []
        for i in range(3):
            (x0, y0), (x1, y1) = self.verts[i], self.verts[(i + 1) % 3]
            n = max(1, int(math.dist((x0, y0), (x1, y1)) / SAMPLE_SPACING))
            pts += [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n)]
        return pts

    # ---------------------------------------------------------------- input
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._keys_pinch = True
        elif event.type == pygame.KEYUP and event.key == pygame.K_SPACE:
            self._keys_pinch = False

    def _read_input(self) -> tuple[tuple[float, float], bool]:
        w, h = self.screen.get_size()
        hand = self.tracker.hand if self.tracker.available else None
        if self.tracker.available:
            self.face_lost = hand is None
            if hand is None:
                return self.pointer, False
            return (hand[0] * w, hand[1] * h), hand[2]
        return pygame.mouse.get_pos(), self._keys_pinch or pygame.mouse.get_pressed()[0]

    # --------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        if self.finished:
            return
        if self.result is not None:
            self.end_timer += dt
            if self.end_timer >= END_DELAY:
                self.finish(self.result)
            return

        pos, pinch = self._read_input()
        was_pinching = self.pinching
        self.pinching = pinch
        if not pinch:
            self.pointer, self.prev_pointer = pos, None
            return

        # Crack from the last pointer position (or here, if the pinch just began).
        start = self.prev_pointer if was_pinching and self.prev_pointer else pos
        if not was_pinching:
            self.cracks.append([])
        self._crack_along(start, pos)
        self.pointer, self.prev_pointer = pos, pos

        if self.off_length > self.max_off:
            self.result = False
        elif sum(self.covered) / len(self.covered) >= WIN_COVERAGE:
            self.result = True

    def _crack_along(self, a: tuple[float, float], b: tuple[float, float]) -> None:
        dist = math.dist(a, b)
        steps = max(1, int(dist / 6))
        step_len = dist / steps
        for i in range(1, steps + 1):
            t = i / steps
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            near = min(math.dist(p, s) for s in self.samples)
            on_line = near <= self.tolerance
            if on_line:
                for j, s in enumerate(self.samples):
                    if math.dist(p, s) <= self.tolerance:
                        self.covered[j] = True
            else:
                self.off_length += step_len
            self.cracks[-1].append((p[0], p[1], on_line))

    # ----------------------------------------------------------------- draw
    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        screen.fill(BG)
        cx, cy = int(self.center[0]), int(self.center[1])
        pygame.draw.circle(screen, COOKIE_EDGE, (cx, cy), int(self.cookie_radius) + 6)
        pygame.draw.circle(screen, COOKIE, (cx, cy), int(self.cookie_radius))
        pygame.draw.polygon(screen, LINE, self.verts, 4)

        # cracked stretches of the outline
        for (x, y), done in zip(self.samples, self.covered):
            if done:
                pygame.draw.circle(screen, CUT_DONE, (int(x), int(y)), 4)
        for stroke in self.cracks:
            for (x0, y0, _), (x1, y1, ok) in zip(stroke, stroke[1:]):
                pygame.draw.line(screen, CRACK_OK if ok else CRACK_BAD, (x0, y0), (x1, y1), 3)

        color = (255, 90, 70) if self.pinching else (255, 255, 255)
        px, py = int(self.pointer[0]), int(self.pointer[1])
        pygame.draw.circle(screen, color, (px, py), 10 if self.pinching else 14, 3)

        self._draw_hud(screen, w, h)
        if self.result is not None:
            msg, col = ("COOKIE CLEARED!", (110, 230, 130)) if self.result else ("CRACKED!", (240, 80, 70))
            text = self.big_font.render(msg, True, col)
            screen.blit(text, (w // 2 - text.get_width() // 2, 60))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        bx, bw, bh = 20, 220, 14
        for i, (label, frac, col) in enumerate((
            ("PROGRESS", sum(self.covered) / len(self.covered) / WIN_COVERAGE, (110, 220, 130)),
            ("CRACK DAMAGE", self.off_length / self.max_off, (230, 70, 60)),
        )):
            y = 20 + i * 44
            pygame.draw.rect(screen, (60, 52, 46), (bx, y + 20, bw, bh), border_radius=4)
            pygame.draw.rect(screen, col, (bx, y + 20, int(bw * min(1.0, frac)), bh), border_radius=4)
            screen.blit(self.small_font.render(label, True, (210, 200, 190)), (bx, y))

        preview = self.tracker.preview_surface() if self.tracker.available else None
        if preview is not None:
            pw, ph = preview.get_size()
            screen.blit(preview, (w - pw - 10, 10))
            pygame.draw.rect(screen, (200, 200, 200), (w - pw - 10, 10, pw, ph), 2)

        if self.tracker.available:
            info = "Hand tracking on - pinch to crack"
            if self.face_lost:
                info = "Hand lost!"
        else:
            info = "No camera - mouse to move, hold click or SPACE to pinch"
        screen.blit(self.small_font.render(info, True, (160, 150, 140)), (10, h - 28))


# =============================================================================
# Demo runner
# =============================================================================
def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((960, 640))
    pygame.display.set_caption("Dalgona")
    clock = pygame.time.Clock()

    game = Dalgona(screen)
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            else:
                game.handle_event(event)
        game.update(dt)
        if game.finished:
            game.start()
        game.draw(screen)
        pygame.display.flip()

    game.close()
    pygame.quit()


if __name__ == "__main__":
    main()
