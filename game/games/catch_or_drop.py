"""Don't Get Fired: office-themed reskin of Catch or Drop.

Single-file minigame (MediaPipe Hands tracking + game + demo runner).

Two inputs only:  OPEN PALM (catch)  and  FIST (let it drop).
  Good items (contracts, documents, programs): show an open palm while they pass the catch zone.
  Bad items (P45s, "You're Fired" letters): make a fist and let them fall. Catch one and you're sacked.
Win: deal with 10 items before losing all 3 lives.

Install:  uv add pygame opencv-python mediapipe numpy
Try it:   uv run main.py

Custom artwork (optional): drop PNGs (transparent background recommended) into an
`assets/` folder next to this file. Any that are missing fall back to code-drawn art:
    assets/contract.png   assets/document.png   assets/program.png
    assets/p45.png        assets/fired.png
Images are scaled to fit roughly SPRITE_MAX_W x SPRITE_MAX_H pixels, keeping aspect ratio.

Demo keys: SPACE restart after a round, Esc quit.
Keyboard fallback (no camera): O or Up = open palm, F or Down = fist.
"""

from __future__ import annotations

import math
import os
import random
import sys
import threading
import time
import urllib.request
from collections import Counter, deque
from dataclasses import dataclass

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
# Hand tracking (MediaPipe Hands, background thread). Reports "palm", "fist" or None.
# =============================================================================
HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
HAND_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")

WRIST, MIDDLE_KNUCKLE = 0, 9
# (fingertip id, knuckle id, "extended" threshold). Each finger is measured as
# tip-to-knuckle distance divided by palm size (wrist to middle knuckle): ~1.0 for a
# straight finger, ~0.4 when curled into a fist. Scale- and rotation-invariant.
FINGERS = ((8, 5, 0.80), (12, 9, 0.85), (16, 13, 0.80), (20, 17, 0.62))
CURLED_RATIO = 0.55

VOTE_FRAMES = 5          # a pose must win 3 of the last 5 frames: kills flicker
VOTES_NEEDED = 3
STALE_SECONDS = 0.3      # no fresh detection for this long -> None
PREVIEW_SIZE = (160, 120)


def classify_hand(pts, w: int, h: int) -> str | None:
    """'palm', 'fist', or None when the hand is ambiguous (mid-transition)."""
    def dist(a, b):
        return math.hypot((a.x - b.x) * w, (a.y - b.y) * h)

    palm_size = dist(pts[WRIST], pts[MIDDLE_KNUCKLE])
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


class HandTracker:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.backend: str | None = None
        self.error: str | None = MP_ERROR

        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._votes: deque = deque(maxlen=VOTE_FRAMES)
        self._stable: str | None = None
        self._stable_time = 0.0
        self._preview: bytes | None = None

        self._hands = None
        self._landmarker = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running:
            return
        if mp is None:
            print("Hand tracking: OFF - mediapipe not importable:", self.error)
            print("Python being used:", sys.executable)
            return
        # Open the camera on the calling (main) thread: macOS wants that.
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            self.error = "could not open webcam"
            print("Hand tracking: OFF -", self.error)
            return
        self._cap = cap
        if not (self._init_legacy() or self._init_tasks()):
            print("Hand tracking: OFF -", self.error)
            print("Python being used:", sys.executable)
            cap.release()
            self._cap = None
            return
        print(f"Hand tracking: ON ({self.backend} backend)")
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
    def _init_legacy(self) -> bool:
        try:
            self._hands = mp.solutions.hands.Hands(
                max_num_hands=1, model_complexity=0,
                min_detection_confidence=0.6, min_tracking_confidence=0.5)
            self.backend = "mediapipe-hands"
            return True
        except Exception as exc:
            self.error = f"legacy Hands unavailable: {exc!r}"
            return False

    def _init_tasks(self) -> bool:
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            if not os.path.exists(HAND_MODEL_PATH):
                print("Downloading hand model (one time, ~8 MB)...")
                urllib.request.urlretrieve(HAND_MODEL_URL, HAND_MODEL_PATH + ".part")
                os.replace(HAND_MODEL_PATH + ".part", HAND_MODEL_PATH)
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
                num_hands=1,
                running_mode=vision.RunningMode.IMAGE)
            self._landmarker = vision.HandLandmarker.create_from_options(options)
            self.backend = "mediapipe-tasks"
            return True
        except Exception as exc:
            self.error = f"HandLandmarker failed: {exc!r}"
            return False

    # ---------------------------------------------------------- measurement
    def _measure(self, frame_bgr):
        """Returns (label or None, [normalised (x, y) landmarks for the preview])."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.backend == "mediapipe-hands":
            res = self._hands.process(rgb)
            if not res.multi_hand_landmarks:
                return None, []
            pts = res.multi_hand_landmarks[0].landmark
        else:
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = self._landmarker.detect(img)
            if not res.hand_landmarks:
                return None, []
            pts = res.hand_landmarks[0]
        return classify_hand(pts, w, h), [(p.x, p.y) for p in pts]

    def _loop(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror view
            try:
                label, marks = self._measure(frame)
            except Exception as exc:
                self.error = f"tracking error: {exc!r}"
                label, marks = None, []

            small = cv2.resize(frame, PREVIEW_SIZE)
            color = {"palm": (0, 255, 0), "fist": (0, 160, 255)}.get(label, (200, 200, 200))
            for mx, my in marks:
                cv2.circle(small, (int(mx * PREVIEW_SIZE[0]), int(my * PREVIEW_SIZE[1])), 2, color, -1)
            preview = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes()

            self._votes.append(label)
            top, count = Counter(self._votes).most_common(1)[0]
            stable = top if (top is not None and count >= VOTES_NEEDED) else None
            with self._lock:
                self._stable, self._stable_time = stable, time.time()
                self._preview = preview

    # ------------------------------------------------------------ accessors
    @property
    def available(self) -> bool:
        return self._running and self.backend is not None

    @property
    def hand(self) -> str | None:
        """'palm', 'fist', or None (no hand, unclear pose, or stale)."""
        with self._lock:
            if time.time() - self._stable_time > STALE_SECONDS:
                return None
            return self._stable

    def preview_surface(self) -> pygame.Surface | None:
        """Small mirrored camera image with hand dots, for on-screen display."""
        with self._lock:
            data = self._preview
        if data is None:
            return None
        return pygame.image.frombuffer(data, PREVIEW_SIZE, "RGB")


# =============================================================================
# The minigame
# =============================================================================
TARGET_OBJECTS = 10
LIVES = 3
FALL_TIME = (1.65, 1.1)        # seconds from spawn to your hand, start -> end of round
SPAWN_INTERVAL = (1.5, 0.9)    # seconds between objects, start -> end of round
BAD_CHANCE = 0.4               # after the first two objects; never more than 2 in a row
PALM_HOLD = 0.05               # palm must be shown this long inside the zone to catch
FIST_HOLD = 0.05               # fist must be shown this long inside the zone to drop a bad item
READY_SECONDS = 3.5
SIM_SECONDS = 0.5              # keyboard fallback: how long a key press "holds" a pose
FLASH_SECONDS = 0.7
OBJ_R = 34                     # radius of the ring drawn around each item

# --- item kinds --------------------------------------------------------------
GOOD_KINDS = ("contract", "document", "program")
BAD_KINDS = ("p45", "fired")

KIND_COLORS = {
    "contract": (245, 235, 200),
    "document": (170, 210, 255),
    "program": (90, 220, 140),
    "p45": (240, 210, 90),
    "fired": (235, 70, 70),
}

# --- custom artwork ----------------------------------------------------------
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
SPRITE_FILES = {kind: f"{kind}.png" for kind in GOOD_KINDS + BAD_KINDS}
SPRITE_MAX_W, SPRITE_MAX_H = 72, 72

BG = (16, 18, 32)
FLOOR = (30, 32, 50)
GOOD_COLOR = (110, 210, 130)
BAD_COLOR = (235, 70, 70)
PALM_COLOR = (125, 195, 255)
FIST_COLOR = (255, 170, 90)
DARK = (25, 25, 35)
PAPER = (248, 246, 238)
INK = (90, 95, 120)


@dataclass
class Item:
    kind: str
    good: bool
    x: float
    y: float
    vy: float
    palm_t: float = 0.0
    fist_t: float = 0.0
    judged: bool = False
    state: str = "falling"   # falling | caught | gone
    fade: float = 0.0


def lerp(pair: tuple[float, float], t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * t


def load_sprites() -> dict[str, pygame.Surface | None]:
    """Load optional PNGs from ASSET_DIR. Missing/broken files map to None (code-drawn fallback)."""
    sprites: dict[str, pygame.Surface | None] = {}
    for kind, filename in SPRITE_FILES.items():
        path = os.path.join(ASSET_DIR, filename)
        sprites[kind] = None
        if not os.path.exists(path):
            continue
        try:
            img = pygame.image.load(path)
            img = img.convert_alpha() if pygame.display.get_surface() else img
            iw, ih = img.get_size()
            scale = min(SPRITE_MAX_W / iw, SPRITE_MAX_H / ih)
            sprites[kind] = pygame.transform.smoothscale(img, (max(1, int(iw * scale)), max(1, int(ih * scale))))
        except Exception as exc:
            print(f"Could not load {path}: {exc!r} (using built-in art)")
    return sprites


class CatchOrDrop(Minigame):
    """Palm to catch the good paperwork, fist to let the P45s fall. Don't get sacked."""

    title = "Don't Get Fired"

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen)
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.tiny_font = pygame.font.Font(None, 18)
        self.big_font = pygame.font.Font(None, 64)
        self._overlay: pygame.Surface | None = None
        self.sprites = load_sprites()

        # Pass a shared HandTracker in if several minigames use the camera.
        self._owns_tracker = tracker is None
        self.tracker = tracker if tracker is not None else HandTracker()
        self.tracker.start()
        self.start()

    # ------------------------------------------------------------------ API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Open Palm", "Show an open palm to catch good paperwork (or O / Up)",
                   self.open_palm),
            Action("Fist", "Make a fist to let a P45 fall (or F / Down)", self.make_fist),
        )

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.elapsed = 0.0
        self.score = 0
        self.lives = LIVES
        self.spawned = 0
        self.resolved = 0
        self.bad_run = 0
        self.spawn_timer = 99.0     # spawn the first object as soon as play starts
        self.items: list[Item] = []
        self.particles: list[list] = []

        self.hand: str | None = None
        self.sim_pose: str | None = None
        self.sim_time = 0.0

        self.mode = "ready"
        self.ready_t = 0.0
        self.flash_t = 0.0
        self.flash_text = ""
        self.flash_color = GOOD_COLOR

    def close(self) -> None:
        """Release the camera (only if this minigame created the tracker)."""
        if self._owns_tracker:
            self.tracker.stop()

    # ---------------------------------------------------------------- input
    def open_palm(self) -> None:
        self.sim_pose, self.sim_time = "palm", SIM_SECONDS

    def make_fist(self) -> None:
        self.sim_pose, self.sim_time = "fist", SIM_SECONDS

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_o, pygame.K_UP):
            self.open_palm()
        elif event.key in (pygame.K_f, pygame.K_DOWN):
            self.make_fist()

    # ------------------------------------------------------------- geometry
    def _geom(self) -> tuple[int, int, int, int, int]:
        """(width, hand_y, zone_top, zone_bottom, ground_y)"""
        w, h = self.screen.get_size()
        hand_y = h - 120
        return w, hand_y, hand_y - 150, hand_y - 20, hand_y + 70

    # --------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.flash_t = max(0.0, self.flash_t - dt)
        self._read_hand(dt)
        self._update_particles(dt)

        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        self._spawn(dt)
        self._update_items(dt)

        if self.lives <= 0:
            self.finish(False)
        elif self.resolved >= TARGET_OBJECTS:
            self.finish(True)

    def _read_hand(self, dt: float) -> None:
        if self.sim_time > 0 and self.sim_pose:   # keyboard fallback
            self.sim_time -= dt
            self.hand = self.sim_pose
        else:
            self.hand = self.tracker.hand if self.tracker.available else None

    def _spawn(self, dt: float) -> None:
        if self.spawned >= TARGET_OBJECTS:
            return
        self.spawn_timer += dt
        progress = self.spawned / max(1, TARGET_OBJECTS - 1)
        if self.spawn_timer < lerp(SPAWN_INTERVAL, progress):
            return
        self.spawn_timer = 0.0

        w, hand_y, _, _, _ = self._geom()
        bad = self.spawned >= 2 and self.bad_run < 2 and random.random() < BAD_CHANCE
        self.bad_run = self.bad_run + 1 if bad else 0
        kind = random.choice(BAD_KINDS) if bad else random.choice(GOOD_KINDS)
        spawn_y = -OBJ_R - 10
        vy = (hand_y - spawn_y) / lerp(FALL_TIME, progress)
        self.items.append(Item(kind, not bad, w / 2 + random.uniform(-70, 70), spawn_y, vy))
        self.spawned += 1

    def _update_items(self, dt: float) -> None:
        w, hand_y, zone_top, zone_bot, ground_y = self._geom()
        for it in self.items:
            if it.state == "caught":
                it.fade -= dt
                if it.fade <= 0:
                    it.state = "gone"
                continue
            it.y += it.vy * dt
            if not it.judged:
                if zone_top <= it.y <= zone_bot:
                    self._sample(it, dt)
                if not it.judged and it.y > zone_bot:
                    self._judge(it, caught=False)
            if it.y >= ground_y and it.state == "falling":
                self._burst(it.x, ground_y, KIND_COLORS[it.kind], 14, 260)
                it.state = "gone"
        self.items = [it for it in self.items if it.state != "gone"]

    def _sample(self, it: Item, dt: float) -> None:
        """Called every frame the item is inside the catch zone."""
        it.palm_t = it.palm_t + dt if self.hand == "palm" else max(0.0, it.palm_t - 2 * dt)
        it.fist_t = it.fist_t + dt if self.hand == "fist" else max(0.0, it.fist_t - 2 * dt)
        if it.palm_t >= PALM_HOLD:
            self._judge(it, caught=True)

    def _judge(self, it: Item, caught: bool) -> None:
        w, hand_y, _, _, _ = self._geom()
        it.judged = True
        self.resolved += 1
        if caught:
            it.state, it.fade = "caught", 0.3
            it.x, it.y = w / 2, hand_y - 30
            if it.good:
                self._success("SIGNED OFF!" if it.kind == "contract" else "FILED!"
                              if it.kind == "document" else "DEPLOYED!")
            else:
                self._burst(it.x, it.y, KIND_COLORS[it.kind], 28, 380)
                self._failure("YOU'RE FIRED!" if it.kind == "fired" else "P45 ACCEPTED!")
        elif it.good:
            self._failure("PAPERWORK LOST!")
        elif it.fist_t >= FIST_HOLD:
            self._success("DODGED THE SACK!")
        else:
            self._failure("SHOW A FIST!")

    def _success(self, text: str) -> None:
        self.score += 1
        self.flash_text, self.flash_color, self.flash_t = text, GOOD_COLOR, FLASH_SECONDS

    def _failure(self, text: str) -> None:
        self.lives -= 1
        self.flash_text, self.flash_color, self.flash_t = text, BAD_COLOR, FLASH_SECONDS

    # ------------------------------------------------------------ particles
    def _burst(self, x: float, y: float, color: tuple[int, int, int], count: int, speed: float) -> None:
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            sp = random.uniform(0.3, 1.0) * speed
            self.particles.append(
                [x, y, math.cos(angle) * sp, math.sin(angle) * sp - 80, random.uniform(0.35, 0.7), color])

    def _update_particles(self, dt: float) -> None:
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 700 * dt
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]

    # ----------------------------------------------------------------- draw
    def _text(self, screen: pygame.Surface, font: pygame.font.Font, text: str,
              color: tuple[int, int, int], center: tuple[int, int]) -> None:
        surf = font.render(text, True, color)
        screen.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))

    def draw(self, screen: pygame.Surface) -> None:
        w, hand_y, zone_top, zone_bot, ground_y = self._geom()
        h = screen.get_height()
        screen.fill(BG)
        pygame.draw.rect(screen, FLOOR, (0, ground_y, w, h - ground_y))

        # catch zone: brightens while an object you still need to deal with is inside it
        active = any(not it.judged and zone_top <= it.y <= zone_bot for it in self.items)
        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        self._overlay.fill((0, 0, 0, 0))
        pygame.draw.rect(self._overlay, (255, 255, 255, 70 if active else 25),
                         (w // 2 - 150, zone_top, 300, zone_bot - zone_top), border_radius=14)
        screen.blit(self._overlay, (0, 0))
        pygame.draw.rect(screen, (200, 200, 220) if active else (90, 90, 110),
                         (w // 2 - 150, zone_top, 300, zone_bot - zone_top), 2, border_radius=14)

        for it in self.items:
            self._draw_item(screen, it)
        self._draw_hand(screen, w // 2, hand_y)
        for x, y, _, _, life, color in self.particles:
            pygame.draw.circle(screen, color, (int(x), int(y)), max(2, int(life * 10)))

        self._draw_hud(screen, w, h)

        if self.mode == "ready":
            self._text(screen, self.big_font, "OPEN PALM = CATCH", GOOD_COLOR, (w // 2, 150))
            self._text(screen, self.big_font, "FIST = LET P45s FALL", BAD_COLOR, (w // 2, 215))
            self._text(screen, self.font, "Get ready...", (230, 230, 230), (w // 2, 270))
        elif self.flash_t > 0:
            self._text(screen, self.big_font, self.flash_text, self.flash_color, (w // 2, 110))

    # --- code-drawn fallback art (used when no PNG is supplied) --------------
    def _paper(self, screen: pygame.Surface, x: int, y: int, w: int, h: int,
               fill=PAPER, border=DARK) -> pygame.Rect:
        rect = pygame.Rect(x - w // 2, y - h // 2, w, h)
        pygame.draw.rect(screen, fill, rect, border_radius=3)
        pygame.draw.rect(screen, border, rect, 3, border_radius=3)
        return rect

    def _text_lines(self, screen: pygame.Surface, rect: pygame.Rect, top: int, count: int,
                    color=INK, gap: int = 8, pad: int = 9) -> None:
        for i in range(count):
            end = rect.right - pad - (10 if i == count - 1 else 0)
            yy = rect.top + top + i * gap
            pygame.draw.line(screen, color, (rect.left + pad, yy), (end, yy), 2)

    def _draw_contract(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 52, 68)
        pygame.draw.rect(screen, INK, (r.left + 9, r.top + 8, r.w - 18, 4))   # heading
        self._text_lines(screen, r, 20, 4)
        sig = [(r.left + 9, r.bottom - 12), (r.left + 15, r.bottom - 20), (r.left + 20, r.bottom - 10),
               (r.left + 26, r.bottom - 19), (r.left + 32, r.bottom - 12)]
        pygame.draw.lines(screen, (40, 80, 200), False, sig, 2)               # signature
        pygame.draw.circle(screen, BAD_COLOR, (r.right - 12, r.bottom - 14), 7)  # wax seal
        pygame.draw.circle(screen, (150, 30, 30), (r.right - 12, r.bottom - 14), 7, 2)

    def _draw_document(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 52, 68, fill=(232, 240, 255))
        fold = [(r.right - 14, r.top), (r.right, r.top + 14), (r.right - 14, r.top + 14)]
        pygame.draw.polygon(screen, (170, 190, 230), fold)
        pygame.draw.polygon(screen, DARK, fold, 2)
        self._text_lines(screen, r, 20, 5, color=(110, 130, 170))

    def _draw_program(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = pygame.Rect(x - 34, y - 28, 68, 56)
        pygame.draw.rect(screen, (28, 32, 46), r, border_radius=5)
        bar = pygame.Rect(r.left, r.top, r.w, 13)
        pygame.draw.rect(screen, (70, 80, 115), bar, border_top_left_radius=5, border_top_right_radius=5)
        for i, c in enumerate(((255, 95, 90), (255, 190, 60), (60, 200, 90))):
            pygame.draw.circle(screen, c, (r.left + 8 + i * 9, r.top + 6), 3)
        for i, (indent, length) in enumerate(((0, 30), (8, 38), (8, 24), (0, 18))):
            yy = r.top + 22 + i * 8
            pygame.draw.line(screen, (90, 230, 140), (r.left + 7 + indent, yy), (r.left + 7 + indent + length, yy), 2)
        pygame.draw.rect(screen, DARK, r, 3, border_radius=5)

    def _draw_p45(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 52, 68, fill=(250, 240, 200))
        pygame.draw.rect(screen, (200, 60, 60), (r.left + 3, r.top + 3, r.w - 6, 18))
        self._text(screen, self.small_font, "P45", (255, 255, 255), (r.centerx, r.top + 12))
        self._text_lines(screen, r, 30, 4, color=(140, 120, 70))

    def _draw_fired(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 58, 68, fill=(255, 235, 235), border=(160, 30, 30))
        self._text(screen, self.tiny_font, "YOU'RE", (190, 30, 30), (r.centerx, r.top + 17))
        self._text(screen, self.small_font, "FIRED!", (190, 30, 30), (r.centerx, r.top + 33))
        self._text_lines(screen, r, 48, 3, color=(190, 120, 120))

    _FALLBACK = {
        "contract": "_draw_contract", "document": "_draw_document", "program": "_draw_program",
        "p45": "_draw_p45", "fired": "_draw_fired",
    }

    def _draw_item(self, screen: pygame.Surface, it: Item) -> None:
        x, y = int(it.x), int(it.y)
        sprite = self.sprites.get(it.kind)
        if sprite is not None:
            screen.blit(sprite, (x - sprite.get_width() // 2, y - sprite.get_height() // 2))
        else:
            getattr(self, self._FALLBACK[it.kind])(screen, x, y)

        ring = GOOD_COLOR if it.good else BAD_COLOR
        pygame.draw.circle(screen, ring, (x, y), OBJ_R + 14, 3)
        self._text(screen, self.small_font, "CATCH" if it.good else "DROP", ring, (x, y - OBJ_R - 32))

    def _draw_hand(self, screen: pygame.Surface, cx: int, cy: int) -> None:
        if self.hand == "palm":
            c = PALM_COLOR
            pygame.draw.circle(screen, c, (cx, cy + 10), 34)
            for off, ht in ((-27, 46), (-9, 56), (9, 52), (27, 40)):
                pygame.draw.rect(screen, c, (cx + off - 7, cy - 5 - ht, 14, ht), border_radius=7)
            thumb = [(cx - 30, cy + 22), (cx - 60, cy - 2), (cx - 49, cy - 14), (cx - 22, cy + 6)]
            pygame.draw.polygon(screen, c, thumb)
            label = "OPEN PALM"
        elif self.hand == "fist":
            c = FIST_COLOR
            pygame.draw.circle(screen, c, (cx, cy), 38)
            for kx, ky in ((-27, -24), (-9, -28), (9, -28), (27, -24)):
                pygame.draw.circle(screen, c, (cx + kx, cy + ky), 12)
                pygame.draw.circle(screen, DARK, (cx + kx, cy + ky), 12, 2)
            pygame.draw.ellipse(screen, c, (cx - 54, cy - 2, 40, 22))
            pygame.draw.ellipse(screen, DARK, (cx - 54, cy - 2, 40, 22), 2)
            label = "FIST"
        else:
            pygame.draw.circle(screen, (90, 90, 110), (cx, cy), 38, 3)
            label = "no hand / unclear"
        self._text(screen, self.small_font, label, (210, 210, 220), (cx, cy + 62))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        screen.blit(self.font.render(f"{self.resolved} / {TARGET_OBJECTS}", True, (240, 240, 240)), (10, 10))
        for i in range(LIVES):
            alive = i < self.lives
            pygame.draw.circle(screen, BAD_COLOR if alive else (60, 60, 75), (22 + i * 28, 56), 10)

        preview = self.tracker.preview_surface() if self.tracker.available else None
        if preview is not None:
            pw, ph = preview.get_size()
            pos = (w - pw - 10, 10)
            screen.blit(preview, pos)
            pygame.draw.rect(screen, (200, 200, 200), (*pos, pw, ph), 2)

        if self.tracker.available:
            info = f"Hand tracking: {self.tracker.backend}"
        else:
            info = "No hand tracking - keyboard: O = open palm, F = fist"
        screen.blit(self.small_font.render(info, True, (140, 140, 160)), (10, h - 26))


# =============================================================================
# Demo runner
# =============================================================================
def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((960, 540))
    pygame.display.set_caption("Don't Get Fired")
    clock = pygame.time.Clock()
    big = pygame.font.Font(None, 84)
    small = pygame.font.Font(None, 32)

    game = CatchOrDrop(screen)
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
            msg, col = ("EMPLOYEE OF THE MONTH!", GOOD_COLOR) if game.won else ("YOU'RE FIRED!", BAD_COLOR)
            text = big.render(msg, True, col)
            hint = small.render("Press SPACE to play again", True, (230, 230, 230))
            cx, cy = screen.get_width() // 2, screen.get_height() // 2
            screen.blit(text, (cx - text.get_width() // 2, cy - 50))
            screen.blit(hint, (cx - hint.get_width() // 2, cy + 25))

        pygame.display.flip()

    game.close()
    pygame.quit()


if __name__ == "__main__":
    main()