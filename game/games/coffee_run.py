"""Coffee Run. Difficulty settings (constants below):

    Main dials
      HEAD_GAIN      cup degrees per head degree   lower = harder
      SAFE_ROLL      lean allowed before spilling  lower = harder

    Other knobs
      WOBBLE_ROLL    how hard the hand swings      higher = harder
      SPILL_RATE     coffee lost just past ring    higher = harder
      SPILL_SPEED_UP extra loss the further past   higher = harder
      JOLT_EVERY     seconds between jolts         lower = harder
      JOLT_SIZE      size of each jolt (degrees)   higher = harder
      DURATION       seconds to survive            higher = harder

    Harder example: HEAD_GAIN = 1.2, SAFE_ROLL = 16
"""
from __future__ import annotations

import math
import random

import pygame

from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered


DURATION = 16.0              # seconds to carry the coffee
READY_SECONDS = 1.5
SIM_SECONDS = 0.45           # keyboard fallback: how long a key press "holds" a tilt

# Hand wobble (the hand drifts and gets jolted; tilt your head to correct it)
HEAD_GAIN = 1.6              # hand degrees per head degree
SAFE_ROLL = 21.0             # degrees of lean before coffee slops out
SAFE_YAW = 0.5               # only used to draw the rim
WOBBLE_ROLL = 36.0
JOLT_EVERY = (2.5, 4.0)
JOLT_SIZE = (6.0, 10.0)
SPILL_RATE = 0.18            # coffee lost per second just past the edge
SPILL_SPEED_UP = 0.5         # extra spill per unit of overshoot

# keyboard fallback: pose -> head roll degrees
SIM_POSES = {"tilt_left": -14.0, "tilt_right": 14.0}

BG = (28, 22, 30)
FLOOR = (44, 34, 40)
SKIN = (238, 192, 150)
SKIN_SHADE = (205, 156, 118)
SLEEVE = (70, 90, 150)
CUP = (245, 245, 250)
CUP_SHADE = (215, 215, 225)
SLEEVE_BAND = (200, 90, 80)
COFFEE = (110, 66, 38)
COFFEE_TOP = (140, 88, 52)
GOOD = (110, 210, 130)
WARN = (240, 180, 60)
BAD = (235, 70, 70)
DARK = (25, 25, 35)


def lerp_color(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class CoffeeRun(FaceMinigame):
    """Tilt your head to keep the wobbling cup level. Don't spill the coffee."""

    title = "coffee run"
    after_calibration = "ready"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.start()

    # Public API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Tilt Left", "Tilt your head left to correct the cup (or A / Q)", self.tilt_left),
            Action("Tilt Right", "Tilt your head right to correct the cup (or D / E)", self.tilt_right),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.ready_t = 0.0
        self.coffee = 1.0
        self.spilled = 0.0

        self.you_roll = 0.0     # head tilt (target)
        self.vis_roll = 0.0     # head tilt (smoothed)
        self.sim_pose: str | None = None
        self.sim_time = 0.0

        self.lean_roll = 0.0    # resulting hand lean
        self.lean_yaw = 0.0
        self.phases = [random.uniform(0, math.tau) for _ in range(2)]
        self.freqs = [random.uniform(0.45, 0.7), random.uniform(0.9, 1.3)]
        self.jolt_roll = 0.0
        self.jolt_t = random.uniform(*JOLT_EVERY)
        self.drops: list[list[float]] = []   # x, y, vx, vy, life
        self.drop_acc = 0.0

    # Handle input
    def tilt_left(self) -> None:
        self._sim("tilt_left")

    def tilt_right(self) -> None:
        self._sim("tilt_right")

    def _sim(self, pose: str) -> None:
        self.sim_pose, self.sim_time = pose, SIM_SECONDS

    def handle_event(self, event: pygame.event.Event) -> None:
        super().handle_event(event)
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_a, pygame.K_LEFT, pygame.K_q):
            self._sim("tilt_left")
        elif event.key in (pygame.K_d, pygame.K_RIGHT, pygame.K_e):
            self._sim("tilt_right")

    # Update state
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.vis_roll += (self.you_roll - self.vis_roll) * min(1.0, 14.0 * dt)
        self._update_drops(dt)

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        self._read_pose(dt)
        if self.mode == "ready":
            self.lean_roll = self.vis_roll * HEAD_GAIN
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        self._update_lean(dt)
        self._update_spill(dt)
        if self.coffee <= 0.0:
            self.coffee = 0.0
            self.finish(False)
        elif self.elapsed >= DURATION:
            self.finish(True)

    def _read_pose(self, dt: float) -> None:
        if self.sim_time > 0 and self.sim_pose:        # keyboard fallback
            self.sim_time -= dt
            self.you_roll = SIM_POSES[self.sim_pose]
            return

        offsets = self.read_offsets()
        if offsets is None:
            self.you_roll *= 0.9
            return

        yaw_off, roll_off = offsets
        if not (not self.tracker.available or self.tracker.has_roll):
            roll_off = yaw_off * 30.0   # tracker can't see tilt: turning works instead
        self.you_roll = max(-30.0, min(30.0, roll_off))

    def _update_lean(self, dt: float) -> None:
        ramp = 0.65 + 0.35 * min(1.0, self.elapsed / DURATION)
        t = self.elapsed
        p, f = self.phases, self.freqs

        self.jolt_t -= dt
        if self.jolt_t <= 0:
            self.jolt_t = random.uniform(*JOLT_EVERY)
            self.jolt_roll += random.choice((-1, 1)) * random.uniform(*JOLT_SIZE) * ramp
        self.jolt_roll *= math.exp(-1.6 * dt)

        wobble = (0.65 * math.sin(f[0] * t + p[0]) + 0.35 * math.sin(f[1] * t + p[1])) * WOBBLE_ROLL * ramp
        self.lean_roll = wobble + self.jolt_roll + self.vis_roll * HEAD_GAIN

    def danger(self) -> float:
        """Lean as a fraction of the safe zone (1.0 = about to spill)."""
        return abs(self.lean_roll) / SAFE_ROLL

    def _update_spill(self, dt: float) -> None:
        over = self.danger() - 1.0
        if over <= 0 or self.coffee <= 0:
            return
        loss = (SPILL_RATE + SPILL_SPEED_UP * min(over, 1.0)) * dt
        self.coffee -= loss
        self.spilled += loss
        self.drop_acc += (25 + 50 * min(over, 1.0)) * dt
        while self.drop_acc >= 1.0:
            self.drop_acc -= 1.0
            self._emit_drop()

    def _emit_drop(self) -> None:
        w, h = self.screen.get_size()
        s = h / 720
        px, py = self._pivot(w, h)
        side = 1.0 if self.lean_roll >= 0 else -1.0
        vx = side * random.uniform(60, 160) * s
        vy = random.uniform(-120, -20) * s
        a = math.radians(self.lean_roll)
        x, y = side * 65 * s, -250 * s
        wx = px + x * math.cos(a) - y * math.sin(a)
        wy = py + x * math.sin(a) + y * math.cos(a)
        self.drops.append([wx, wy, vx, vy, random.uniform(0.8, 1.4)])

    def _update_drops(self, dt: float) -> None:
        g = 900 * self.screen.get_height() / 720
        for d in self.drops:
            d[3] += g * dt
            d[0] += d[2] * dt
            d[1] += d[3] * dt
            d[4] -= dt
        self.drops = [d for d in self.drops if d[4] > 0 and d[1] < self.screen.get_height()]

    # Draw the scene
    def _pivot(self, w: int, h: int) -> tuple[int, int]:
        return int(w * 0.42), int(h * 0.70)

    def _draw_arm(self, screen: pygame.Surface, px: int, py: int, s: float) -> None:
        h = screen.get_height()
        sleeve = pygame.Rect(0, 0, int(96 * s), h - py + 20)
        sleeve.midtop = (px, py + int(34 * s))
        pygame.draw.rect(screen, SLEEVE, sleeve, border_radius=int(10 * s))
        band = pygame.Rect(sleeve.x, sleeve.y, sleeve.w, int(14 * s))
        pygame.draw.rect(screen, SLEEVE_BAND, band)
        wrist = pygame.Rect(0, 0, int(74 * s), int(48 * s))
        wrist.midtop = (px, py - int(8 * s))
        pygame.draw.rect(screen, SKIN, wrist, border_radius=int(12 * s))

    def _hand_surface(self, s: float, yaw: float) -> pygame.Surface:
        """Hand + cup, pivot at the centre of the surface, unrotated."""
        r = int(330 * s)
        surf = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)

        def P(x: float, y: float) -> tuple[int, int]:
            return int(r + x * s), int(r + y * s)

        # cup body, level of coffee inside, rim ellipse foreshortened by forward/back lean
        top_y, bot_y = -250, -90
        top_w, bot_w = 66, 48
        openness = max(0.12, min(0.9, 0.45 + 0.42 * yaw / SAFE_YAW * 0.6))
        rim_h = 2 * top_w * openness

        body = [P(-top_w, top_y), P(top_w, top_y), P(bot_w, bot_y), P(-bot_w, bot_y)]
        pygame.draw.polygon(surf, CUP, body)
        pygame.draw.polygon(surf, CUP_SHADE, [P(top_w * 0.45, top_y), P(top_w, top_y),
                                              P(bot_w, bot_y), P(bot_w * 0.45, bot_y)])

        # coffee surface is kept level in the world, so it slides against the cup frame
        level = max(0.0, self.coffee)
        cof_y = bot_y + (top_y - bot_y) * (0.15 + 0.78 * level)
        frac = (cof_y - bot_y) / (top_y - bot_y)
        cof_w = bot_w + (top_w - bot_w) * frac
        slosh = max(-1.0, min(1.0, -self.lean_roll / SAFE_ROLL)) * 10
        surf_h = max(4, int(2 * cof_w * openness * 0.8 * s))
        if level > 0:
            pygame.draw.polygon(surf, COFFEE, [P(-cof_w, cof_y), P(cof_w, cof_y),
                                               P(bot_w, bot_y), P(-bot_w, bot_y)])
            top = pygame.Rect(0, 0, int(2 * cof_w * s), surf_h)
            top.center = P(slosh, cof_y)
            pygame.draw.ellipse(surf, COFFEE_TOP, top)

        rim = pygame.Rect(0, 0, int(2 * top_w * s), max(6, int(rim_h * s)))
        rim.center = P(0, top_y)
        pygame.draw.ellipse(surf, DARK, rim, max(3, int(5 * s)))

        # palm cradling the base, thumb up the side, fingers wrapped across the front
        palm = pygame.Rect(0, 0, int(130 * s), int(100 * s))
        palm.center = P(0, -50)
        pygame.draw.ellipse(surf, SKIN, palm)
        thumb = pygame.Rect(0, 0, int(26 * s), int(80 * s))
        thumb.center = P(-bot_w - 8, -135)
        pygame.draw.rect(surf, SKIN_SHADE, thumb, border_radius=int(13 * s))
        for i in range(4):
            fx = -36 + i * 24
            finger = pygame.Rect(0, 0, int(21 * s), int(70 * s))
            finger.center = P(fx + 8, -112)
            pygame.draw.rect(surf, SKIN, finger, border_radius=int(10 * s))
            pygame.draw.rect(surf, SKIN_SHADE, finger, 2, border_radius=int(10 * s))
        return surf

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        s = h / 720
        screen.fill(BG)
        pygame.draw.rect(screen, FLOOR, (0, h - 110, w, 110))
        self._draw_hud(screen, w, h)

        if self.mode == "calibrate":
            self.draw_calibration(screen)
            return

        px, py = self._pivot(w, h)
        self._draw_arm(screen, px, py, s)

        # coffee puddle
        if self.spilled > 0:
            pw = int(min(1.0, self.spilled) * 420 * s)
            pud = pygame.Rect(0, 0, pw, max(4, pw // 6))
            pud.center = (px + int(150 * s), h - 100)
            pygame.draw.ellipse(screen, COFFEE, pud)

        hand = self._hand_surface(s, self.lean_yaw)
        hand = pygame.transform.rotate(hand, -self.lean_roll)
        screen.blit(hand, hand.get_rect(center=(px, py)))

        for x, y, _, _, life in self.drops:
            pygame.draw.circle(screen, COFFEE, (int(x), int(y)), max(2, int((3 + 3 * min(1.0, life)) * s)))

        if self.mode == "ready":
            draw_text_centered(screen, self.big_font, "GET READY!", (240, 240, 240), (w // 2, 85))
            draw_text_centered(screen, self.font, "Tilt your head to keep the cup level - don't spill!",
                               (200, 200, 210), (w // 2, 130))
            return

        self._draw_gauge(screen, int(w * 0.78), int(h * 0.45), int(95 * s))

        # coffee left (side bar) and delivery progress (bottom bar)
        cx, cy, cw, ch = int(w * 0.12), int(h * 0.22), 26, int(h * 0.42)
        draw_text_centered(screen, self.font, "COFFEE", (240, 240, 240), (cx + cw // 2, cy - 22))
        self._draw_coffee_bar(screen, cx, cy, cw, ch)

        frac = min(1.0, self.elapsed / DURATION)
        bx, by, bw, bh = 120, h - 62, w - 240, 26
        draw_bar(screen, (bx, by, bw, bh), frac, GOOD, radius=8)
        draw_text_centered(screen, self.small_font, "DELIVERING...", (240, 240, 240), (w // 2, by - 12))

    def _draw_coffee_bar(self, screen: pygame.Surface, x: int, y: int, bw: int, bh: int) -> None:
        pygame.draw.rect(screen, (50, 45, 60), (x, y, bw, bh), border_radius=8)
        fill = int(bh * max(0.0, min(1.0, self.coffee)))
        if fill > 0:
            col = COFFEE_TOP if self.coffee > 0.35 else BAD
            pygame.draw.rect(screen, col, (x, y + bh - fill, bw, fill), border_radius=8)
        pygame.draw.rect(screen, (230, 230, 240), (x, y, bw, bh), 2, border_radius=8)

    def _draw_gauge(self, screen: pygame.Surface, cx: int, cy: int, r: int) -> None:
        """Level gauge: dot leaves the green ring and the coffee spills."""
        full = r * 1.4                       # gauge covers 1.4x the safe zone
        pygame.draw.circle(screen, (40, 36, 52), (cx, cy), int(full))
        pygame.draw.circle(screen, GOOD, (cx, cy), r, 3)
        pygame.draw.line(screen, (80, 76, 96), (cx - int(full), cy), (cx + int(full), cy), 1)
        pygame.draw.line(screen, (80, 76, 96), (cx, cy - int(full)), (cx, cy + int(full)), 1)

        nx = max(-1.4, min(1.4, self.lean_roll / SAFE_ROLL))
        d = self.danger()
        color = lerp_color(GOOD, WARN, (d - 0.5) * 2) if d < 1 else lerp_color(WARN, BAD, (d - 1) * 3)
        pos = (cx + int(nx * r), cy)
        pygame.draw.circle(screen, color, pos, 11)
        pygame.draw.circle(screen, DARK, pos, 11, 2)
        draw_text_centered(screen, self.small_font, "KEEP IT IN THE RING", (200, 200, 210),
                           (cx, cy + int(full) + 18))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        left = max(0.0, DURATION - self.elapsed)
        screen.blit(self.font.render(f"{left:0.0f}s", True, (240, 240, 240)), (10, 10))

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = f"Pose tracking: {self.tracker.backend}   (C = recentre)"
        else:
            info = "No camera tracking - keyboard: A/D or Q/E tilt"
        draw_status_line(screen, self.small_font, info)

        self.draw_face_lost(screen, 40)
