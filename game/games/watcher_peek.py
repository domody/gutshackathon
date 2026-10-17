"""Sneak a Look: peek at your performance review while the line manager isn't watching.

The scene: your manager sits at their desk with your performance review. Your eyes are
CLOSED most of the time (you are "not looking"). Open them to read the review - but only
while the manager's eyes are down on their screen.

How it plays:
  * Opening your eyes while the manager is NOT looking fills REVIEW READ.
  * If your eyes are open while the manager is looking up, SUSPICION fills.
  * Suspicion full = busted (see CAUGHT_PENALTY_MODE). Review fully read = you win.
  * Watch the manager: their head lifts and their glasses flash red (the "tell") just before
    they look up. Near the very end of the round some tells are FAKES (they do not look up).

Keyboard fallback (no camera): hold SPACE to keep your eyes "open". C = recalibrate.

Artwork: everything is drawn with code by default. To use your own art, drop PNG files into
game/games/assets/watcher_peek/ using the names in ASSET_FILES below. Any missing file simply
falls back to the drawn version, so you can replace pieces one at a time.

Two-player ready: every per-player value lives in a PlayerSlot, and the Manager is shared.
Create it with num_players=2 (faces are assigned to players left-to-right on screen).
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from statistics import median

import pygame

from game.calibrated_minigame import CalibratedMinigame
from game.tracking.eye_tracking import EyeTracker
from game.minigame import Action
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

# =============================================================================
# Settings you are likely to change (toggles first)
# =============================================================================
PROGRESS_DECAY_ENABLED = True   # TOGGLE: progress slowly drains while your eyes are closed
CAUGHT_PENALTY_MODE = "full"    # TOGGLE: "full" = lose the round, "half" = lose 50%, "third" = lose 33%
CAUGHT_PENALTY_FRACTIONS = {"full": 1.0, "half": 0.5, "third": 0.33}

# Round
ROUND_SECONDS = 30.0            # time limit; running out counts as a loss
PROGRESS_FILL_SECONDS = 9.5     # seconds of SAFE open-eyes time needed to fill progress
PROGRESS_DECAY_SECONDS = 23.0   # seconds for a full bar to drain while eyes are closed (if enabled)
END_DELAY = 1.5                 # seconds the result stays up before the minigame finishes
READY_SECONDS = 1.0             # "open your eyes" pause after calibration

# Calibration (the open-eyes stage is the CalibratedMinigame one; the closed stage is ours)
CALIBRATE_TIMEOUT = 20.0        # long enough for the first-run model download
CLOSED_PROMPT_SECONDS = 1.0     # time given to close your eyes before sampling
CLOSED_SAMPLE_SECONDS = 1.0     # sampling time with eyes closed
MIN_CALIBRATION_SPAN = 0.25     # open/closed readings closer than this -> use default thresholds
DEFAULT_OPEN_BELOW = 0.35       # closed score under this = eyes open (hysteresis low edge)
DEFAULT_CLOSED_ABOVE = 0.55     # closed score over this = eyes closed (hysteresis high edge)
OPEN_DEBOUNCE = 0.09            # eyes must look open this long to count (filters noisy frames)
# Closing is never debounced, and a lost face counts as closed, so tracking glitches never hurt you.

# Detection (same feel as the spotlight game)
EXPOSURE_UP_TIME = 0.22         # seconds open under the manager's gaze before you're caught
EXPOSURE_DOWN_TIME = 0.6        # seconds to cool down when safe
CAUGHT_STUN_SECONDS = 1.0       # after a partial-penalty catch: no gain and no detection

# The manager: durations are (easy, hard) pairs, blended as the round goes on.
INITIAL_SAFE_SECONDS = 2.0      # first safe window, so you can start reading straight away
SAFE_MIN = (2.2, 1.2)           # eyes-down window, shortest
SAFE_MAX = (3.0, 1.8)           # eyes-down window, longest
TELL_SECONDS = (0.9, 0.6)       # warning before they look up
OPEN_MIN = (0.9, 1.0)           # looking-up (danger) window, shortest
OPEN_MAX = (1.3, 1.5)           # looking-up (danger) window, longest
FAKE_TELL_START = 0.8           # fake tells only appear after this fraction of the round
FAKE_TELL_CHANCE = 0.5          # chance that a tell is fake once they are allowed
LID_SPEED = 9.0                 # how fast the manager's eyes animate (visual only)

# Look (computer-drawn defaults; every picture can be replaced by a PNG, see ASSET_FILES)
BG = (12, 14, 26)
FLOOR = (28, 30, 46)
SILHOUETTE = (36, 40, 62)
SILHOUETTE_EDGE = (60, 66, 96)
DESK = (32, 35, 54)
SCREEN_GLOW = (44, 66, 100)
TIE = (150, 50, 60)
PAPER = (46, 50, 74)
PAPER_UNREAD = (60, 66, 96)
GAZE = (255, 248, 200)
DANGER = (230, 60, 60)
WARNING = (255, 90, 90)
SAFE_GREEN = (80, 200, 120)
TEXT = (240, 240, 240)
DIM_ALPHA = 110                 # screen darkness while your own eyes are closed (single player)
DIM_SPEED = 600.0               # alpha units per second for the dim fade

# Text shown to the player
PROGRESS_LABEL = "REVIEW READ"
DETECTION_LABEL = "SUSPICION"
REVIEW_TITLE = "PERFORMANCE REVIEW"
REVIEW_RATING = "MEETS EXPECTATIONS"    # revealed when the whole review has been read
READY_TEXT = "EYES OPEN... CAREFULLY"
WIN_TEXT = "YOU READ IT ALL!"
LOSE_TEXT = "BUSTED!"
CAUGHT_TEXT = "BUSTED!"

# Review page layout (drawn version)
DOC_SIZE = (190, 250)
DOC_TOP = 125
REVIEW_LINE_WIDTHS = (0.9, 0.75, 0.85, 0.6, 0.8, 0.7, 0.5)   # relative length of each text line

# Sprite sizes and positions (used for both the drawn art and PNG replacements)
MANAGER_CENTER_Y = 230
MANAGER_SPRITE_SIZE = (300, 300)
DESK_CENTER_Y = 350
DESK_SPRITE_SIZE = (420, 110)
PLAYER_SPRITE_SIZE = (70, 100)

# Optional PNG replacements: key -> file name inside ASSET_DIR. Missing files fall back to drawing.
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "watcher_peek")
ASSET_FILES = {
    "background": "background.png",          # whole screen (replaces wall + floor)
    "manager_closed": "manager_closed.png",  # eyes down on screen (safe)
    "manager_tell": "manager_tell.png",      # head lifting, glasses flashing (warning)
    "manager_open": "manager_open.png",      # looking up at you (danger)
    "desk": "desk.png",                      # desk in front of the manager (drawn over their body)
    "review_page": "review_page.png",        # the review; unread part is darkened as you read
    "player_open": "player_open.png",        # you, eyes open
    "player_closed": "player_closed.png",    # you, eyes closed
    "player_caught": "player_caught.png",    # you, busted (optional; falls back to player_closed)
}


def _lerp(pair: tuple[float, float], t: float) -> float:
    """Blend an (easy, hard) pair by t in 0..1."""
    return pair[0] + (pair[1] - pair[0]) * max(0.0, min(1.0, t))


class Assets:
    """Loads optional PNG replacements once and hands them out already scaled. Missing = None."""

    def __init__(self, folder: str = ASSET_DIR) -> None:
        self.folder = folder
        self._cache: dict[tuple, pygame.Surface | None] = {}

    def get(self, key: str, size: tuple[int, int]) -> pygame.Surface | None:
        cache_key = (key, size)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._load(key, size)
        return self._cache[cache_key]

    def _load(self, key: str, size: tuple[int, int]) -> pygame.Surface | None:
        if key not in ASSET_FILES:
            return None
        path = os.path.join(self.folder, ASSET_FILES[key])
        if not os.path.isfile(path):
            return None
        try:
            image = pygame.image.load(path).convert_alpha()
            return pygame.transform.smoothscale(image, size)
        except Exception as exc:        # a broken PNG must never crash the game
            print(f"Could not load {path}: {exc!r} - using drawn version")
            return None


class Manager:
    """The on-screen line manager. Shared by all players. Cycles: closed -> tell -> open -> closed."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = "closed"       # "closed" (eyes down, safe), "tell" (warning), "open" (looking up, danger)
        self.timer = 0.0
        self.duration = INITIAL_SAFE_SECONDS
        self.fake = False           # True while a tell will NOT lead to them looking up
        self.lid = 0.0              # 0 = shut, 1 = wide (visual eye position, eased)

    @property
    def dangerous(self) -> bool:
        """True only while the manager is really looking up."""
        return self.phase == "open"

    @property
    def tell_amount(self) -> float:
        """0..1 progress through the tell (0 outside the tell)."""
        return min(1.0, self.timer / self.duration) if self.phase == "tell" else 0.0

    def update(self, dt: float, progress: float) -> None:
        """progress: 0..1 round progress, used for difficulty and for allowing fake tells."""
        self.timer += dt
        if self.timer >= self.duration:
            self._next_phase(progress)
        target = 1.0 if self.phase == "open" else 0.0
        self.lid += (target - self.lid) * min(1.0, LID_SPEED * dt)

    def _next_phase(self, progress: float) -> None:
        self.timer = 0.0
        if self.phase == "closed":
            self.phase = "tell"
            self.duration = _lerp(TELL_SECONDS, progress)
            self.fake = progress >= FAKE_TELL_START and random.random() < FAKE_TELL_CHANCE
        elif self.phase == "tell":
            if self.fake:           # the head twitched but they keep looking at their screen
                self.fake = False
                self._begin_closed(progress)
            else:
                self.phase = "open"
                self.duration = random.uniform(_lerp(OPEN_MIN, progress), _lerp(OPEN_MAX, progress))
        else:
            self._begin_closed(progress)

    def _begin_closed(self, progress: float) -> None:
        self.phase = "closed"
        self.duration = random.uniform(_lerp(SAFE_MIN, progress), _lerp(SAFE_MAX, progress))


@dataclass
class PlayerSlot:
    """Everything that belongs to ONE player. Add a second slot for two-player mode."""
    index: int
    key: int                                     # keyboard fallback: hold to keep eyes open
    open_below: float = DEFAULT_OPEN_BELOW       # closed score under this -> eyes open
    closed_above: float = DEFAULT_CLOSED_ABOVE   # closed score over this -> eyes closed
    key_open: bool = False                       # keyboard fallback state
    raw_open: bool = False                       # hysteresis state from the camera
    open_time: float = 0.0                       # how long raw_open has been true (debounce)
    face_visible: bool = False
    progress: float = 0.0                        # 0..1, reach 1.0 to win
    exposure: float = 0.0                        # 0..1, reach 1.0 = caught
    stun: float = 0.0                            # seconds left of post-catch protection
    alive: bool = True
    open_samples: list = field(default_factory=list)
    closed_samples: list = field(default_factory=list)

    @property
    def eyes_open(self) -> bool:
        """Final open/closed decision used by the game rules."""
        return self.key_open or (self.raw_open and self.open_time >= OPEN_DEBOUNCE)

    def reset_round(self) -> None:
        self.key_open = False
        self.raw_open = False
        self.open_time = 0.0
        self.progress = 0.0
        self.exposure = 0.0
        self.stun = 0.0
        self.alive = True

    def read_eyes(self, closed_score: float | None, dt: float) -> None:
        """Turn a raw closed score into raw_open with hysteresis. None (no face) counts as closed."""
        self.face_visible = closed_score is not None
        if closed_score is None or closed_score >= self.closed_above:
            self.raw_open = False
        elif closed_score <= self.open_below:
            self.raw_open = True
        # between the two thresholds: keep the previous state (stops flicker)
        self.open_time = self.open_time + dt if self.raw_open else 0.0

    def apply_calibration(self) -> None:
        """Set personal thresholds from the open/closed samples collected during calibration."""
        if len(self.open_samples) < 8 or len(self.closed_samples) < 8:
            return
        open_med, closed_med = median(self.open_samples), median(self.closed_samples)
        span = closed_med - open_med
        if span < MIN_CALIBRATION_SPAN:
            return  # readings too similar to trust: keep the defaults
        self.open_below = open_med + 0.35 * span
        self.closed_above = open_med + 0.60 * span


class WatcherPeek(CalibratedMinigame):
    """Read your review while the manager's eyes are down, close your eyes before they look up."""

    title = "Sneak a Look"
    tracker_cls = EyeTracker
    calibrate_timeout = CALIBRATE_TIMEOUT
    after_calibration = "calibrate_closed"   # our second calibration stage, then "ready", then "play"

    def __init__(self, screen: pygame.Surface, tracker: EyeTracker | None = None, *,
                 num_players: int = 1, decay_enabled: bool = PROGRESS_DECAY_ENABLED,
                 penalty_mode: str = CAUGHT_PENALTY_MODE) -> None:
        if penalty_mode not in CAUGHT_PENALTY_FRACTIONS:
            raise ValueError(f"penalty_mode must be one of {list(CAUGHT_PENALTY_FRACTIONS)}")
        owns_two_face_tracker = tracker is None and num_players > 1
        if owns_two_face_tracker:
            tracker = EyeTracker(num_faces=num_players)  # the default tracker_cls() tracks one face
        super().__init__(screen, tracker)
        if owns_two_face_tracker:
            self._owns_tracker = True                    # so close() releases the camera

        self.decay_enabled = decay_enabled
        self.penalty_mode = penalty_mode

        # One slot per player. Keys: P1 = Space, P2 = Enter (keyboard fallback only).
        keys = [pygame.K_SPACE, pygame.K_RETURN]
        self.slots = [PlayerSlot(i, keys[i]) for i in range(num_players)]
        self.manager = Manager()
        self.assets = Assets(ASSET_DIR)
        self._dim_alpha = 0.0
        self._dim_surface: pygame.Surface | None = None
        self._overlay: pygame.Surface | None = None
        self._mask: pygame.Surface | None = None
        self.start()

    # Public API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Eyes Open", "Open your eyes to read the review (or hold SPACE)", self.open_eyes),
            Action("Eyes Closed", "Close your eyes to stay hidden (or release SPACE)", self.close_eyes),
        )

    def start(self) -> None:
        super().start()                  # resets finished/won and begins calibration
        self.elapsed = 0.0
        self.result: bool | None = None  # set when the round is decided; finish() follows END_DELAY later
        self.winner: int | None = None
        self.end_timer = 0.0
        self.ready_t = 0.0
        self.message = ""
        self.message_time = 0.0
        self._dim_alpha = 0.0
        self.manager.reset()
        for slot in self.slots:
            slot.reset_round()

    # Handle input
    def open_eyes(self) -> None:
        self.slots[0].key_open = True

    def close_eyes(self) -> None:
        self.slots[0].key_open = False

    def handle_event(self, event: pygame.event.Event) -> None:
        super().handle_event(event)      # C = recalibrate
        if event.type not in (pygame.KEYDOWN, pygame.KEYUP):
            return
        left, right = self.actions
        for slot in self.slots:
            if event.key != slot.key:
                continue
            is_down = event.type == pygame.KEYDOWN
            if slot.index == 0:
                (left if is_down else right).perform()   # goes through the Action objects
            else:
                slot.key_open = is_down

    # Calibration
    def begin_calibration(self) -> None:
        super().begin_calibration()
        self.closed_time = 0.0
        for slot in self.slots:
            slot.open_samples, slot.closed_samples = [], []

    def _scores(self) -> tuple[float, ...] | None:
        """Closed score for every player, or None if any face is missing (or no eye tracker)."""
        reader = getattr(self.tracker, "closed_for", None)
        if reader is None or not self.tracker.available:
            return None
        scores = tuple(reader(slot.index) for slot in self.slots)
        return None if any(s is None for s in scores) else scores

    def read_sample(self) -> tuple[float, ...] | None:
        """Stage 1 (eyes open): one closed score per player."""
        return self._scores()

    def on_calibrated(self, samples: list) -> None:
        for slot in self.slots:
            slot.open_samples = [s[slot.index] for s in samples]

    def calibration_prompt(self) -> str:
        if self.tracker.available and getattr(self.tracker, "backend", None) is None:
            return "Loading eye tracking (first run downloads a model)..."
        if self._scores() is None:
            return "Look at the camera with your eyes OPEN"
        return "Keep your eyes OPEN"

    def _update_closed_calibration(self, dt: float) -> None:
        """Stage 2: ask the player to close their eyes, then sample how 'closed' looks for them."""
        if not self.tracker.available:
            self.mode = "play"           # no camera: keyboard fallback with default thresholds
            return
        self.closed_time += dt
        if self.closed_time >= CLOSED_PROMPT_SECONDS:
            scores = self._scores()
            if scores is not None:
                for slot in self.slots:
                    slot.closed_samples.append(scores[slot.index])
        if self.closed_time >= CLOSED_PROMPT_SECONDS + CLOSED_SAMPLE_SECONDS:
            for slot in self.slots:
                slot.apply_calibration()
            self.ready_t = 0.0
            self.mode = "ready"

    # Update state
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)                # a long frame (e.g. window dragged) must not skip the rules
        self.message_time = max(0.0, self.message_time - dt)

        if self.result is not None:      # round decided: hold the result on screen briefly
            self.end_timer += dt
            if self.end_timer >= END_DELAY:
                self.finish(self.result)
            return

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return
        if self.mode == "calibrate_closed":
            self._update_closed_calibration(dt)
            return
        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        round_progress = min(1.0, self.elapsed / ROUND_SECONDS)
        self.manager.update(dt, round_progress)

        for slot in self.slots:
            self._read_slot_eyes(slot, dt)
            if slot.alive and self._update_slot(slot, dt):
                self._on_caught(slot)

        self._check_end()

    def _read_slot_eyes(self, slot: PlayerSlot, dt: float) -> None:
        """Camera -> slot. Without a camera the keyboard fallback is the only input."""
        reader = getattr(self.tracker, "closed_for", None)
        score = reader(slot.index) if reader is not None and self.tracker.available else None
        slot.read_eyes(score, dt)

    def _update_slot(self, slot: PlayerSlot, dt: float) -> bool:
        """Apply the rules for one player this frame. Returns True if they were just caught."""
        slot.stun = max(0.0, slot.stun - dt)
        eyes_open = slot.eyes_open
        stunned = slot.stun > 0.0

        # Detection: eyes open while the manager is looking up.
        if eyes_open and self.manager.dangerous and not stunned:
            slot.exposure = min(1.0, slot.exposure + dt / EXPOSURE_UP_TIME)
        else:
            slot.exposure = max(0.0, slot.exposure - dt / EXPOSURE_DOWN_TIME)

        # Progress: fills on safe peeks, optionally drains while eyes are closed.
        if eyes_open and not self.manager.dangerous and not stunned:
            slot.progress = min(1.0, slot.progress + dt / PROGRESS_FILL_SECONDS)
        elif not eyes_open and self.decay_enabled:
            slot.progress = max(0.0, slot.progress - dt / PROGRESS_DECAY_SECONDS)

        return slot.exposure >= 1.0

    def _on_caught(self, slot: PlayerSlot) -> None:
        fraction = CAUGHT_PENALTY_FRACTIONS[self.penalty_mode]
        if fraction >= 1.0:
            slot.alive = False           # full loss: this player is out
            self._flash(CAUGHT_TEXT, 1.5)
            return
        slot.progress *= (1.0 - fraction)  # partial loss: keep playing
        slot.exposure = 0.0
        slot.stun = CAUGHT_STUN_SECONDS
        self._flash(f"{CAUGHT_TEXT} -{int(fraction * 100)}% progress", 1.5)

    def _check_end(self) -> None:
        # Highest progress wins if several fill on the same frame (only matters in 2P).
        done = [s for s in self.slots if s.progress >= 1.0 and s.alive]
        if done:
            self.winner = max(done, key=lambda s: s.progress).index
            self.result = True
        elif not any(s.alive for s in self.slots) or self.elapsed >= ROUND_SECONDS:
            self.result = False

    def _flash(self, text: str, seconds: float) -> None:
        self.message, self.message_time = text, seconds

    # Draw the scene
    def _blit_asset(self, screen: pygame.Surface, keys, center: tuple[int, int],
                    size: tuple[int, int]) -> bool:
        """Draw the first available PNG from `keys` (a name or list of names) centred on `center`."""
        for key in ([keys] if isinstance(keys, str) else keys):
            sprite = self.assets.get(key, size)
            if sprite is not None:
                screen.blit(sprite, (center[0] - size[0] // 2, center[1] - size[1] // 2))
                return True
        return False

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        ground_y = h - 110
        if not self._blit_asset(screen, "background", (w // 2, h // 2), (w, h)):
            screen.fill(BG)
            pygame.draw.rect(screen, FLOOR, (0, ground_y + 40, w, h - ground_y - 40))

        self._draw_manager(screen, w)
        self._draw_desk(screen, w)

        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay = self._overlay
        overlay.fill((0, 0, 0, 0))
        if self.mode == "play" and self.manager.dangerous:
            self._draw_gaze(overlay, w, ground_y)
        screen.blit(overlay, (0, 0))

        for slot in self.slots:
            self._draw_review(screen, slot, w)
            self._draw_player(screen, slot, ground_y, w)

        self._draw_dim(screen, w, h)     # dark screen while your eyes are closed
        self._draw_hud(screen, w, h)

    def _draw_gaze(self, overlay: pygame.Surface, w: int, ground_y: int) -> None:
        """Red wash plus two light cones from the manager's glasses down to the floor."""
        pulse = 18 * math.sin(self.elapsed * 12)
        overlay.fill((255, 40, 40, int(34 + pulse)))
        cx, ey = w // 2, 185
        for side in (-1, 1):
            ex = cx + side * 30
            pygame.draw.polygon(overlay, (*GAZE, 60), [
                (ex - 8, ey), (ex + 8, ey),
                (ex + side * 170 + 90, ground_y + 55), (ex + side * 170 - 90, ground_y + 55)])

    def _draw_manager(self, screen: pygame.Surface, w: int) -> None:
        cx = w // 2
        mgr = self.manager
        keys = {"closed": "manager_closed", "tell": "manager_tell", "open": "manager_open"}
        if self._blit_asset(screen, keys[mgr.phase], (cx, MANAGER_CENTER_Y), MANAGER_SPRITE_SIZE):
            return

        lift = -int(8 * mgr.tell_amount)            # head rises as the tell builds
        # Shoulders, tie and head.
        pygame.draw.polygon(screen, SILHOUETTE, [(cx - 120, 345), (cx - 70, 270), (cx + 70, 270), (cx + 120, 345)])
        pygame.draw.polygon(screen, TIE, [(cx - 8, 274), (cx + 8, 274), (cx + 12, 330), (cx, 345), (cx - 12, 330)])
        pygame.draw.ellipse(screen, SILHOUETTE, (cx - 75, 105 + lift, 150, 170))
        pygame.draw.ellipse(screen, SILHOUETTE_EDGE, (cx - 75, 105 + lift, 150, 170), 3)

        for side in (-1, 1):
            ex, ey = cx + side * 30, 185 + lift
            lens = (ex - 24, ey - 18, 48, 36)
            frame = SILHOUETTE_EDGE
            if mgr.phase == "tell" and int(mgr.timer * 12) % 2 == 0:
                frame = WARNING                     # glasses flash: real and fake tells look identical
            if mgr.phase == "open":
                eye_h = max(4, int(24 * mgr.lid))
                pygame.draw.ellipse(screen, GAZE, (ex - 17, ey - eye_h // 2, 34, eye_h))
                if eye_h > 10:
                    pygame.draw.circle(screen, BG, (ex, ey), 5)
                frame = GAZE
            else:
                pygame.draw.line(screen, SILHOUETTE_EDGE, (ex - 17, ey + 4), (ex + 17, ey + 4), 4)  # eyes down
            pygame.draw.rect(screen, frame, lens, 3, border_radius=10)
        pygame.draw.line(screen, SILHOUETTE_EDGE, (cx - 6, 185 + lift), (cx + 6, 185 + lift), 3)  # glasses bridge

    def _draw_desk(self, screen: pygame.Surface, w: int) -> None:
        """The desk in front of the manager, with a monitor, mug and your review folder on it."""
        cx = w // 2
        if self._blit_asset(screen, "desk", (cx, DESK_CENTER_Y), DESK_SPRITE_SIZE):
            return
        pygame.draw.rect(screen, DESK, (cx - 170, 352, 340, 40))                    # front panel
        pygame.draw.rect(screen, DESK, (cx - 190, 332, 380, 22), border_radius=4)    # desk top
        pygame.draw.rect(screen, SILHOUETTE_EDGE, (cx - 190, 332, 380, 22), 2, border_radius=4)
        pygame.draw.rect(screen, SILHOUETTE_EDGE, (cx + 88, 284, 74, 48), border_radius=4)   # monitor
        pygame.draw.rect(screen, SCREEN_GLOW, (cx + 93, 289, 64, 36), border_radius=2)
        pygame.draw.rect(screen, PAPER_UNREAD, (cx - 62, 322, 54, 10), border_radius=2)      # your review folder
        pygame.draw.rect(screen, SILHOUETTE_EDGE, (cx - 168, 314, 18, 18), border_radius=3)  # mug
        pygame.draw.arc(screen, SILHOUETTE_EDGE, (cx - 154, 317, 12, 11), -math.pi / 2, math.pi / 2, 2)
        pygame.draw.rect(screen, SILHOUETTE_EDGE, (cx - 30, 362, 60, 14), 2, border_radius=2)  # nameplate

    def _doc_rect(self, slot: PlayerSlot, w: int) -> tuple[int, int, int, int]:
        """Where this player's magnified review page sits (left for P1, right for P2)."""
        dw, dh = DOC_SIZE
        count = len(self.slots)
        x = 40 if count == 1 else 30 + int((w - dw - 60) * slot.index / (count - 1))
        return x, DOC_TOP, dw, dh

    def _draw_review(self, screen: pygame.Surface, slot: PlayerSlot, w: int) -> None:
        """The review page you are sneaking a look at. Lines light up as progress fills."""
        x, y, dw, dh = self._doc_rect(slot, w)
        rect = (x, y, dw, dh)
        has_art = self._blit_asset(screen, "review_page", (x + dw // 2, y + dh // 2), (dw, dh))

        if has_art:
            self._draw_unread_mask(screen, rect, slot.progress)
        else:
            pygame.draw.rect(screen, PAPER, rect, border_radius=6)
            draw_text_centered(screen, self.small_font, REVIEW_TITLE, TEXT, (x + dw // 2, y + 18))
            top, count = y + 42, len(REVIEW_LINE_WIDTHS)
            for i, width in enumerate(REVIEW_LINE_WIDTHS):
                ly = top + i * 22
                full = int((dw - 28) * width)
                read = max(0.0, min(1.0, slot.progress * count - i))   # how much of this line is read
                pygame.draw.rect(screen, PAPER_UNREAD, (x + 14, ly, full, 8), border_radius=3)
                if read > 0:
                    pygame.draw.rect(screen, GAZE, (x + 14, ly, int(full * read), 8), border_radius=3)
            done = slot.progress >= 1.0
            draw_text_centered(screen, self.small_font, "RATING:", (200, 200, 200), (x + dw // 2, y + dh - 52))
            draw_text_centered(screen, self.small_font, REVIEW_RATING if done else "???",
                               GAZE if done else WARNING, (x + dw // 2, y + dh - 30))

        # Frame colour tells you at a glance whether this is a safe moment to read.
        edge = SILHOUETTE_EDGE
        if slot.eyes_open and slot.alive:
            edge = DANGER if self.manager.dangerous else SAFE_GREEN
        pygame.draw.rect(screen, edge, rect, 3, border_radius=6)
        if len(self.slots) > 1:
            draw_text_centered(screen, self.small_font, f"P{slot.index + 1}", (200, 200, 200),
                               (x + dw // 2, y + dh + 14))

    def _draw_unread_mask(self, screen: pygame.Surface, rect: tuple[int, int, int, int], progress: float) -> None:
        """For PNG review pages: darken the part of the page that has not been read yet."""
        x, y, dw, dh = rect
        read_h = int(dh * max(0.0, min(1.0, progress)))
        if read_h >= dh:
            return
        if self._mask is None or self._mask.get_size() != (dw, dh):
            self._mask = pygame.Surface((dw, dh), pygame.SRCALPHA)
            self._mask.fill((0, 0, 0, 170))
        screen.blit(self._mask, (x, y + read_h), (0, 0, dw, dh - read_h))

    def _draw_player(self, screen: pygame.Surface, slot: PlayerSlot, ground_y: int, w: int) -> None:
        px = int(w * (slot.index + 1) / (len(self.slots) + 1))
        if not slot.alive:
            keys = ["player_caught", "player_closed"]
        else:
            keys = ["player_open" if slot.eyes_open else "player_closed"]
        if self._blit_asset(screen, keys, (px, ground_y - 10), PLAYER_SPRITE_SIZE):
            return

        e = slot.exposure
        color = (80 + int(175 * e), 200 - int(130 * e), 120 - int(80 * e))
        if not slot.alive:
            color = (90, 90, 100)
        elif slot.stun > 0 and int(slot.stun * 10) % 2:
            color = (200, 200, 220)      # flicker while protected after a catch
        pygame.draw.ellipse(screen, (6, 6, 10), (px - 24, ground_y + 22, 48, 14))
        pygame.draw.rect(screen, color, (px - 16, ground_y - 14, 32, 44), border_radius=8)
        pygame.draw.circle(screen, color, (px, ground_y - 30), 14)
        # Eyes mirror the player's real state.
        for side in (-1, 1):
            ex, ey = px + side * 5, ground_y - 32
            if slot.eyes_open and slot.alive:
                pygame.draw.circle(screen, GAZE, (ex, ey), 3)
            else:
                pygame.draw.line(screen, BG, (ex - 3, ey), (ex + 3, ey), 2)

    def _draw_dim(self, screen: pygame.Surface, w: int, h: int) -> None:
        """Darken the view while the (single) player's eyes are closed. Skipped in multiplayer."""
        if len(self.slots) != 1 or self.mode != "play":
            return
        target = 0.0 if self.slots[0].eyes_open else float(DIM_ALPHA)
        step = DIM_SPEED / 60.0
        self._dim_alpha += max(-step, min(step, target - self._dim_alpha))
        if self._dim_alpha > 1:
            if self._dim_surface is None or self._dim_surface.get_size() != (w, h):
                self._dim_surface = pygame.Surface((w, h), pygame.SRCALPHA)
            self._dim_surface.fill((0, 0, 0, int(self._dim_alpha)))
            screen.blit(self._dim_surface, (0, 0))

    def _draw_meter(self, screen: pygame.Surface, cx: int, y: int, frac: float,
                    color: tuple[int, int, int], label: str) -> None:
        draw_bar(screen, (cx - 100, y, 200, 12), frac, color)
        draw_text_centered(screen, self.small_font, label, (200, 200, 200), (cx, y + 12 + 12))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        remaining = max(0.0, ROUND_SECONDS - self.elapsed)
        screen.blit(self.font.render(f"{remaining:.1f}s", True, TEXT), (10, 10))

        for slot in self.slots:
            cx = int(w * (slot.index + 1) / (len(self.slots) + 1))
            label = PROGRESS_LABEL if len(self.slots) == 1 else f"P{slot.index + 1} {PROGRESS_LABEL}"
            self._draw_meter(screen, cx, 14, slot.progress, SAFE_GREEN, label)
            self._draw_meter(screen, cx, 58, slot.exposure, DANGER, DETECTION_LABEL)

        draw_camera_preview(screen, self.tracker)

        decay = "on" if self.decay_enabled else "off"
        if self.tracker.available:
            backend = getattr(self.tracker, "backend", None) or "loading"
            info = f"Eye tracking: {backend} | decay {decay} | penalty {self.penalty_mode} (C = recalibrate)"
        else:
            info = f"No camera - hold SPACE to open eyes | decay {decay} | penalty {self.penalty_mode}"
        draw_status_line(screen, self.small_font, info)

        if self.mode == "calibrate":
            self.draw_calibration(screen)
        elif self.mode == "calibrate_closed":
            self._draw_closed_calibration(screen, w, h)
        elif self.mode == "ready":
            draw_text_centered(screen, self.big_font, READY_TEXT, SAFE_GREEN, (w // 2, h // 2))
        elif self.tracker.available and any(not s.face_visible for s in self.slots if s.alive):
            draw_text_centered(screen, self.font, "Face lost! (counts as eyes closed)", (255, 160, 60),
                               (w // 2, h // 2 + 40))

        if self.result is not None:
            msg, col = (WIN_TEXT, SAFE_GREEN) if self.result else (LOSE_TEXT, DANGER)
            draw_text_centered(screen, self.big_font, msg, col, (w // 2, h // 2 + 80))
        elif self.message_time > 0:
            draw_text_centered(screen, self.font, self.message, WARNING, (w // 2, h // 2 + 80))

    def _draw_closed_calibration(self, screen: pygame.Surface, w: int, h: int) -> None:
        sampling = self.closed_time >= CLOSED_PROMPT_SECONDS
        prompt = "Keep them shut..." if sampling else "Now CLOSE your eyes and keep them shut"
        draw_text_centered(screen, self.font, prompt, TEXT, (w // 2, h // 2 - 60))
        total = CLOSED_PROMPT_SECONDS + CLOSED_SAMPLE_SECONDS
        draw_bar(screen, (w // 2 - 120, h // 2 - 20, 240, 12), self.closed_time / total, SAFE_GREEN)
