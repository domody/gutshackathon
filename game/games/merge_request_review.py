from __future__ import annotations

import math
import os
import random

import numpy as np
import pygame

from game.minigame import Action, Minigame
from game.tracking import HandTracker
from game.ui import draw_camera_preview, draw_status_line, draw_text_centered

TARGET_REQUESTS = 10
LIVES = 3
READY_SECONDS = 2.8
GESTURE_HOLD = 0.18
RESULT_SECONDS = 0.72

GOOD = (62, 176, 92)
BAD = (232, 72, 65)
NAVY = (19, 39, 67)
WHITE = (250, 250, 246)


def ease_out_cubic(value: float) -> float:
    return 1.0 - (1.0 - value) ** 3


def chroma_surface(path: str) -> pygame.Surface:
    image = pygame.image.load(path).convert_alpha()
    rgb = pygame.surfarray.array3d(image)
    alpha = pygame.surfarray.pixels_alpha(image)
    red = rgb[:, :, 0].astype(np.int16)
    green = rgb[:, :, 1].astype(np.int16)
    blue = rgb[:, :, 2].astype(np.int16)
    pink = (
        (red > 90)
        & (blue > 90)
        & (green < np.minimum(red, blue) * 0.72)
        & (np.abs(red - blue) < 115)
    )
    alpha[pink] = 0
    del alpha
    bounds = image.get_bounding_rect(min_alpha=8)
    return image.subsurface(bounds).copy() if bounds.width and bounds.height else image


class MergeRequestReview(Minigame):
    title = "Merge Request Review"
    tracker_cls = HandTracker

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.label_font = pygame.font.Font(None, 30)
        asset_dir = os.path.join(os.path.dirname(__file__), "assets")
        self.background_source = pygame.image.load(
            os.path.join(asset_dir, "merge_review_background.png")
        ).convert()
        self.request_sources = {
            True: chroma_surface(os.path.join(asset_dir, "merge_request_good.png")),
            False: chroma_surface(os.path.join(asset_dir, "merge_request_bad.png")),
        }
        self.hand_sources = {
            "palm": chroma_surface(os.path.join(asset_dir, "merge_accept_hand.png")),
            "fist": chroma_surface(os.path.join(asset_dir, "merge_reject_fist.png")),
        }
        self._scaled_size: tuple[int, int] | None = None
        self._background: pygame.Surface | None = None
        self._requests: dict[bool, pygame.Surface] = {}
        self._hands: dict[str, pygame.Surface] = {}
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Open Hand", "Open your hand to accept a good merge request"),
            Action("Closed Fist", "Make a fist to reject a bad merge request"),
        )

    @property
    def negative_progress(self) -> float:
        return 1.0 - self.lives / LIVES

    def start(self) -> None:
        super().start()
        good_count = TARGET_REQUESTS // 2
        self.queue = [True] * good_count + [False] * (TARGET_REQUESTS - good_count)
        random.shuffle(self.queue)
        if len(self.queue) > 1 and self.queue[0] == self.queue[1]:
            opposite = next((i for i, value in enumerate(self.queue[1:], 1) if value != self.queue[0]), None)
            if opposite is not None:
                self.queue[1], self.queue[opposite] = self.queue[opposite], self.queue[1]
        self.current_good = self.queue[0]
        self.index = 0
        self.resolved = 0
        self.correct = 0
        self.lives = LIVES
        self.mode = "ready"
        self.ready_t = 0.0
        self.hold_t = 0.0
        self.result_t = 0.0
        self.hand: str | None = None
        self.decision: str | None = None
        self.decision_correct = False
        self.flash_text = ""
        self.shake = 0.0
        self.gesture_armed = True

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self._read_hand()
        self.shake = max(0.0, self.shake - dt)

        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "choose"
            return

        if self.mode == "result":
            self.result_t += dt
            if self.result_t >= RESULT_SECONDS:
                self._next_request()
            return

        keys = pygame.key.get_pressed()
        fallback = "palm" if keys[pygame.K_a] else "fist" if keys[pygame.K_d] else None
        active = self.hand or fallback
        if not self.gesture_armed:
            if active is None:
                self.gesture_armed = True
            return
        if active in ("palm", "fist"):
            self.hold_t += dt
            if self.hold_t >= GESTURE_HOLD:
                self._decide(active)
        else:
            self.hold_t = max(0.0, self.hold_t - dt * 2.5)

    def _read_hand(self) -> None:
        self.hand = self.tracker.gesture if self.tracker.available else None

    def _decide(self, gesture: str) -> None:
        if self.mode != "choose":
            return
        self.decision = gesture
        self.decision_correct = (gesture == "palm") == self.current_good
        self.resolved += 1
        if self.decision_correct:
            self.correct += 1
            self.flash_text = "MERGED" if gesture == "palm" else "DECLINED"
        else:
            self.lives -= 1
            self.flash_text = "THAT SHOULD HAVE BEEN DECLINED" if gesture == "palm" else "THAT ONE WAS SAFE"
            self.shake = 0.35
        self.result_t = 0.0
        self.mode = "result"
        self.gesture_armed = False

    def _next_request(self) -> None:
        if self.lives <= 0:
            self.finish(False)
            return
        self.index += 1
        if self.index >= len(self.queue):
            self.finish(True)
            return
        self.current_good = self.queue[self.index]
        self.decision = None
        self.hold_t = 0.0
        self.result_t = 0.0
        self.mode = "choose"

    def _scale_assets(self, size: tuple[int, int]) -> None:
        if self._scaled_size == size:
            return
        w, h = size
        self._scaled_size = size
        self._background = pygame.transform.smoothscale(self.background_source, size)
        request_size = max(124, int(h * 0.22))
        self._requests = {
            good: pygame.transform.smoothscale(source, (request_size, request_size))
            for good, source in self.request_sources.items()
        }
        hand_h = max(155, int(h * 0.28))
        self._hands = {}
        for gesture, source in self.hand_sources.items():
            ratio = source.get_width() / source.get_height()
            self._hands[gesture] = pygame.transform.smoothscale(source, (int(hand_h * ratio), hand_h))

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        self._scale_assets((w, h))
        offset_x = int(math.sin(self.result_t * 65) * 7) if self.shake > 0 else 0
        screen.blit(self._background, (offset_x, 0))
        self._draw_request(screen)
        self._draw_hud(screen)

        if self.mode == "ready":
            panel = pygame.Surface((w, h), pygame.SRCALPHA)
            panel.fill((8, 22, 42, 155))
            screen.blit(panel, (0, 0))
            draw_text_centered(screen, self.big_font, "REVIEW THE MERGE REQUESTS", WHITE, (w // 2, int(h * 0.30)))
            draw_text_centered(screen, self.font, "OPEN HAND  ACCEPT", (115, 232, 145), (w // 2, int(h * 0.42)))
            draw_text_centered(screen, self.font, "CLOSED FIST  DECLINE", (255, 140, 125), (w // 2, int(h * 0.49)))
            draw_text_centered(screen, self.small_font, "Good changes have checks. Risky changes have crosses.", WHITE, (w // 2, int(h * 0.58)))

    def _draw_request(self, screen: pygame.Surface) -> None:
        if self.mode == "ready":
            return
        w, h = screen.get_size()
        request = self._requests[self.current_good]
        start = pygame.Vector2(w * 0.50, h * 0.42)
        center = start
        scale = 1.0

        if self.mode == "result" and self.decision is not None:
            progress = min(1.0, self.result_t / RESULT_SECONDS)
            eased = ease_out_cubic(progress)
            target = pygame.Vector2(w * (0.255 if self.decision == "palm" else 0.745), h * 0.69)
            center = start.lerp(target, eased)
            if self.decision == "palm":
                center.y -= math.sin(progress * math.pi) * h * 0.15
            else:
                center.x += math.sin(progress * math.pi) * w * 0.035
                center.y += progress * progress * h * 0.045
            scale = 1.0 - progress * 0.55
            self._draw_action_hand(screen, progress)

        if scale != 1.0:
            size = max(18, int(request.get_width() * scale))
            shown = pygame.transform.smoothscale(request, (size, size))
        else:
            shown = request
        rect = shown.get_rect(center=(round(center.x), round(center.y)))
        screen.blit(shown, rect)

        if self.mode == "choose":
            kind = "SAFE TO MERGE" if self.current_good else "RISKY CHANGES"
            color = GOOD if self.current_good else BAD
            draw_text_centered(screen, self.label_font, kind, color, (w // 2, int(h * 0.235)))
            gesture = "OPEN HAND TO ACCEPT" if self.current_good else "CLOSED FIST TO DECLINE"
            draw_text_centered(screen, self.small_font, gesture, NAVY, (w // 2, int(h * 0.57)))
            if self.hold_t > 0:
                bar = pygame.Rect(0, 0, int(w * 0.16), 9)
                bar.center = (w // 2, int(h * 0.61))
                pygame.draw.rect(screen, (204, 211, 220), bar, border_radius=5)
                fill = bar.copy()
                fill.width = int(bar.width * min(1.0, self.hold_t / GESTURE_HOLD))
                pygame.draw.rect(screen, GOOD if self.hand == "palm" else BAD, fill, border_radius=5)
        elif self.mode == "result":
            color = GOOD if self.decision_correct else BAD
            draw_text_centered(screen, self.font, self.flash_text, color, (w // 2, int(h * 0.22)))

    def _draw_action_hand(self, screen: pygame.Surface, progress: float) -> None:
        if self.decision is None:
            return
        w, h = screen.get_size()
        sprite = self._hands[self.decision]
        if self.decision == "palm":
            x = w * 0.50
            y = h * (0.67 - 0.035 * math.sin(progress * math.pi))
            rotation = -10 + math.sin(progress * math.pi) * 13
        else:
            x = w * (0.48 + min(1.0, progress * 2.5) * 0.08)
            y = h * 0.65
            rotation = -18
        shown = pygame.transform.rotozoom(sprite, rotation, 1.0)
        screen.blit(shown, shown.get_rect(center=(round(x), round(y))))

    def _draw_hud(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        draw_text_centered(screen, self.small_font, f"REVIEW {min(self.resolved + 1, TARGET_REQUESTS)} / {TARGET_REQUESTS}", WHITE, (w // 2, int(h * 0.087)))

        for i in range(LIVES):
            color = BAD if i < self.lives else (155, 166, 179)
            x = int(w * 0.18) + i * 24
            pygame.draw.circle(screen, color, (x, int(h * 0.22)), 8)

        draw_camera_preview(screen, self.tracker)
        status = "Open hand accepts   Closed fist declines" if self.tracker.available else "Camera unavailable   A accepts   D declines"
        draw_status_line(screen, self.small_font, status)
