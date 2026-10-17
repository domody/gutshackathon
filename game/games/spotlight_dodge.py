from __future__ import annotations

import math
import random

import pygame

from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line


SURVIVE_SECONDS = 15.0

# Control
DEAD_ZONE = 0.08            # ignore tiny head movements (fraction of full turn)
PLAYER_SPEED = 2.2          # max player speed, screen-widths per second
KEY_STEP = 0.25             # keyboard fallback: screen fraction per key press
EDGE_MARGIN = 0.04
PLAYER_HALF_W = 16

# Searchlight
BEAM_HALF_W = 0.11          # beam half-width, fraction of screen width
WARN_SECONDS = 0.9
EXPOSURE_UP_TIME = 0.22     # seconds in light before you're caught
EXPOSURE_DOWN_TIME = 0.6    # seconds to cool down when back in shadow

BG = (12, 14, 26)
FLOOR = (28, 30, 46)


class SpotlightDodge(FaceMinigame):
    """A searchlight sweeps in from an edge. Stay in shadow for 15 seconds."""

    title = "Dodge the Spotlight"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self._overlay: pygame.Surface | None = None
        self.start()

    # Public API
    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Lean Left", "Turn your head left to slide left (or A / Left)", self.move_left),
            Action("Lean Right", "Turn your head right to slide right (or D / Right)", self.move_right),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0

        self.player_u = 0.5     # player position, 0..1 across the screen
        self.target_u = 0.5

        self.light_phase = "idle"   # idle -> warn -> sweep -> idle ...
        self.light_t = 0.0
        self.idle_dur = 0.8
        self.side = -1              # -1: enters from left, +1: from right
        self.reach = 0.6            # how far the leading edge gets (0..1)
        self.sweep_dur = 2.4
        self.beam_u: float | None = None
        self.exposure = 0.0
        self.lit = False

    # Handle input
    def move_left(self) -> None:
        self.target_u = max(0.0, self.target_u - KEY_STEP)

    def move_right(self) -> None:
        self.target_u = min(1.0, self.target_u + KEY_STEP)

    def handle_event(self, event: pygame.event.Event) -> None:
        super().handle_event(event)
        if event.type != pygame.KEYDOWN:
            return
        left, right = self.actions
        if event.key in (pygame.K_a, pygame.K_LEFT):
            left.perform()
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            right.perform()

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
            return  # face lost (or keyboard only): keep current target
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
            pygame.draw.polygon(overlay, (255, 248, 200, 70), [
                (cx - 14, 0), (cx + 14, 0), (cx + hw, top),
                (cx + hw, floor_c), (cx - hw, floor_c), (cx - hw, top)])
            pygame.draw.ellipse(overlay, (255, 250, 210, 130), (cx - hw, floor_c - 30, 2 * hw, 60))
        screen.blit(overlay, (0, 0))

        if playing and self.light_phase == "warn":
            self._draw_warning(screen, w, h)
        self._draw_player(screen, ground_y, w)
        self._draw_hud(screen, w, h)

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
        text = "SEARCHLIGHT FROM THE " + ("LEFT" if self.side < 0 else "RIGHT")
        surf = self.font.render(text, True, (255, 120, 120))
        screen.blit(surf, ((w - surf.get_width()) // 2, 60))

    def _draw_player(self, screen: pygame.Surface, ground_y: int, w: int) -> None:
        px = int(self.player_u * w)
        e = self.exposure
        color = (80 + int(175 * e), 200 - int(130 * e), 120 - int(80 * e))
        pygame.draw.ellipse(screen, (6, 6, 10), (px - 24, ground_y + 22, 48, 14))
        pygame.draw.rect(screen, color, (px - PLAYER_HALF_W, ground_y - 14, PLAYER_HALF_W * 2, 44),
                         border_radius=8)
        pygame.draw.circle(screen, color, (px, ground_y - 30), 14)

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        remaining = max(0.0, SURVIVE_SECONDS - self.elapsed)
        screen.blit(self.font.render(f"{remaining:.1f}s", True, (240, 240, 240)), (10, 10))

        # detection meter
        bx, by, bw, bh = w // 2 - 100, 14, 200, 12
        draw_bar(screen, (bx, by, bw, bh), self.exposure, (230, 60, 60))
        label = self.small_font.render("DETECTION", True, (200, 200, 200))
        screen.blit(label, (w // 2 - label.get_width() // 2, by + bh + 4))

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = f"Head tracking: {self.tracker.backend}   (C = recentre)"
        else:
            info = "No camera tracking - keyboard: A/D or arrows"
        draw_status_line(screen, self.small_font, info)

        if self.mode == "calibrate":
            self.draw_calibration(screen)
        else:
            self.draw_face_lost(screen, h // 2)
