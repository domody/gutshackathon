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
    after_calibration = "ready"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None, *,
                 fast: bool = False, opposite: bool = False, combo: bool = False) -> None:
        super().__init__(screen, tracker)
        self.fast = fast
        self.opposite = opposite
        self.combo = combo
        self.start()

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
        self.turn_left = TURN_SECONDS
        self.hold = 0.0
        self.current = "forward"
        self.speaker = "forward"
        self.previous_speaker = "forward"
        self.line = random.choice(SPEECH["forward"])
        self.talking_t = 0.0
        self.feedback = ""
        self.feedback_t = 0.0
        self._new_speaker(first=True)

    def _new_speaker(self, first: bool = False) -> None:
        choices = [d for d in ("left", "forward", "right") if d != self.previous_speaker]
        self.speaker = "forward" if first else random.choice(choices)
        self.previous_speaker = self.speaker
        self.line = random.choice(SPEECH[self.speaker])
        self.turn_left = TURN_SECONDS * (0.82 if self.fast else 1.0) + (1.0 if first else 0.0)
        self.hold = 0.0
        self.talking_t = 0.0

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
            self.hold = max(0.0, self.hold - dt * 2.5)

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
