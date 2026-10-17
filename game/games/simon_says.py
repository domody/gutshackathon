from __future__ import annotations

import math
import random

import pygame

from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

TARGET_TURNS = 9
READY_SECONDS = 1.4
HOLD_SECONDS = 1.35
SPEAK_SECONDS = 2.8
TURN_SECONDS = 5.2
SIDE_THRESHOLD = 0.48

NAVY = (7, 34, 66)
CHASE_BLUE = (17, 92, 170)
CHASE_LIGHT = (77, 157, 224)
BROWN = (92, 62, 45)
WOOD = (130, 91, 62)
WALL = (224, 226, 222)
FLOOR = (177, 158, 139)
INK = (25, 35, 46)
WHITE = (248, 248, 244)
GREEN = (69, 173, 113)
AMBER = (244, 177, 72)
RED = (210, 78, 66)

<<<<<<< HEAD
# Command time decreases from its starting value to its ending value over the round.
TIME_START, TIME_END = 2.6, 1.6
FAST_TIME_START, FAST_TIME_END = 1.9, 1.2
COMBO_TIME_FACTOR = 0.85  # Multiplier applied to the total time for a pose combo.
HOLD_TIME = 0.30  # Seconds a pose must be held to count.
FAST_HOLD_TIME = 0.22
OPPOSITE_CHANCE = 0.4  # Chance to reverse a command after the first two commands.

# Pose thresholds are measured relative to the calibrated neutral position.
YAW_THRESH = 0.6  # Yaw change as a fraction of the tracker's full-turn scale.
TILT_THRESH = 14.0  # Minimum head tilt in degrees.

READY_SECONDS = 1.0
FLASH_SECONDS = 0.35
# Each pose maps to its label, avatar yaw from -1 to 1 and avatar roll in degrees.
POSES = {
    "left": ("TURN LEFT", -1.0, 0.0),
    "right": ("TURN RIGHT", 1.0, 0.0),
    "tilt_left": ("TILT LEFT", 0.0, -28.0),
    "tilt_right": ("TILT RIGHT", 0.0, 28.0),
}
OPPOSITE = {"left": "right", "right": "left", "tilt_left": "tilt_right", "tilt_right": "tilt_left"}
FLASH_WORDS = ("NICE!", "YES!", "GOOD!", "BOOM!", "SMOOTH!")

# Challenge setting name, display label and description.
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

    title = "Simon Says"
=======
SPEECH = {
    "left": ("Quick update from my side...", "Can everyone see my screen?",
             "I'll circle back on that.", "One tiny blocker..."),
    "forward": ("Let's align on priorities.", "This should only take a minute.",
                "Moving to the next slide...", "Any questions before we start?"),
    "right": ("Just to build on that...", "I have one quick thought.",
              "Could we take this offline?", "You're still on mute."),
}
NAMES = {"left": "MAYA", "forward": "PRESENTER", "right": "JAMIE"}
def classify_direction(yaw_off: float) -> str:
    if yaw_off <= -SIDE_THRESHOLD:
        return "left"
    if yaw_off >= SIDE_THRESHOLD:
        return "right"
    return "forward"


class simonsays(FaceMinigame):
    title = "Who's Talking?"
>>>>>>> e5a16ac (Meeting game v1)
    after_calibration = "ready"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None, *,
                 fast: bool = False, opposite: bool = False, combo: bool = False) -> None:
        super().__init__(screen, tracker)
        self.fast = fast
        self.opposite = opposite
        self.combo = combo
        self.start()

<<<<<<< HEAD
    # Actions shown on the game intro screen.
=======
>>>>>>> e5a16ac (Meeting game v1)
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Look Around", "Turn your head left or right toward the person speaking"),
            Action("Face Forward", "Return to the centre when the presenter is speaking"),
        )

    def start(self) -> None:
        super().start()
        self.done = 0
        self.ready_t = 0.0
<<<<<<< HEAD

        self.current: str | None = None  # Pose currently detected for the player.
        self.you_yaw = self.you_roll = 0.0  # Target yaw and roll for the player's avatar.
        self.vis_yaw = self.vis_roll = 0.0  # Smoothed yaw and roll used to draw the avatar.

        self.flash_t = 0.0
        self.flash_word = FLASH_WORDS[0]
        self.last_required: str | None = None
        self.cmd: dict = {"required": ["left"], "shown": ["left"], "opposite": False}
        self.idx = 0
=======
        self.turn_left = TURN_SECONDS
>>>>>>> e5a16ac (Meeting game v1)
        self.hold = 0.0
        self.current = "forward"
        self.speaker = "forward"
        self.previous_speaker = "forward"
        self.line = random.choice(SPEECH["forward"])
        self.talking_t = 0.0
        self.feedback = ""
        self.feedback_t = 0.0
        self._new_speaker(first=True)

<<<<<<< HEAD
    # Choose poses and timing for each command.
    def _pose_pool(self) -> tuple[str, ...]:
        if self.tracker.available and not self.tracker.has_roll:
            return ("left", "right")  # This tracker cannot detect head tilt.
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
            # Avoid asking for the pose the player most recently held.
            pick = random.choice([p for p in pool if p != prev])
            required.append(pick)
            prev = pick

        opposite = self.opposite and self.done >= 2 and random.random() < OPPOSITE_CHANCE
        shown = [OPPOSITE[p] for p in required] if opposite else list(required)

        self.cmd = {"required": required, "shown": shown, "opposite": opposite}
        self.idx = 0
=======
    def _new_speaker(self, first: bool = False) -> None:
        choices = [d for d in ("left", "forward", "right") if d != self.previous_speaker]
        self.speaker = "forward" if first else random.choice(choices)
        self.previous_speaker = self.speaker
        self.line = random.choice(SPEECH[self.speaker])
        self.turn_left = TURN_SECONDS * (0.82 if self.fast else 1.0) + (1.0 if first else 0.0)
>>>>>>> e5a16ac (Meeting game v1)
        self.hold = 0.0
        self.talking_t = 0.0

<<<<<<< HEAD
    # Update pose detection, command timing and progress.
=======
>>>>>>> e5a16ac (Meeting game v1)
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.feedback_t = max(0.0, self.feedback_t - dt)
        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        offsets = self.read_offsets()
        if offsets is None and self.tracker.available:
            return
        if offsets is not None:
            self.current = classify_direction(offsets[0])

        self.talking_t += dt
        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        if self.current == self.speaker:
            self.hold += dt
        else:
<<<<<<< HEAD
            self.hold = max(0.0, self.hold - 3.0 * dt)  # Reduce the timer gradually to tolerate brief detection gaps.
=======
            self.hold = max(0.0, self.hold - dt * 2.5)
>>>>>>> e5a16ac (Meeting game v1)

        if self.hold >= HOLD_SECONDS and self.talking_t >= SPEAK_SECONDS:
            self.done += 1
            self.feedback = random.choice(("NATURAL.", "GOOD LISTENING.", "NAILED IT."))
            self.feedback_t = 0.65
            if self.done >= TARGET_TURNS:
                self.finish(True)
            else:
                self._new_speaker()
            return

        self.turn_left -= dt
        if self.turn_left <= 0.0:
            self.feedback = "WRONG PERSON."
            self.finish(False)

<<<<<<< HEAD
    # Draw the player, target poses and progress.
    def _draw_face(self, screen: pygame.Surface, cx: int, cy: int, r: int,
                   yaw: float, roll: float, color: tuple[int, int, int]) -> None:
        """Cartoon head. yaw -1..1 shifts the features, roll tilts the whole head."""
        a = math.radians(roll)
        ca, sa = math.cos(a), math.sin(a)
=======
    def _draw_room(self, screen: pygame.Surface, w: int, h: int) -> None:
        screen.fill(WALL)
        pygame.draw.rect(screen, NAVY, (0, 0, w, 72))
        pygame.draw.rect(screen, (205, 207, 201), (0, 72, w, 315))
        pygame.draw.rect(screen, FLOOR, (0, 387, w, h - 387))
        pygame.draw.line(screen, (155, 137, 121), (0, 387), (w, 387), 4)
        pygame.draw.rect(screen, (238, 239, 235), (310, 92, 180, 108), border_radius=5)
        pygame.draw.rect(screen, CHASE_BLUE, (320, 102, 160, 88), border_radius=3)
        pygame.draw.lines(screen, WHITE, False, [(342, 162), (376, 132), (410, 153), (454, 116)], 5)
        pygame.draw.ellipse(screen, BROWN, (65, 414, w - 130, 176))
        pygame.draw.ellipse(screen, WOOD, (65, 396, w - 130, 160))
        pygame.draw.ellipse(screen, (159, 113, 76), (86, 415, w - 172, 116), 3)
        pygame.draw.rect(screen, (235, 237, 232), (325, 435, 150, 76), border_radius=5)
        for y in range(449, 499, 12):
            pygame.draw.line(screen, (174, 179, 181), (340, y), (460, y), 2)
>>>>>>> e5a16ac (Meeting game v1)

    def _draw_person(self, screen: pygame.Surface, x: int, base_y: int, active: bool,
                     phase: float, jacket: tuple[int, int, int], name: str) -> None:
        bounce = int(math.sin(phase * 10.0) * 3) if active else int(math.sin(phase * 2.0 + x))
        y = base_y + bounce
        pygame.draw.ellipse(screen, (53, 56, 63), (x - 46, y + 76, 92, 23))
        pygame.draw.rect(screen, jacket, (x - 43, y + 28, 86, 74), border_radius=18)
        pygame.draw.polygon(screen, WHITE, [(x - 13, y + 29), (x, y + 62), (x + 13, y + 29)])
        pygame.draw.circle(screen, (212, 164, 126), (x, y), 34)
        pygame.draw.arc(screen, (64, 44, 35), (x - 35, y - 36, 70, 60), math.pi, math.tau, 12)
        pygame.draw.circle(screen, INK, (x - 11, y - 4), 3)
        pygame.draw.circle(screen, INK, (x + 11, y - 4), 3)
        if active:
            mouth_h = 6 + int((math.sin(phase * 18.0) + 1.0) * 3)
            pygame.draw.ellipse(screen, INK, (x - 8, y + 12, 16, mouth_h))
            pygame.draw.circle(screen, AMBER, (x, y), 43, 4)
        else:
            pygame.draw.line(screen, INK, (x - 7, y + 15), (x + 7, y + 15), 2)
        label = self.small_font.render(name, True, WHITE)
        rect = (x - label.get_width() // 2 - 7, y + 105, label.get_width() + 14, 24)
        pygame.draw.rect(screen, NAVY, rect, border_radius=6)
        screen.blit(label, (x - label.get_width() // 2, y + 108))

    def _draw_bubble(self, screen: pygame.Surface, x: int, text: str) -> None:
        font = self.small_font
        surf = font.render(text, True, INK)
        bw = min(238, surf.get_width() + 28)
        bx = max(8, min(screen.get_width() - bw - 8, x - bw // 2))
        by = 82 if x != 400 else 210
        pygame.draw.rect(screen, WHITE, (bx, by, bw, 48), border_radius=12)
        pygame.draw.rect(screen, CHASE_BLUE, (bx, by, bw, 48), 3, border_radius=12)
        tip_x = max(bx + 22, min(bx + bw - 22, x))
        pygame.draw.polygon(screen, WHITE, [(tip_x - 11, by + 46), (tip_x + 11, by + 46), (x, by + 61)])
        pygame.draw.lines(screen, CHASE_BLUE, False,
                          [(tip_x - 11, by + 46), (x, by + 61), (tip_x + 11, by + 46)], 3)
        clipped = text
        while font.size(clipped)[0] > bw - 20 and len(clipped) > 4:
            clipped = clipped[:-4] + "..."
        draw_text_centered(screen, font, clipped, INK, (bx + bw // 2, by + 24))

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        positions = {"left": int(w * 0.14), "forward": w // 2, "right": int(w * 0.86)}
        self._draw_room(screen, w, h)
        screen.blit(self.font.render("WHO'S TALKING?", True, WHITE), (18, 20))
        screen.blit(self.small_font.render(f"LISTENED  {self.done}/{TARGET_TURNS}", True, WHITE), (18, 50))

        if self.mode == "calibrate":
            self.draw_calibration(screen)
            draw_camera_preview(screen, self.tracker)
            return

<<<<<<< HEAD
        lx, rx, cy = int(w * 0.29), int(w * 0.72), 270

        # Draw the player's avatar.
        required = self.cmd["required"][min(self.idx, len(self.cmd["required"]) - 1)]
        matching = self.mode == "play" and self.current == required
        self._draw_face(screen, rx, cy, 100, self.vis_yaw, self.vis_roll, YOU_COLOR)
        if matching:
            pygame.draw.circle(screen, DONE_COLOR, (rx, cy), 112, 6)
        draw_text_centered(screen, self.font, "YOU", (200, 200, 210), (rx, cy + 135))

        if self.mode == "ready":
            draw_text_centered(screen, self.big_font, "GET READY!", (240, 240, 240), (lx + 40, cy))
            return

        # Draw the requested pose or pose sequence.
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

        # Show whether the displayed pose matches or opposes the requested pose.
        mx = (lx + rx) // 2
        pygame.draw.line(screen, (230, 230, 230), (mx - 25, cy - 10), (mx + 25, cy - 10), 5)
        pygame.draw.line(screen, (230, 230, 230), (mx - 25, cy + 10), (mx + 25, cy + 10), 5)
        if opposite:
            pygame.draw.line(screen, (255, 90, 90), (mx - 30, cy + 32), (mx + 30, cy - 32), 6)

        # Show the hold meter under the player and the timer along the bottom.
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
            info = f"Pose tracking: {self.tracker.backend}"
=======
        for direction, jacket in (("left", (92, 64, 48)), ("forward", CHASE_BLUE),
                                  ("right", (62, 94, 112))):
            self._draw_person(screen, positions[direction], 300, direction == self.speaker,
                              self.talking_t, jacket, NAMES[direction])
        self._draw_bubble(screen, positions[self.speaker], self.line)

        if self.mode == "ready":
            pygame.draw.rect(screen, NAVY, (165, 236, 470, 82), border_radius=16)
            draw_text_centered(screen, self.font, "WATCH WHO'S SPEAKING", WHITE, (w // 2, 260))
            draw_text_centered(screen, self.small_font, "Turn left, right, or face forward", CHASE_LIGHT,
                               (w // 2, 294))
>>>>>>> e5a16ac (Meeting game v1)
        else:
            total = TURN_SECONDS * (0.82 if self.fast else 1.0) + (1.0 if self.done == 0 else 0.0)
            frac = max(0.0, self.turn_left / total)
            draw_bar(screen, (w // 2 - 150, 365, 300, 12), frac, GREEN if frac > 0.35 else RED,
                     back=(167, 169, 164), radius=6)
            direction = {"left": "LOOK LEFT", "forward": "LOOK FORWARD", "right": "LOOK RIGHT"}[self.speaker]
            draw_text_centered(screen, self.font, direction, NAVY, (w // 2, 348))
            attention = min(self.hold / HOLD_SECONDS, self.talking_t / SPEAK_SECONDS)
            draw_bar(screen, (w // 2 - 75, 382, 150, 7), attention, CHASE_BLUE,
                     back=(190, 191, 186), radius=4)

        if self.feedback_t > 0:
            draw_text_centered(screen, self.font, self.feedback, GREEN, (w // 2, 220))
        draw_camera_preview(screen, self.tracker)
        info = f"Face tracking: {self.tracker.backend}" if self.tracker.available else "Camera tracking unavailable"
        draw_status_line(screen, self.small_font, info)
        self.draw_face_lost(screen, 76)
