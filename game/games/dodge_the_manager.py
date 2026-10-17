"""Dodge the Manager: office-themed reskin of Dodge the Spotlight.

Your manager is wandering the office looking for volunteers. Stay out of their line of
sight for 15 seconds. If they spot you, you've been volunteered.

Custom artwork (optional): drop PNGs (transparent background recommended) into an
`assets/` folder next to this file. Any that are missing fall back to code-drawn art:
    assets/manager.png     the manager (drawn at the head of the line of sight)
    assets/employee.png    the player
    assets/employee_volunteered.png   (optional) player with hand up, shown when nearly caught
"""

from __future__ import annotations

import math
import os
import random

import pygame

from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line


SURVIVE_SECONDS = 15.0

# Control
DEAD_ZONE = 0.08            # ignore tiny head movements (fraction of full turn)
PLAYER_SPEED = 2.0          # max player speed, screen-widths per second
EDGE_MARGIN = 0.04
PLAYER_HALF_W = 16

# Manager's line of sight
BEAM_HALF_W = 0.11          # sight-cone half-width, fraction of screen width
WARN_SECONDS = 0.9
EXPOSURE_UP_TIME = 0.18     # seconds in sight before you're volunteered
EXPOSURE_DOWN_TIME = 0.6    # seconds to cool down when back out of sight
MANAGER_Y = 112             # vertical position of the manager's head
HAND_UP_AT = 0.5            # exposure level at which the player's hand starts creeping up

BG = (18, 22, 34)
WALL = (24, 29, 44)
FLOOR = (34, 40, 58)
PARTITION = (30, 36, 54)

# --- custom artwork ----------------------------------------------------------
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MANAGER_SPRITE_H = 96
EMPLOYEE_SPRITE_H = 84


def _load_sprite(filename: str, height: int) -> pygame.Surface | None:
    """Load an optional PNG scaled to `height`. Missing/broken files return None."""
    path = os.path.join(ASSET_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        img = pygame.image.load(path)
        if pygame.display.get_surface():
            img = img.convert_alpha()
        iw, ih = img.get_size()
        return pygame.transform.smoothscale(img, (max(1, int(iw * height / ih)), height))
    except Exception as exc:
        print(f"Could not load {path}: {exc!r} (using built-in art)")
        return None


class DodgeTheManager(FaceMinigame):
    """The manager sweeps the office asking for volunteers. Stay out of sight for 15 seconds."""

    title = "Dodge the Manager"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self._overlay: pygame.Surface | None = None
        self.manager_sprite = _load_sprite("manager.png", MANAGER_SPRITE_H)
        self.employee_sprite = _load_sprite("employee.png", EMPLOYEE_SPRITE_H)
        self.employee_hand_sprite = _load_sprite("employee_volunteered.png", EMPLOYEE_SPRITE_H)
        self.start()

    # Public API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Lean Left", "Turn your head left to slide left"),
            Action("Lean Right", "Turn your head right to slide right"),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0

        self.player_u = 0.5     # player position, 0..1 across the screen
        self.target_u = 0.5

        self.light_phase = "idle"   # idle -> warn -> sweep -> idle ...
        self.light_t = 0.0
        self.idle_dur = 0.8
        self.side = -1              # -1: manager enters from left, +1: from right
        self.reach = 0.6            # how far the manager gets (0..1)
        self.sweep_dur = 2.4
        self.beam_u: float | None = None
        self.exposure = 0.0
        self.lit = False

    # Update state
    def update(self, dt: float) -> None:
        if self.finished:
            return

        if self.mode == "calibrate":
            self.update_calibration(dt)
            self._move_player(dt)
            return

        self.elapsed += dt
        self._update_control()
        self._move_player(dt)
        self._update_light(dt)
        self._update_exposure(dt)

        if self.exposure >= 1.0:
            self.finish(False)
        elif self.elapsed >= SURVIVE_SECONDS:
            self.finish(True)

    def _update_control(self) -> None:
        offsets = self.read_offsets()
        if offsets is None:
            return  # face lost: keep current target
        off = max(-1.0, min(1.0, offsets[0]))
        if abs(off) < DEAD_ZONE:
            off = 0.0
        else:
            off = math.copysign((abs(off) - DEAD_ZONE) / (1 - DEAD_ZONE), off)
        self.target_u = 0.5 + 0.5 * off

    def _move_player(self, dt: float) -> None:
        target = max(EDGE_MARGIN, min(1 - EDGE_MARGIN, self.target_u))
        delta = (target - self.player_u) * min(1.0, 14.0 * dt)
        step = PLAYER_SPEED * dt
        self.player_u += max(-step, min(step, delta))

    def _begin_warn(self) -> None:
        progress = min(1.0, self.elapsed / SURVIVE_SECONDS)
        # Usually enter from the side the player is on, forcing them to cross.
        on_side = -1 if self.player_u < 0.5 else 1
        self.side = on_side if random.random() < 0.7 else -on_side
        self.reach = random.uniform(0.50 + 0.10 * progress, 0.68 + 0.12 * progress)
        self.sweep_dur = 2.4 - 0.7 * progress
        self.light_phase = "warn"
        self.light_t = 0.0

    def _update_light(self, dt: float) -> None:
        self.light_t += dt
        if self.light_phase == "idle":
            self.beam_u = None
            if self.light_t >= self.idle_dur:
                self._begin_warn()
        elif self.light_phase == "warn":
            if self.light_t >= WARN_SECONDS:
                self.light_phase, self.light_t = "sweep", 0.0
        else:
            p = self.light_t / self.sweep_dur
            if p >= 1.0:
                self.light_phase, self.light_t = "idle", 0.0
                self.idle_dur = random.uniform(0.4, 0.8)
                self.beam_u = None
            else:
                lead = self.reach * math.sin(math.pi * p)  # out and back
                if self.side < 0:
                    self.beam_u = lead - BEAM_HALF_W
                else:
                    self.beam_u = 1.0 - lead + BEAM_HALF_W

    def _update_exposure(self, dt: float) -> None:
        w = self.screen.get_width()
        self.lit = (
            self.beam_u is not None
            and abs(self.player_u * w - self.beam_u * w) < BEAM_HALF_W * w + PLAYER_HALF_W * 0.5
        )
        if self.lit:
            self.exposure = min(1.0, self.exposure + dt / EXPOSURE_UP_TIME)
        else:
            self.exposure = max(0.0, self.exposure - dt / EXPOSURE_DOWN_TIME)

    # Draw the scene
    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        ground_y = h - 110
        screen.fill(BG)
        pygame.draw.rect(screen, WALL, (0, 0, w, ground_y + 40))
        self._draw_cubicles(screen, w, ground_y)
        pygame.draw.rect(screen, FLOOR, (0, ground_y + 40, w, h - ground_y - 40))

        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay = self._overlay
        overlay.fill((0, 0, 0, 0))

        playing = self.mode == "play"
        if playing and self.light_phase in ("warn", "sweep"):
            zone_w = int(self.reach * w)
            x0 = 0 if self.side < 0 else w - zone_w
            alpha = 35
            if self.light_phase == "warn":
                alpha += int(25 * math.sin(self.light_t * 10))
            pygame.draw.rect(overlay, (255, 40, 40, alpha), (x0, 0, zone_w, h))

        if self.beam_u is not None:
            cx, hw = int(self.beam_u * w), int(BEAM_HALF_W * w)
            floor_c = ground_y + 55
            top = ground_y - 40
            # cone of sight from the manager's eyes down to the floor
            pygame.draw.polygon(overlay, (255, 235, 150, 70), [
                (cx - 14, MANAGER_Y), (cx + 14, MANAGER_Y), (cx + hw, top),
                (cx + hw, floor_c), (cx - hw, floor_c), (cx - hw, top)])
            pygame.draw.ellipse(overlay, (255, 240, 170, 130), (cx - hw, floor_c - 30, 2 * hw, 60))
        screen.blit(overlay, (0, 0))

        if playing and self.light_phase == "warn":
            self._draw_warning(screen, w, h)
        if self.beam_u is not None:
            self._draw_manager(screen, int(self.beam_u * w), w, speaking=True)
        self._draw_player(screen, ground_y, w)
        self._draw_hud(screen, w, h)

    def _draw_cubicles(self, screen: pygame.Surface, w: int, ground_y: int) -> None:
        """Faint cubicle partitions along the back wall."""
        step = max(120, w // 7)
        for x in range(step // 2, w, step):
            pygame.draw.rect(screen, PARTITION, (x, ground_y - 70, 8, 110), border_radius=3)
            pygame.draw.rect(screen, PARTITION, (x, ground_y - 70, step - 30, 8), border_radius=3)

    def _draw_manager(self, screen: pygame.Surface, cx: int, w: int, speaking: bool) -> None:
        y = MANAGER_Y
        if self.manager_sprite is not None:
            sp = self.manager_sprite
            screen.blit(sp, (cx - sp.get_width() // 2, y - sp.get_height() // 2))
        else:
            pygame.draw.rect(screen, (50, 55, 80), (cx - 22, y + 10, 44, 46), border_radius=8)   # suit
            pygame.draw.polygon(screen, (235, 235, 240), [(cx - 8, y + 10), (cx + 8, y + 10), (cx, y + 26)])  # shirt
            pygame.draw.polygon(screen, (200, 50, 60), [(cx - 4, y + 14), (cx + 4, y + 14), (cx + 3, y + 40), (cx, y + 44), (cx - 3, y + 40)])  # tie
            pygame.draw.circle(screen, (235, 190, 160), (cx, y - 6), 20)                          # head
            pygame.draw.circle(screen, (20, 20, 30), (cx, y - 6), 20, 3)
            pygame.draw.rect(screen, (30, 30, 40), (cx - 15, y - 12, 12, 8), 2, border_radius=2)  # glasses
            pygame.draw.rect(screen, (30, 30, 40), (cx + 3, y - 12, 12, 8), 2, border_radius=2)
            pygame.draw.line(screen, (30, 30, 40), (cx - 3, y - 8), (cx + 3, y - 8), 2)
            pygame.draw.line(screen, (120, 60, 50), (cx - 6, y + 4), (cx + 6, y + 4), 2)           # mouth

        if speaking:
            text = self.small_font.render("Any volunteers?", True, (30, 30, 40))
            bw, bh = text.get_width() + 18, text.get_height() + 12
            bx = max(6, min(w - bw - 6, cx + 26))
            by = y - 48
            pygame.draw.rect(screen, (250, 250, 245), (bx, by, bw, bh), border_radius=8)
            pygame.draw.rect(screen, (30, 30, 40), (bx, by, bw, bh), 2, border_radius=8)
            tail_x = max(bx + 10, min(bx + bw - 10, cx + 20))
            pygame.draw.polygon(screen, (250, 250, 245), [(tail_x - 6, by + bh - 1), (tail_x + 6, by + bh - 1), (cx + 12, y - 28)])
            screen.blit(text, (bx + 9, by + 6))

    def _draw_warning(self, screen: pygame.Surface, w: int, h: int) -> None:
        if int(self.light_t * 8) % 2:
            return
        for i in range(3):
            if self.side < 0:
                x = 20 + i * 26
                pts = [(x, h // 2 - 20), (x + 20, h // 2), (x, h // 2 + 20)]
            else:
                x = w - 20 - i * 26
                pts = [(x, h // 2 - 20), (x - 20, h // 2), (x, h // 2 + 20)]
            pygame.draw.polygon(screen, (255, 90, 90), pts)
        text = "MANAGER COMING FROM THE " + ("LEFT" if self.side < 0 else "RIGHT") + " - LOOK BUSY!"
        surf = self.font.render(text, True, (255, 120, 120))
        screen.blit(surf, ((w - surf.get_width()) // 2, 60))

    def _draw_player(self, screen: pygame.Surface, ground_y: int, w: int) -> None:
        px = int(self.player_u * w)
        e = self.exposure
        pygame.draw.ellipse(screen, (6, 6, 10), (px - 24, ground_y + 22, 48, 14))

        sprite = self.employee_sprite
        if e >= HAND_UP_AT and self.employee_hand_sprite is not None:
            sprite = self.employee_hand_sprite
        if sprite is not None:
            screen.blit(sprite, (px - sprite.get_width() // 2, ground_y + 30 - sprite.get_height()))
        else:
            # shirt shifts from calm green to alarmed red as you get spotted
            color = (80 + int(175 * e), 200 - int(130 * e), 120 - int(80 * e))
            pygame.draw.rect(screen, color, (px - PLAYER_HALF_W, ground_y - 14, PLAYER_HALF_W * 2, 44),
                             border_radius=8)
            pygame.draw.polygon(screen, (40, 50, 90), [(px - 3, ground_y - 12), (px + 3, ground_y - 12), (px, ground_y + 10)])  # tie
            pygame.draw.circle(screen, (235, 190, 160), (px, ground_y - 30), 14)
            pygame.draw.circle(screen, (20, 20, 30), (px, ground_y - 30), 14, 2)
            if e >= HAND_UP_AT:
                # the hand creeps up on its own: you're about to be volunteered
                lift = (e - HAND_UP_AT) / (1 - HAND_UP_AT)
                hand_y = ground_y - 10 - int(46 * lift)
                pygame.draw.line(screen, color, (px + PLAYER_HALF_W - 2, ground_y - 6), (px + 13, hand_y), 6)
                pygame.draw.circle(screen, (235, 190, 160), (px + 26, hand_y), 6)

        if e > 0.05:
            pygame.draw.circle(screen, (255, int(200 - 150 * e), 60), (px, ground_y - 4), 46, max(1, int(2 + 4 * e)))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        remaining = max(0.0, SURVIVE_SECONDS - self.elapsed)
        screen.blit(self.font.render(f"{remaining:.1f}s", True, (240, 240, 240)), (10, 10))

        # volunteered meter
        bx, by, bw, bh = w // 2 - 100, 14, 200, 12
        draw_bar(screen, (bx, by, bw, bh), self.exposure, (230, 60, 60))
        label = self.small_font.render("VOLUNTEERED", True, (200, 200, 200))
        screen.blit(label, (w // 2 - label.get_width() // 2, by + bh + 4))

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = f"Head tracking: {self.tracker.backend}"
        else:
            info = "Camera tracking unavailable"
        draw_status_line(screen, self.small_font, info)

        if self.mode == "calibrate":
            self.draw_calibration(screen)
        else:
            self.draw_face_lost(screen, h // 2)
