from __future__ import annotations

import math
import random

import pygame

from game.audio import sound_bank
from game.assets import load_image
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
    "left": ("Quick update from my side.", "Can everyone see my screen?",
             "I'll circle back on that after lunch.", "I have one small blocker to raise.",
             "The numbers are looking better this week.", "I sent the revised notes this morning.",
             "We should check that with compliance.", "I can own the follow-up action."),
    "forward": ("Let's align on today's priorities.", "This should only take a minute.",
                "Moving to the next slide now.", "Any questions before we continue?",
                "We need a decision before close of business.", "Let's keep the client outcome in mind.",
                "The deadline has moved to Friday.", "We'll finish with the action points."),
    "right": ("Just to build on that point.", "I have one quick thought to add.",
              "Could we take the details offline?", "I think someone is still on mute.",
              "The latest version is in the shared folder.", "That matches what the client requested.",
              "I'll send a summary after the meeting.", "We can test that approach this afternoon."),
}
NAMES = {"left": "MAYA", "forward": "PRESENTER", "right": "JAMIE"}


def classify_direction(yaw_off: float) -> str:
    if yaw_off <= -SIDE_THRESHOLD:
        return "left"
    if yaw_off >= SIDE_THRESHOLD:
        return "right"
    return "forward"


class WhosTalking(FaceMinigame):
    title = "Who's Talking?"
    objective = "Look toward each colleague while they speak, then face forward for the presenter."
    after_calibration = "ready"

    def __init__(self, screen: pygame.Surface, tracker: FaceTracker | None = None, *,
                 fast: bool = False, opposite: bool = False, combo: bool = False) -> None:
        super().__init__(screen, tracker)
        self.fast = fast
        self.opposite = opposite
        self.combo = combo
        self.room_source = load_image("meeting_room.png", alpha=False)
        self.people_source = {
            "left": {
                False: load_image("meeting_left_idle.png"),
                True: load_image("meeting_left_speaking.png"),
            },
            "forward": {
                False: load_image("meeting_center_idle.png"),
                True: load_image("meeting_center_speaking.png"),
            },
            "right": {
                False: load_image("meeting_right_idle.png"),
                True: load_image("meeting_right_speaking.png"),
            },
        }
        self._art_size: tuple[int, int] | None = None
        self.room_art: pygame.Surface | None = None
        self.people_art: dict[str, dict[bool, pygame.Surface]] = {}
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Look Around", "Turn your head left or right toward the person speaking"),
            Action("Face Forward", "Return to the centre when the presenter is speaking"),
        )

    @property
    def negative_progress(self) -> float:
        return 1.0 - self.done / TARGET_TURNS

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
            self.register_combo_success()
            sound_bank.play("correct")
            self.feedback = random.choice(("NATURAL.", "GOOD LISTENING.", "NAILED IT."))
            self.feedback_t = 0.65
            if self.done >= TARGET_TURNS:
                self.finish(True)
            else:
                self._new_speaker()
            return

        self.turn_left -= dt
        if self.turn_left <= 0.0:
            self.reset_combo()
            sound_bank.play("mistake")
            self.feedback = "WRONG PERSON."
            self.finish(False)

    def _draw_room(self, screen: pygame.Surface, w: int, h: int) -> None:
        self._prepare_art(w, h)
        screen.blit(self.room_art, (0, 0))
        tint = pygame.Surface((w, h), pygame.SRCALPHA)
        tint.fill((7, 34, 66, 18))
        screen.blit(tint, (0, 0))

    def _prepare_art(self, w: int, h: int) -> None:
        if self._art_size == (w, h):
            return
        self._art_size = (w, h)
        self.room_art = pygame.transform.smoothscale(self.room_source, (w, h))
        target_h = max(210, int(h * 0.43))
        self.people_art = {}
        for direction, states in self.people_source.items():
            self.people_art[direction] = {}
            for speaking, source in states.items():
                target_w = round(source.get_width() * target_h / source.get_height())
                self.people_art[direction][speaking] = pygame.transform.smoothscale(source, (target_w, target_h))

    def _draw_person(self, screen: pygame.Surface, direction: str, x: int, bottom: int,
                     active: bool, phase: float) -> None:
        sprite = self.people_art[direction][active]
        bounce = int(math.sin(phase * 8.0) * 3) if active else 0
        rect = sprite.get_rect(midbottom=(x, bottom + bounce))
        if active:
            glow = pygame.Surface((rect.width + 22, rect.height + 14), pygame.SRCALPHA)
            pygame.draw.ellipse(glow, (244, 177, 72, 70), glow.get_rect())
            screen.blit(glow, glow.get_rect(center=rect.center))
        screen.blit(sprite, rect)
        label = self.small_font.render(NAMES[direction], True, WHITE)
        label_box = label.get_rect(midtop=(x, bottom + 4)).inflate(16, 8)
        pygame.draw.rect(screen, NAVY, label_box, border_radius=7)
        screen.blit(label, label.get_rect(center=label_box.center))

    def _draw_bubble(self, screen: pygame.Surface, x: int, text: str) -> None:
        font = self.small_font
        max_text_width = 250
        words = text.split()
        lines: list[str] = []
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            if line and font.size(trial)[0] > max_text_width:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        bw = min(286, max(font.size(line)[0] for line in lines) + 28)
        bh = 22 * len(lines) + 24
        right_edge = screen.get_width() - 8
        if x > screen.get_width() * 0.66:
            right_edge = screen.get_width() - 212
        bx = max(8, min(right_edge - bw, x - bw // 2))
        by = 145
        pygame.draw.rect(screen, WHITE, (bx, by, bw, bh), border_radius=12)
        pygame.draw.rect(screen, CHASE_BLUE, (bx, by, bw, bh), 3, border_radius=12)
        tip_x = max(bx + 22, min(bx + bw - 22, x))
        pygame.draw.polygon(screen, WHITE, [(tip_x - 11, by + bh - 2), (tip_x + 11, by + bh - 2), (x, by + bh + 13)])
        pygame.draw.lines(screen, CHASE_BLUE, False,
                          [(tip_x - 11, by + bh - 2), (x, by + bh + 13), (tip_x + 11, by + bh - 2)], 3)
        for index, line in enumerate(lines):
            draw_text_centered(screen, font, line, INK, (bx + bw // 2, by + 17 + index * 22))

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        positions = {"left": int(w * 0.18), "forward": w // 2, "right": int(w * 0.82)}
        self._draw_room(screen, w, h)
        title_panel = pygame.Surface((235, 68), pygame.SRCALPHA)
        pygame.draw.rect(title_panel, (7, 34, 66, 220), title_panel.get_rect(), border_radius=0)
        screen.blit(title_panel, (0, 0))
        screen.blit(self.font.render("WHO'S TALKING?", True, WHITE), (16, 11))
        screen.blit(self.small_font.render(f"LISTENED  {self.done}/{TARGET_TURNS}", True, CHASE_LIGHT), (16, 43))

        if self.mode == "calibrate":
            self.draw_calibration(screen)
            draw_camera_preview(screen, self.tracker)
            return

        for direction in ("left", "forward", "right"):
            self._draw_person(screen, direction, positions[direction], int(h * 0.70),
                              direction == self.speaker, self.talking_t)
        self._draw_bubble(screen, positions[self.speaker], self.line)

        if self.mode == "ready":
            panel = pygame.Rect(0, 0, min(470, w - 40), 82)
            panel.center = (w // 2, int(h * 0.82))
            pygame.draw.rect(screen, NAVY, panel, border_radius=16)
            draw_text_centered(screen, self.font, "WATCH WHO'S SPEAKING", WHITE, (w // 2, panel.y + 25))
            draw_text_centered(screen, self.small_font, "Turn left, right, or face forward", CHASE_LIGHT,
                               (w // 2, panel.y + 59))
        else:
            total = TURN_SECONDS * (0.82 if self.fast else 1.0) + (1.0 if self.done == 0 else 0.0)
            frac = max(0.0, self.turn_left / total)
            cue_y = int(h * 0.79)
            cue = pygame.Surface((330, 76), pygame.SRCALPHA)
            pygame.draw.rect(cue, (248, 248, 244, 220), cue.get_rect(), border_radius=14)
            screen.blit(cue, cue.get_rect(center=(w // 2, cue_y)))
            draw_bar(screen, (w // 2 - 135, cue_y + 18, 270, 10), frac, GREEN if frac > 0.35 else RED,
                     back=(167, 169, 164), radius=6)
            direction = {"left": "LOOK LEFT", "forward": "LOOK FORWARD", "right": "LOOK RIGHT"}[self.speaker]
            draw_text_centered(screen, self.font, direction, NAVY, (w // 2, cue_y - 12))
            attention = min(self.hold / HOLD_SECONDS, self.talking_t / SPEAK_SECONDS)
            draw_bar(screen, (w // 2 - 70, cue_y + 33, 140, 6), attention, CHASE_BLUE,
                     back=(190, 191, 186), radius=4)

        if self.feedback_t > 0:
            draw_text_centered(screen, self.font, self.feedback, GREEN, (w // 2, int(h * 0.74)))
        draw_camera_preview(screen, self.tracker)
        info = f"Face tracking: {self.tracker.backend}" if self.tracker.available else "Camera tracking unavailable"
        draw_status_line(screen, self.small_font, info)
        self.draw_face_lost(screen, 76)
