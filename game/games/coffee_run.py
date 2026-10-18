from __future__ import annotations

import math
import random

import numpy as np
import pygame

from game.assets import crop_to_alpha, key_pink, load_image
from game.face_minigame import FaceMinigame
from game.minigame import Action
from game.tracking import FaceTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

DURATION = 16.0
READY_SECONDS = 1.5
CONTROL_ACCELERATION = 4.8
OUTWARD_GRAVITY = 1.35
DRAG = 0.72
MAX_SPEED = 2.1
SAFE_POSITION = 0.58
SPILL_RATE = 0.13
SPILL_SPEED_UP = 0.34
JOLT_EVERY = (2.7, 4.2)
JOLT_SIZE = (0.18, 0.32)

NAVY = (8, 35, 64)
WHITE = (248, 248, 243)
PALE = (196, 220, 234)
COFFEE = (105, 57, 30)
COFFEE_TOP = (130, 75, 39)
GOOD = (62, 175, 108)
WARN = (240, 173, 50)
BAD = (214, 65, 62)


def _load_chroma(filename: str, remove_coffee: bool = False) -> tuple[pygame.Surface, pygame.Rect]:
    image = load_image(filename)
    rgb = key_pink(image)
    if remove_coffee:
        alpha = pygame.surfarray.pixels_alpha(image)
        xs = np.arange(image.get_width())[:, None]
        ys = np.arange(image.get_height())[None, :]
        coffee_area = (xs > 385) & (xs < 575) & (ys > 150) & (ys < 225)
        brown = ((rgb[:, :, 0] > 30) & (rgb[:, :, 0] < 170)
                 & (rgb[:, :, 1] > 14) & (rgb[:, :, 1] < 125)
                 & (rgb[:, :, 2] < 100))
        alpha[coffee_area & brown] = 0
        del alpha
    return crop_to_alpha(image)


class CoffeeRun(FaceMinigame):
    title = "Coffee Run"
    objective = "Carry the boss's coffee to the office without spilling the cup."
    success_title = "COFFEE DELIVERED"
    success_description = "Most of it is still in the cup."
    after_calibration = "ready"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.hallway_source = load_image("coffee_hallway.png", alpha=False)
        self.hand_source, self.hand_bounds = _load_chroma("coffee_hand.png", True)
        self.bar_source, _ = _load_chroma("coffee_balance_bar.png")
        self.marker_source, _ = _load_chroma("coffee_balance_marker.png")
        self._art_size: tuple[int, int] | None = None
        self.hand_art: pygame.Surface | None = None
        self.bar_art: pygame.Surface | None = None
        self.marker_art: pygame.Surface | None = None
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Tilt Left", "Tilt your head left to push the marker left"),
            Action("Tilt Right", "Tilt your head right to push the marker right"),
        )

    @property
    def negative_progress(self) -> float:
        return self.spilled

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.ready_t = 0.0
        self.coffee = 1.0
        self.spilled = 0.0
        self.head_roll = 0.0
        self.balance = 0.0
        self.velocity = 0.0
        self.jolt_t = random.uniform(*JOLT_EVERY)
        self.drops: list[list[float]] = []
        self.drop_acc = 0.0

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self._update_drops(dt)
        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        self._read_pose()
        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        control = max(-1.0, min(1.0, self.head_roll / 22.0))
        acceleration = control * CONTROL_ACCELERATION + self.balance * OUTWARD_GRAVITY
        self.velocity += acceleration * dt
        self.velocity *= math.exp(-DRAG * dt)

        self.jolt_t -= dt
        if self.jolt_t <= 0.0:
            self.jolt_t = random.uniform(*JOLT_EVERY)
            self.velocity += random.choice((-1, 1)) * random.uniform(*JOLT_SIZE)

        self.velocity = max(-MAX_SPEED, min(MAX_SPEED, self.velocity))
        self.balance += self.velocity * dt
        if abs(self.balance) > 1.0:
            self.balance = math.copysign(1.0, self.balance)
            self.velocity *= -0.18

        self._update_spill(dt)
        if self.coffee <= 0.0:
            self.coffee = 0.0
            self.finish(False)
        elif self.elapsed >= DURATION:
            self.finish(True)

    def _read_pose(self) -> None:
        offsets = self.read_offsets()
        if offsets is None:
            self.head_roll *= 0.88
            return
        yaw, roll = offsets
        if self.tracker.available and not self.tracker.has_roll:
            roll = yaw * 30.0
        self.head_roll = max(-30.0, min(30.0, roll))

    def danger(self) -> float:
        return abs(self.balance) / SAFE_POSITION

    def _update_spill(self, dt: float) -> None:
        over = self.danger() - 1.0
        if over <= 0.0 or self.coffee <= 0.0:
            return
        loss = (SPILL_RATE + SPILL_SPEED_UP * min(over, 1.0)) * dt
        self.coffee = max(0.0, self.coffee - loss)
        self.spilled = min(1.0, self.spilled + loss)
        self.drop_acc += (18 + 42 * min(over, 1.0)) * dt
        while self.drop_acc >= 1.0:
            self.drop_acc -= 1.0
            self._emit_drop()

    def _emit_drop(self) -> None:
        width, height = self.screen.get_size()
        side = 1 if self.balance > 0 else -1
        x = width * 0.50 + side * width * 0.08
        y = height * 0.49
        self.drops.append([x, y, side * random.uniform(50, 130), random.uniform(-80, -15), 1.2])

    def _update_drops(self, dt: float) -> None:
        gravity = self.screen.get_height() * 1.35
        for drop in self.drops:
            drop[3] += gravity * dt
            drop[0] += drop[2] * dt
            drop[1] += drop[3] * dt
            drop[4] -= dt
        self.drops = [drop for drop in self.drops if drop[4] > 0.0]

    def _prepare_art(self, width: int, height: int) -> None:
        if self._art_size == (width, height):
            return
        self._art_size = (width, height)
        hand_width = min(int(width * 0.66), int(height * 1.03))
        hand_height = round(self.hand_source.get_height() * hand_width / self.hand_source.get_width())
        self.hand_art = pygame.transform.smoothscale(self.hand_source, (hand_width, hand_height))
        bar_width = min(int(width * 0.69), 690)
        bar_height = round(self.bar_source.get_height() * bar_width / self.bar_source.get_width())
        self.bar_art = pygame.transform.smoothscale(self.bar_source, (bar_width, bar_height))
        marker_size = max(54, int(height * 0.105))
        self.marker_art = pygame.transform.smoothscale(self.marker_source, (marker_size, marker_size))

    def _draw_hallway(self, screen: pygame.Surface, progress: float) -> None:
        width, height = screen.get_size()
        source_w, source_h = self.hallway_source.get_size()
        eased = progress * progress * (3.0 - 2.0 * progress)
        zoom = 1.0 + 1.45 * eased
        crop_w = source_w / zoom
        crop_h = source_h / zoom
        center_x = source_w * 0.5
        center_y = source_h * (0.50 - 0.055 * eased)
        crop = pygame.Rect(0, 0, round(crop_w), round(crop_h))
        crop.center = (round(center_x), round(center_y))
        crop.clamp_ip(self.hallway_source.get_rect())
        view = self.hallway_source.subsurface(crop)
        screen.blit(pygame.transform.smoothscale(view, (width, height)), (0, 0))
        tint = pygame.Surface((width, height), pygame.SRCALPHA)
        tint.fill((5, 27, 50, 34))
        screen.blit(tint, (0, 0))

    def _draw_hand(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        art = self.hand_art
        layer = pygame.Surface(art.get_size(), pygame.SRCALPHA)
        scale_x = art.get_width() / self.hand_bounds.width
        scale_y = art.get_height() / self.hand_bounds.height
        coffee_x = (480 - self.hand_bounds.x) * scale_x
        coffee_y = (187 - self.hand_bounds.y) * scale_y
        base_w = 176 * scale_x
        base_h = 52 * scale_y
        level = max(0.0, min(1.0, self.coffee))
        cavity = pygame.Rect(0, 0, round(base_w), max(5, round(base_h)))
        cavity.center = (round(coffee_x), round(coffee_y))
        pygame.draw.ellipse(layer, (45, 27, 21), cavity)
        if level > 0.0:
            coffee_rect = pygame.Rect(0, 0, round(base_w * (0.38 + 0.62 * level)),
                                      max(3, round(base_h * (0.20 + 0.80 * level))))
            coffee_rect.center = (round(coffee_x), round(coffee_y + (1.0 - level) * base_h * 0.23))
            pygame.draw.ellipse(layer, COFFEE_TOP, coffee_rect)
        layer.blit(art, (0, 0))
        angle = -self.balance * 12.0
        rotated = pygame.transform.rotate(layer, angle)
        center = (int(width * 0.57), int(height * 0.69))
        screen.blit(rotated, rotated.get_rect(center=center))

    def _draw_balance(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        bar = self.bar_art
        bar_rect = bar.get_rect(midtop=(width // 2, 82))
        screen.blit(bar, bar_rect)
        left = bar_rect.left + int(bar_rect.width * 0.10)
        right = bar_rect.right - int(bar_rect.width * 0.10)
        x = int((left + right) / 2 + self.balance * (right - left) / 2)
        marker = self.marker_art
        marker_rect = marker.get_rect(center=(x, bar_rect.centery))
        screen.blit(marker, marker_rect)
        draw_text_centered(screen, self.small_font, "KEEP THE CUP IN THE CENTRE", WHITE,
                           (width // 2, bar_rect.bottom + 16))

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._prepare_art(width, height)
        progress = min(1.0, self.elapsed / DURATION)
        self._draw_hallway(screen, progress)

        remaining = max(0, math.ceil(DURATION - self.elapsed))
        timer = self.font.render(f"{remaining}s", True, WHITE)
        timer_box = timer.get_rect(topleft=(18, 16)).inflate(22, 12)
        pygame.draw.rect(screen, NAVY, timer_box, border_radius=10)
        screen.blit(timer, timer.get_rect(center=timer_box.center))

        if self.mode == "calibrate":
            self.draw_calibration(screen)
            return

        self._draw_balance(screen)
        self._draw_hand(screen)
        for x, y, _, _, life in self.drops:
            pygame.draw.circle(screen, COFFEE, (int(x), int(y)), max(3, int(6 * min(1.0, life))))

        meter_w = min(360, int(width * 0.42))
        draw_bar(screen, (width // 2 - meter_w // 2, height - 62, meter_w, 18), self.coffee,
                 GOOD if self.coffee > 0.35 else BAD, back=(48, 59, 67), radius=8)
        draw_text_centered(screen, self.small_font, f"COFFEE LEFT  {self.coffee * 100:.0f}%", WHITE,
                           (width // 2, height - 78))

        if self.mode == "ready":
            panel = pygame.Surface((width, height), pygame.SRCALPHA)
            panel.fill((5, 25, 45, 145))
            screen.blit(panel, (0, 0))
            draw_text_centered(screen, self.big_font, "STEADY...", WHITE, (width // 2, height // 2 - 25))
            draw_text_centered(screen, self.font, "Tilt your head to keep the marker centred", PALE,
                               (width // 2, height // 2 + 30))

        draw_camera_preview(screen, self.tracker)
        info = f"Face tracking: {self.tracker.backend}" if self.tracker.available else "Camera tracking unavailable"
        draw_status_line(screen, self.small_font, info, WHITE)
        self.draw_face_lost(screen, 40)
