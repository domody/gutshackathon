"""A deliberate, retakeable badge photo using the existing camera owner."""
from collections.abc import Callable
import math

import pygame

from game.assets import cover, get_font
from game.employee import EmployeeRecord
from game.ui.screen import Screen


class BadgePhotoScreen(Screen):
    background = (8, 28, 50)
    suppress_corner_score = True
    fade_in = 0.3
    fade_out = 0.3

    def __init__(self, tracker, record: EmployeeRecord, on_continue: Callable[[], None]) -> None:
        self.tracker, self.record, self.on_continue = tracker, record, on_continue
        self.mode = "ready"
        self.countdown = 0.0
        self.photo = None
        self.buttons: dict[str, pygame.Rect] = {}

    def gesture_continue(self) -> None:
        if self.mode == "review":
            self._accept()
        elif self.mode == "ready" and self.tracker.snapshot_surface() is not None:
            self.mode = "countdown"
            self.countdown = 3.0

    def update(self, dt: float) -> None:
        if self.mode != "countdown":
            return
        frame = self.tracker.snapshot_surface()
        if frame is None:
            self.mode = "ready"
            return
        self.countdown -= dt
        if self.countdown <= 0:
            self.photo = frame.copy()
            self.mode = "review"

    def _accept(self) -> None:
        if self.photo is not None:
            self.record.set_photo(self.photo)
        self.on_continue()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        for name, rect in self.buttons.items():
            if rect.collidepoint(event.pos):
                if name == "Retake":
                    self.photo = None
                    self.mode = "ready"
                elif name == "Skip photo":
                    self.on_continue()
                else:
                    self.gesture_continue()
                return

    def draw(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        def label(text, y, size=30, color=(248, 246, 233)):
            rendered = get_font(size).render(text, True, color)
            surface.blit(rendered, rendered.get_rect(midtop=(w // 2, y)))
        label("ONE PHOTO FOR YOUR BADGE", int(h * 0.06), max(26, min(54, w // 24)))
        label("Saved on this computer only. Your first-day review needs a face.", int(h * 0.15), max(18, min(28, w // 38)))
        box = pygame.Rect(0, 0, min(int(w * 0.6), int(h * 0.68)), int(h * 0.50))
        box.center = (w // 2, int(h * 0.47))
        pygame.draw.rect(surface, (247, 243, 225), box.inflate(16, 16), border_radius=18)
        frame = self.photo if self.mode == "review" else self.tracker.snapshot_surface()
        if frame is not None:
            surface.blit(cover(frame, box.size), box)
        else:
            pygame.draw.rect(surface, (34, 56, 76), box)
            label("Camera not ready - you can skip this photo", box.centery, max(18, min(26, w // 40)))
        if self.mode == "countdown":
            number = get_font(110).render(str(max(1, math.ceil(self.countdown))), True, (255, 215, 90))
            surface.blit(number, number.get_rect(center=box.center))
        elif self.mode == "review":
            label("Looking employable. Pinch to use this photo.", int(h * 0.76))
        else:
            label("Pinch for a three-second countdown. Strike a pose!", int(h * 0.76), max(20, min(30, w // 34)))
        names = ("Retake", "Use photo") if self.mode == "review" else ("Take photo", "Skip photo")
        self.buttons = {}
        if self.mode == "countdown":
            return
        for index, name in enumerate(names):
            rect = pygame.Rect(0, 0, min(210, w // 3), 48)
            rect.center = (w // 2 + (index * 2 - 1) * min(125, w // 5), int(h * 0.90))
            pygame.draw.rect(surface, (36, 91, 125), rect, border_radius=12)
            text = get_font(26).render(name, True, (250, 248, 236))
            surface.blit(text, text.get_rect(center=rect.center))
            self.buttons[name] = rect
