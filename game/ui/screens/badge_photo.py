from __future__ import annotations

import math
from collections.abc import Callable

import pygame

from game.audio import sound_bank
from game.assets import cover, get_font
from game.employee import EmployeeRecord
from game.ui.screen import Screen


class BadgePhotoScreen(Screen):
    background = (8, 28, 50)
    suppress_corner_score = True
    fade_in = 0.3
    fade_out = 0.3
    RETAKE_HOLD_SECONDS = 0.9
    REVIEW_GESTURE_DELAY = 0.45
    FLASH_SECONDS = 0.24

    def __init__(self, tracker, record: EmployeeRecord, on_continue: Callable[[], None]) -> None:
        self.tracker = tracker
        self.record = record
        self.on_continue = on_continue
        self.mode = "ready"
        self.countdown = 0.0
        self.photo: pygame.Surface | None = None
        self.retake_hold = 0.0
        self.review_age = 0.0
        self.flash_t = 0.0
        self.status = "PINCH TO START COUNTDOWN"

    def gesture_continue(self) -> None:
        if self.mode == "review":
            self._accept()
        elif self.mode == "ready":
            if self.tracker.snapshot_surface() is None:
                self.status = "CAMERA UNAVAILABLE. HOLD OPEN HAND TO SKIP"
            else:
                self.mode = "countdown"
                self.countdown = 3.0
                self.status = "HOLD THAT EMPLOYABLE EXPRESSION"

    def update(self, dt: float) -> None:
        if self.mode == "flash":
            self.flash_t = max(0.0, self.flash_t - dt)
            if self.flash_t <= 0.0:
                self.mode = "review"
                self.review_age = 0.0
                self.status = "OPEN HAND TO RETAKE     PINCH TO USE PHOTO"
            return
        if self.mode == "review":
            self.review_age += dt
            if self.review_age >= self.REVIEW_GESTURE_DELAY and getattr(self.tracker, "gesture", None) == "palm":
                self.retake_hold += dt
                self.status = "KEEP OPEN HAND STEADY TO RETAKE"
                if self.retake_hold >= self.RETAKE_HOLD_SECONDS:
                    self._retake()
            else:
                self.retake_hold = 0.0
                self.status = "OPEN HAND TO RETAKE     PINCH TO USE PHOTO"
            return
        if self.mode == "ready" and self.tracker.snapshot_surface() is None:
            if getattr(self.tracker, "gesture", None) == "palm":
                self.retake_hold += dt
                self.status = "KEEP OPEN HAND STEADY TO SKIP"
                if self.retake_hold >= self.RETAKE_HOLD_SECONDS:
                    self._skip()
            else:
                self.retake_hold = 0.0
                self.status = "CAMERA UNAVAILABLE. HOLD OPEN HAND TO SKIP"
            return
        if self.mode != "countdown":
            return
        frame = self.tracker.snapshot_surface()
        if frame is None:
            self.mode = "ready"
            self.status = "CAMERA FRAME LOST. PINCH TO TRY AGAIN"
            return
        self.countdown -= dt
        if self.countdown <= 0:
            self.photo = frame.copy()
            self.mode = "flash"
            self.flash_t = self.FLASH_SECONDS
            self.retake_hold = 0.0
            self.review_age = 0.0
            self.status = "PHOTO CAPTURED"
            sound_bank.play("shutter")

    def _accept(self) -> None:
        if self.photo is None:
            return
        self.record.set_photo(self.photo)
        self.mode = "leaving"
        self.on_continue()

    def _skip(self) -> None:
        self.mode = "leaving"
        self.on_continue()

    def _retake(self) -> None:
        self.photo = None
        self.mode = "ready"
        self.countdown = 0.0
        self.retake_hold = 0.0
        self.review_age = 0.0
        self.status = "PINCH TO START A NEW COUNTDOWN"

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        title_font = get_font(max(32, min(54, width // 24)))
        body_font = get_font(max(20, min(29, width // 42)))
        title = title_font.render("EMPLOYEE BADGE PHOTO", True, (255, 215, 90))
        surface.blit(title, title.get_rect(midtop=(width // 2, int(height * 0.045))))
        dialogue = body_font.render(
            "First, a photo for your employee badge. Try to look employable.",
            True,
            (240, 241, 232),
        )
        surface.blit(dialogue, dialogue.get_rect(midtop=(width // 2, int(height * 0.13))))

        box_width = min(int(width * 0.58), round(height * 0.72))
        box_height = min(int(height * 0.52), round(box_width * 0.75))
        box = pygame.Rect(0, 0, box_width, box_height)
        box.center = (width // 2, int(height * 0.47))
        frame = pygame.Surface(box.inflate(18, 18).size, pygame.SRCALPHA)
        pygame.draw.rect(frame, (247, 243, 225), frame.get_rect(), border_radius=18)
        surface.blit(frame, box.inflate(18, 18))

        image = self.photo if self.mode in ("flash", "review") else self.tracker.snapshot_surface()
        if image is not None:
            surface.blit(cover(image, box.size), box)
        else:
            pygame.draw.rect(surface, (31, 55, 76), box)
            unavailable = body_font.render("Camera not ready", True, (190, 207, 218))
            surface.blit(unavailable, unavailable.get_rect(center=box.center))

        if self.mode == "countdown":
            shade = pygame.Surface(box.size, pygame.SRCALPHA)
            shade.fill((7, 24, 39, 70))
            surface.blit(shade, box)
            number = get_font(max(100, height // 5)).render(
                str(max(1, math.ceil(self.countdown))), True, (255, 215, 90)
            )
            surface.blit(number, number.get_rect(center=box.center))

        if self.mode == "flash":
            strength = min(1.0, self.flash_t / self.FLASH_SECONDS)
            flash = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            flash.fill((255, 255, 248, round(245 * strength)))
            surface.blit(flash, (0, 0))

        status = body_font.render(self.status, True, (180, 211, 227))
        surface.blit(status, status.get_rect(midtop=(width // 2, int(height * 0.76))))
        if self.mode == "review":
            offset = self._action_size(surface)[0] // 2 + 16
            self._draw_action(surface, "OPEN HAND", "RETAKE", width // 2 - offset, int(height * 0.88))
            self._draw_action(surface, "PINCH", "USE PHOTO", width // 2 + offset, int(height * 0.88))
        elif self.mode == "ready" and image is not None:
            self._draw_action(surface, "PINCH", "TAKE PHOTO", width // 2, int(height * 0.88))
        elif self.mode == "ready":
            self._draw_action(surface, "OPEN HAND", "SKIP PHOTO", width // 2, int(height * 0.88))

    ACTION_LABELS = (("OPEN HAND", "RETAKE"), ("PINCH", "USE PHOTO"), ("PINCH", "TAKE PHOTO"), ("OPEN HAND", "SKIP PHOTO"))
    ACTION_PAD = 8

    def _action_fonts(self, surface: pygame.Surface) -> tuple[pygame.font.Font, pygame.font.Font]:
        size = max(14, min(22, surface.get_width() // 58))
        return get_font(size - 3), get_font(size)

    def _action_size(self, surface: pygame.Surface) -> tuple[int, int]:
        gesture_font, action_font = self._action_fonts(surface)
        content = max(
            gesture_font.size(g)[0] + action_font.size(a)[0] for g, a in self.ACTION_LABELS
        )
        width = max(content + 3 * self.ACTION_PAD, int(surface.get_width() * 0.2))
        return width, action_font.get_height() + 2 * self.ACTION_PAD

    def _draw_action(self, surface: pygame.Surface, gesture: str, action: str, x: int, y: int) -> None:
        panel = pygame.Rect((0, 0), self._action_size(surface))
        panel.center = (x, y)
        pygame.draw.rect(surface, (21, 63, 92), panel, border_radius=12)
        gesture_font, action_font = self._action_fonts(surface)
        gesture_art = gesture_font.render(gesture, True, (255, 215, 90))
        action_art = action_font.render(action, True, (249, 248, 238))
        surface.blit(gesture_art, gesture_art.get_rect(midleft=(panel.left + self.ACTION_PAD, panel.centery)))
        surface.blit(action_art, action_art.get_rect(midright=(panel.right - self.ACTION_PAD, panel.centery)))
