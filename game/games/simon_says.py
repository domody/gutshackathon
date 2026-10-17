from __future__ import annotations

import math
import random

import pygame

from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered


TARGET_COMMANDS = 8

# Time per command ramps from START to END over the round.
TIME_START, TIME_END = 2.6, 1.6
FAST_TIME_START, FAST_TIME_END = 1.9, 1.2
COMBO_TIME_FACTOR = 0.85     # combo gets (poses x base x this) seconds
HOLD_TIME = 0.30             # how long a pose must be held to count
FAST_HOLD_TIME = 0.22
OPPOSITE_CHANCE = 0.4        # chance a command is "opposite" (once enabled, after 2 commands)

# Pose detection (relative to the calibrated neutral)
YAW_THRESH = 0.6             # fraction of a full turn (tracker.scale)
TILT_THRESH = 14.0           # degrees

READY_SECONDS = 1.0
FLASH_SECONDS = 0.35
SIM_SECONDS = 0.45           # keyboard fallback: how long a key press "holds" a pose

# pose id -> (label, avatar yaw -1..1, avatar roll degrees)
POSES = {
    "left": ("TURN LEFT", -1.0, 0.0),
    "right": ("TURN RIGHT", 1.0, 0.0),
    "tilt_left": ("TILT LEFT", 0.0, -28.0),
    "tilt_right": ("TILT RIGHT", 0.0, 28.0),
}
OPPOSITE = {"left": "right", "right": "left", "tilt_left": "tilt_right", "tilt_right": "tilt_left"}
FLASH_WORDS = ("NICE!", "YES!", "GOOD!", "BOOM!", "SMOOTH!")

# (attribute, label, description) for menus
CHALLENGES = (
    ("fast", "Fast", "Shorter time for every command"),
    ("opposite", "Opposite", "Red commands: do the OPPOSITE pose"),
    ("combo", "Combo", "Two poses in a row, in order"),
)

BG = (18, 18, 34)
TARGET_COLOR = (245, 205, 110)
OPPOSITE_COLOR = (250, 120, 120)
DONE_COLOR = (110, 210, 130)
YOU_COLOR = (125, 195, 255)
DARK = (25, 25, 35)


def classify(yaw_off: float, roll_off: float) -> str | None:
    """Turn offsets from neutral into a pose id (or None when roughly neutral)."""
    yn, rn = abs(yaw_off) / YAW_THRESH, abs(roll_off) / TILT_THRESH
    if max(yn, rn) < 1.0:
        return None
    if yn >= rn:
        return "right" if yaw_off > 0 else "left"
    return "tilt_right" if roll_off > 0 else "tilt_left"


class simonsays(FaceMinigame):
    """Copy the pose on the left with your head before the time bar empties."""

    title = "simon says"
    after_calibration = "ready"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None, *,
                 fast: bool = False, opposite: bool = False, combo: bool = False) -> None:
        super().__init__(screen, tracker)
        self.fast, self.opposite, self.combo = fast, opposite, combo
        self.start()

    # Public API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Turn Head", "Turn your head left or right to match the pose (or A / D)",
                   self.turn_head),
            Action("Tilt Head", "Tilt your head left or right to match the pose (or Q / E)",
                   self.tilt_head),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.done = 0
        self.ready_t = 0.0

        self.current: str | None = None      # pose the player is doing right now
        self.you_yaw = self.you_roll = 0.0   # live avatar target
        self.vis_yaw = self.vis_roll = 0.0   # avatar as drawn (smoothed)
        self.sim_pose: str | None = None
        self.sim_time = 0.0

        self.flash_t = 0.0
        self.flash_word = FLASH_WORDS[0]
        self.last_required: str | None = None
        self.cmd: dict = {"required": ["left"], "shown": ["left"], "opposite": False}
        self.idx = 0
        self.hold = 0.0
        self.time_left = self.time_limit = 1.0
        self._new_command()

    # Handle input
    def turn_head(self) -> None:
        self._sim("right" if self.sim_pose == "left" else "left")

    def tilt_head(self) -> None:
        self._sim("tilt_right" if self.sim_pose == "tilt_left" else "tilt_left")

    def _sim(self, pose: str) -> None:
        self.sim_pose, self.sim_time = pose, SIM_SECONDS

    def handle_event(self, event: pygame.event.Event) -> None:
        super().handle_event(event)
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_a, pygame.K_LEFT):
            self._sim("left")
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            self._sim("right")
        elif event.key == pygame.K_q:
            self._sim("tilt_left")
        elif event.key == pygame.K_e:
            self._sim("tilt_right")

    # Command selection
    def _pose_pool(self) -> tuple[str, ...]:
        if self.tracker.available and not self.tracker.has_roll:
            return ("left", "right")  # fallback tracker can't see tilt
        return tuple(POSES)

    def _new_command(self) -> None:
        progress = min(1.0, self.done / max(1, TARGET_COMMANDS - 1))
        t0, t1 = (FAST_TIME_START, FAST_TIME_END) if self.fast else (TIME_START, TIME_END)
        base = t0 + (t1 - t0) * progress

        count = 2 if self.combo and self.done >= 1 else 1
        pool = self._pose_pool()
        required: list[str] = []
        prev = self.last_required
        for _ in range(count):
            # never ask for the pose the player is probably already in
            pick = random.choice([p for p in pool if p != prev])
            required.append(pick)
            prev = pick

        opposite = self.opposite and self.done >= 2 and random.random() < OPPOSITE_CHANCE
        shown = [OPPOSITE[p] for p in required] if opposite else list(required)

        self.cmd = {"required": required, "shown": shown, "opposite": opposite}
        self.idx = 0
        self.hold = 0.0
        self.last_required = required[-1]
        self.time_limit = base * (1 if count == 1 else count * COMBO_TIME_FACTOR)
        self.time_left = self.time_limit

    # Update state
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.flash_t = max(0.0, self.flash_t - dt)
        blend = min(1.0, 14.0 * dt)
        self.vis_yaw += (self.you_yaw - self.vis_yaw) * blend
        self.vis_roll += (self.you_roll - self.vis_roll) * blend

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        self._read_pose(dt)
        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        self._check_pose(dt)

    def _read_pose(self, dt: float) -> None:
        if self.sim_time > 0 and self.sim_pose:        # keyboard fallback
            self.sim_time -= dt
            _, self.you_yaw, self.you_roll = POSES[self.sim_pose]
            self.current = self.sim_pose
            return

        offsets = self.read_offsets()
        if offsets is None:
            self.current = None
            self.you_yaw *= 0.9
            self.you_roll *= 0.9
            return

        yaw_off, roll_off = offsets
        self.you_yaw = max(-1.0, min(1.0, yaw_off))
        self.you_roll = max(-30.0, min(30.0, roll_off))
        self.current = classify(yaw_off, roll_off)

    def _check_pose(self, dt: float) -> None:
        required = self.cmd["required"][self.idx]
        if self.current == required:
            self.hold += dt
        else:
            self.hold = max(0.0, self.hold - 3.0 * dt)  # forgive a flicker

        if self.hold >= (FAST_HOLD_TIME if self.fast else HOLD_TIME):
            self.idx += 1
            self.hold = 0.0
            self.flash_t = FLASH_SECONDS
            self.flash_word = random.choice(FLASH_WORDS)
            if self.idx >= len(self.cmd["required"]):
                self.done += 1
                if self.done >= TARGET_COMMANDS:
                    self.finish(True)
                else:
                    self._new_command()
            return

        self.time_left -= dt
        if self.time_left <= 0.0:
            self.time_left = 0.0
            self.finish(False)

    # Draw the scene
    def _draw_face(self, screen: pygame.Surface, cx: int, cy: int, r: int,
                   yaw: float, roll: float, color: tuple[int, int, int]) -> None:
        """Cartoon head. yaw -1..1 shifts the features, roll tilts the whole head."""
        a = math.radians(roll)
        ca, sa = math.cos(a), math.sin(a)

        def pt(x: float, y: float) -> tuple[int, int]:
            px, py = x * r, y * r
            return int(cx + px * ca - py * sa), int(cy + px * sa + py * ca)

        shift = 0.38 * yaw
        pygame.draw.polygon(screen, DARK, [pt(-0.14, -0.96), pt(0.0, -1.28), pt(0.14, -0.96)])
        pygame.draw.circle(screen, color, (cx, cy), r)
        pygame.draw.circle(screen, DARK, (cx, cy), r, 4)
        for side in (-1, 1):
            ex, ey = pt(side * 0.35 + shift, -0.18)
            pygame.draw.circle(screen, DARK, (ex, ey), max(3, int(r * 0.13 * (1 + 0.3 * side * yaw))))
        nx, ny = pt(shift * 1.5, 0.08)
        pygame.draw.circle(screen, DARK, (nx, ny), max(3, int(r * 0.07)))
        mouth = [pt(shift + x * 0.3, 0.42 + 0.10 * (1 - x * x)) for x in (-1, -0.5, 0, 0.5, 1)]
        pygame.draw.lines(screen, DARK, False, mouth, max(2, int(r * 0.04)))

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        screen.fill(BG)
        self._draw_hud(screen, w, h)

        if self.mode == "calibrate":
            self.draw_calibration(screen)
            return

        lx, rx, cy = int(w * 0.29), int(w * 0.72), 270

        # --- you ---
        required = self.cmd["required"][min(self.idx, len(self.cmd["required"]) - 1)]
        matching = self.mode == "play" and self.current == required
        self._draw_face(screen, rx, cy, 100, self.vis_yaw, self.vis_roll, YOU_COLOR)
        if matching:
            pygame.draw.circle(screen, DONE_COLOR, (rx, cy), 112, 6)
        draw_text_centered(screen, self.font, "YOU", (200, 200, 210), (rx, cy + 135))

        if self.mode == "ready":
            draw_text_centered(screen, self.big_font, "GET READY!", (240, 240, 240), (lx + 40, cy))
            return

        # --- target pose(s) ---
        shown, count = self.cmd["shown"], len(self.cmd["shown"])
        opposite = self.cmd["opposite"]
        radius = 100 if count == 1 else 72
        for i, pose in enumerate(shown):
            x = lx if count == 1 else lx - 85 + i * 170
            _, yaw, roll = POSES[pose]
            if i < self.idx:
                color = DONE_COLOR
            else:
                color = OPPOSITE_COLOR if opposite else TARGET_COLOR
            self._draw_face(screen, x, cy, radius, yaw, roll, color)
            if i == self.idx:
                pygame.draw.circle(screen, (255, 255, 255), (x, cy), radius + 12, 4)
        labels = "  >  ".join(POSES[p][0] for p in shown)
        draw_text_centered(screen, self.font, labels, OPPOSITE_COLOR if opposite else (240, 240, 240),
                   (lx, cy + 135))

        if opposite and int(self.elapsed * 6) % 2 == 0:
            draw_text_centered(screen, self.big_font, "DO THE OPPOSITE!", (255, 90, 90), (w // 2, 85))

        # "=" between the faces, slashed out when it's an opposite command
        mx = (lx + rx) // 2
        pygame.draw.line(screen, (230, 230, 230), (mx - 25, cy - 10), (mx + 25, cy - 10), 5)
        pygame.draw.line(screen, (230, 230, 230), (mx - 25, cy + 10), (mx + 25, cy + 10), 5)
        if opposite:
            pygame.draw.line(screen, (255, 90, 90), (mx - 30, cy + 32), (mx + 30, cy - 32), 6)

        # --- hold meter under you, time bar along the bottom ---
        need = FAST_HOLD_TIME if self.fast else HOLD_TIME
        draw_bar(screen, (rx - 80, cy + 160, 160, 10), self.hold / need, DONE_COLOR)

        frac = max(0.0, self.time_left / self.time_limit)
        bar_color = DONE_COLOR if frac > 0.5 else (240, 180, 60) if frac > 0.25 else (235, 70, 70)
        bx, by, bw, bh = 120, h - 62, w - 240, 26
        draw_bar(screen, (bx, by, bw, bh), frac, bar_color, radius=8)

        if self.flash_t > 0:
            draw_text_centered(screen, self.big_font, self.flash_word, DONE_COLOR, (rx, cy - 140))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        screen.blit(self.font.render(f"{self.done} / {TARGET_COMMANDS}", True, (240, 240, 240)), (10, 10))

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = f"Pose tracking: {self.tracker.backend}   (C = recentre)"
        else:
            info = "No camera tracking - keyboard: A/D turn, Q/E tilt"
        draw_status_line(screen, self.small_font, info)

        tags = [label.upper() for attr, label, _ in CHALLENGES if getattr(self, attr)]
        if tags:
            tag = self.small_font.render("  ".join(tags), True, (240, 180, 60))
            screen.blit(tag, (10, 40))

        self.draw_face_lost(screen, 40)
