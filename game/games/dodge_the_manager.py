from __future__ import annotations

import math
import random

import pygame

from game.assets import load_image, scale_to_height
from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

WALK_SECONDS = 24.0
TILT_RANGE = 20.0
DEAD_ZONE = 0.12
PLAYER_SPEED = 1.7
EDGE_MARGIN = 0.16
WARN_SECONDS = 1.15
APPROACH_SECONDS = 2.8
VOLUNTEERED_SECONDS = 2.4

NAVY = (7, 34, 66)
BLUE = (17, 92, 170)
PALE_BLUE = (102, 190, 234)
WHITE = (250, 249, 242)
INK = (20, 34, 48)
GREEN = (64, 177, 112)
RED = (212, 69, 61)
SHADOW = (18, 30, 40, 75)


class DodgeTheManager(FaceMinigame):
    title = "Any Volunteers?"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.hallway_source = load_image("volunteer_hallway.png")
        self.player_source = load_image("volunteer_player.png")
        self.manager_source = load_image("volunteer_manager.png")
        self._scene_size: tuple[int, int] | None = None
        self.hallway: pygame.Surface | None = None
        self.player_sprite: pygame.Surface | None = None
        self.manager_sprite: pygame.Surface | None = None
        self.manager_flipped: pygame.Surface | None = None
        self.player_sizes: dict[int, pygame.Surface] = {}
        self.manager_sizes: dict[tuple[int, bool], pygame.Surface] = {}
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Tilt Left", "Tilt your head left to move across the hallway"),
            Action("Tilt Right", "Tilt your head right to dodge the manager"),
        )

    @property
    def negative_progress(self) -> float:
        return self.peak_caught

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.progress = 0.0
        self.player_u = 0.5
        self.target_u = 0.5
        self.phase = "clear"
        self.phase_t = 0.0
        self.clear_duration = 2.3
        self.side = random.choice((-1, 1))
        self.manager_u = -0.2
        self.caught = 0.0
        self.peak_caught = 0.0
        self.encounters = 0
        self.bubble_t = 0.0
        self.volunteered_t = 0.0

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        offsets = self.read_offsets()
        if offsets is None and self.tracker.available:
            return
        if offsets is not None:
            self._update_control(offsets[1])

        if self.phase == "volunteered":
            self.volunteered_t += dt
            direction = -1 if self.side < 0 else 1
            self.manager_u += direction * dt * 0.22
            target = self.manager_u - direction * 0.10
            self.player_u += (target - self.player_u) * min(1.0, dt * 5.0)
            if self.volunteered_t >= VOLUNTEERED_SECONDS:
                self.finish(False)
            return

        self.elapsed += dt
        self.progress = min(1.0, self.elapsed / WALK_SECONDS)
        self._move_player(dt)
        self._update_manager(dt)
        if self.progress >= 1.0:
            self.finish(True)

    def _update_control(self, roll: float) -> None:
        amount = max(-1.0, min(1.0, roll / TILT_RANGE))
        if abs(amount) < DEAD_ZONE:
            amount = 0.0
        else:
            amount = math.copysign((abs(amount) - DEAD_ZONE) / (1.0 - DEAD_ZONE), amount)
        self.target_u = 0.5 + amount * 0.5

    def _move_player(self, dt: float) -> None:
        target = max(EDGE_MARGIN, min(1.0 - EDGE_MARGIN, self.target_u))
        distance = target - self.player_u
        step = PLAYER_SPEED * dt
        self.player_u += max(-step, min(step, distance * min(1.0, dt * 12.0)))

    def _begin_encounter(self) -> None:
        self.phase = "warning"
        self.phase_t = 0.0
        self.side = random.choice((-1, 1))
        self.bubble_t = WARN_SECONDS + 0.7
        self.encounters += 1

    def _update_manager(self, dt: float) -> None:
        self.phase_t += dt
        self.bubble_t = max(0.0, self.bubble_t - dt)
        start = -0.13 if self.side < 0 else 1.13
        destination = 0.38 if self.side < 0 else 0.62

        if self.phase == "clear":
            self.manager_u = start
            self.caught = max(0.0, self.caught - dt / 0.45)
            if self.phase_t >= self.clear_duration:
                self._begin_encounter()
            return

        if self.phase == "warning":
            reveal = min(1.0, self.phase_t / WARN_SECONDS)
            self.manager_u = start + (destination - start) * 0.25 * reveal
            self.caught = max(0.0, self.caught - dt / 0.45)
            if self.phase_t >= WARN_SECONDS:
                self.phase = "approach"
                self.phase_t = 0.0
            return

        p = min(1.0, self.phase_t / APPROACH_SECONDS)
        travel = math.sin(math.pi * p)
        self.manager_u = start + (destination - start) * travel
        danger = 0.2 < p < 0.8 and abs(self.player_u - self.manager_u) < 0.13
        if danger:
            self._get_volunteered()
            return
        else:
            self.caught = max(0.0, self.caught - dt / 0.4)
        if p >= 1.0:
            self.phase = "clear"
            self.phase_t = 0.0
            self.clear_duration = random.uniform(1.4, 2.2)
            self.caught = 0.0

    def _get_volunteered(self) -> None:
        self.phase = "volunteered"
        self.phase_t = 0.0
        self.volunteered_t = 0.0
        self.caught = 1.0
        self.bubble_t = VOLUNTEERED_SECONDS

    def _prepare_art(self, w: int, h: int) -> None:
        if self._scene_size == (w, h):
            return
        self._scene_size = (w, h)
        self.hallway = pygame.transform.smoothscale(self.hallway_source, (w, h))
        player_h = max(150, int(h * 0.36))
        manager_h = max(165, int(h * 0.38))
        self.player_sprite = scale_to_height(self.player_source, player_h)
        self.manager_sprite = scale_to_height(self.manager_source, manager_h)
        self.manager_flipped = pygame.transform.flip(self.manager_sprite, True, False)
        self.player_sizes.clear()
        self.manager_sizes.clear()

    def _project(self, u: float, depth: float, w: int, h: int) -> tuple[int, int, int]:
        perspective = depth ** 0.78
        floor_width = w * (0.72 + (0.08 - 0.72) * perspective)
        x = w * 0.5 + (u - 0.5) * floor_width
        bottom = (h - 18) + (h * 0.515 - (h - 18)) * perspective
        height = h * (0.36 + (0.115 - 0.36) * perspective)
        return int(x), int(bottom), max(54, int(height))

    def _player_at_height(self, height: int) -> pygame.Surface:
        height = max(4, round(height / 4) * 4)
        if height not in self.player_sizes:
            self.player_sizes[height] = scale_to_height(self.player_sprite, height)
        return self.player_sizes[height]

    def _manager_at_height(self, height: int) -> pygame.Surface:
        height = max(4, round(height / 4) * 4)
        flipped = self.side < 0
        key = (height, flipped)
        if key not in self.manager_sizes:
            source = self.manager_flipped if flipped else self.manager_sprite
            self.manager_sizes[key] = scale_to_height(source, height)
        return self.manager_sizes[key]

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        self._prepare_art(w, h)
        screen.blit(self.hallway, (0, 0))

        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((4, 25, 48, 22))
        pygame.draw.rect(shade, (255, 244, 220, 28), (0, int(h * 0.48), w, int(h * 0.52)))
        screen.blit(shade, (0, 0))

        manager_visible = self.phase in ("warning", "approach", "volunteered") and self.mode != "calibrate"
        self._draw_player(screen, w, h)
        if manager_visible:
            self._draw_manager(screen, w, h)
        self._draw_hud(screen, w, h)

        if self.mode == "calibrate":
            overlay = pygame.Surface((w, h), pygame.SRCALPHA)
            overlay.fill((7, 34, 66, 155))
            screen.blit(overlay, (0, 0))
            self.draw_calibration(screen)

    def _draw_player(self, screen: pygame.Surface, w: int, h: int) -> None:
        px, bottom, sprite_h = self._project(self.player_u, self.progress, w, h)
        sprite = self._player_at_height(sprite_h)
        bob_strength = max(1.0, 4.0 * (1.0 - self.progress) + 1.0)
        bob = int(math.sin(self.elapsed * 10.0) * bob_strength)
        bottom += bob
        shadow_w = max(46, sprite.get_width() // 2)
        shadow_h = max(6, int(18 * sprite_h / max(1, h * 0.36)))
        shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, SHADOW, shadow.get_rect())
        screen.blit(shadow, (px - shadow_w // 2, bottom - shadow_h // 2))
        screen.blit(sprite, (px - sprite.get_width() // 2, bottom - sprite.get_height()))

    def _draw_manager(self, screen: pygame.Surface, w: int, h: int) -> None:
        manager_depth = max(0.0, self.progress - 0.035)
        mx, bottom, player_h = self._project(self.manager_u, manager_depth, w, h)
        sprite = self._manager_at_height(int(player_h * 1.06))
        bob_strength = max(1.0, 3.0 * (1.0 - manager_depth) + 1.0)
        bob = int(math.sin(self.phase_t * 8.0) * bob_strength)
        bottom += bob
        shadow_w = max(50, sprite.get_width() // 2)
        shadow_h = max(6, int(18 * sprite.get_height() / max(1, h * 0.38)))
        shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, SHADOW, shadow.get_rect())
        screen.blit(shadow, (mx - shadow_w // 2, bottom - shadow_h // 2))
        screen.blit(sprite, (mx - sprite.get_width() // 2, bottom - sprite.get_height()))
        if self.bubble_t > 0.0:
            sprite_top = bottom - sprite.get_height()
            message = "Perfect, thank you for volunteering!" if self.phase == "volunteered" else "Got a minute?"
            self._draw_bubble(screen, mx, max(88, sprite_top - 70), w, message)

    def _draw_bubble(self, screen: pygame.Surface, cx: int, y: int, w: int, message: str) -> None:
        font = self.small_font if len(message) > 20 else self.font
        text = font.render(message, True, INK)
        bw, bh = text.get_width() + 34, text.get_height() + 20
        bx = max(10, min(w - bw - 10, cx - bw // 2))
        pygame.draw.rect(screen, WHITE, (bx, y, bw, bh), border_radius=14)
        pygame.draw.rect(screen, NAVY, (bx, y, bw, bh), 3, border_radius=14)
        tip_x = max(bx + 18, min(bx + bw - 18, cx))
        pygame.draw.polygon(screen, WHITE, [(tip_x - 10, y + bh - 2),
                                             (tip_x + 10, y + bh - 2), (cx, y + bh + 16)])
        pygame.draw.lines(screen, NAVY, False, [(tip_x - 10, y + bh - 2),
                                                (cx, y + bh + 16), (tip_x + 10, y + bh - 2)], 3)
        screen.blit(text, (bx + 17, y + 10))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        panel = pygame.Surface((w, 82), pygame.SRCALPHA)
        panel.fill((7, 34, 66, 225))
        screen.blit(panel, (0, 0))
        screen.blit(self.font.render("ANY VOLUNTEERS?", True, WHITE), (18, 13))
        screen.blit(self.small_font.render("Make it to your office without getting stopped", True, PALE_BLUE),
                    (18, 47))

        bx, by, bw = int(w * 0.56), 22, int(w * 0.20)
        draw_bar(screen, (bx, by, bw, 15), self.progress, GREEN, back=(46, 70, 91), radius=7)
        draw_text_centered(screen, self.small_font, "OFFICE", WHITE, (bx + bw // 2, by + 30))

        if self.phase == "warning" and self.mode != "calibrate":
            side = "LEFT" if self.side < 0 else "RIGHT"
            draw_text_centered(screen, self.font, f"MANAGER FROM THE {side}", RED, (w // 2, 112))

        if self.phase == "volunteered":
            draw_text_centered(screen, self.font, "OFF TO HELP THE MANAGER...", RED, (w // 2, 112))

        if self.caught > 0.04 and self.phase != "volunteered":
            draw_bar(screen, (w // 2 - 105, h - 44, 210, 14), self.caught, RED,
                     back=(70, 62, 57), radius=7)
            draw_text_centered(screen, self.small_font, "DON'T GET VOLUNTEERED", WHITE,
                               (w // 2, h - 60))

        draw_camera_preview(screen, self.tracker)
        info = f"Head tilt: {self.tracker.backend}" if self.tracker.available else "Camera tracking unavailable"
        draw_status_line(screen, self.small_font, info)
        if self.mode != "calibrate":
            self.draw_face_lost(screen, h // 2)
