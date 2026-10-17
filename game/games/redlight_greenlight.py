from __future__ import annotations

import math
import random
from statistics import median

import pygame

from game.calibrated_minigame import CalibratedMinigame
from game.minigame import Action
from game.tracking import BodyTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

MEETING_SECONDS = 45.0
INTRO_SECONDS = 4.2
FIRST_CLEAR_SECONDS = 6.5
CLEAR_MIN = 4.0
CLEAR_MAX = 6.2
APPROACH_SECONDS = 1.15
FIRST_APPROACH_SECONDS = 1.6
WATCH_MIN = 2.5
WATCH_MAX = 3.5
DEPART_SECONDS = 1.15
STOP_GRACE = 0.95
SPRINT_SPEED = 7.0
WALK_SPEED = 1.2
PUMP_THRESHOLD = 0.9
DEFAULT_STILL_THRESHOLD = 0.42
CAUGHT_AFTER = 0.2
CHAT_SECONDS = 2.5
RESULT_SECONDS = 2.8

NAVY = (13, 35, 57)
BLUE = (40, 123, 181)
PALE_BLUE = (154, 207, 232)
CARPET = (54, 65, 75)
WALL = (221, 218, 207)
TRIM = (102, 87, 72)
DOOR = (73, 91, 104)
WHITE = (247, 247, 242)
INK = (25, 32, 38)
AMBER = (245, 178, 55)
RED = (219, 69, 72)
GREEN = (72, 177, 113)
BAR_BACK = (58, 70, 80)


class RedLightGreenLight(CalibratedMinigame):
    title = "Act Natural"
    tracker_cls = BodyTracker
    distance_tolerance = 0.38

    def __init__(self, screen: pygame.Surface, tracker: BodyTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.heading_font = pygame.font.Font(None, 62)
        self.countdown_font = pygame.font.Font(None, 42)
        self.cue_font = pygame.font.Font(None, 50)
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Run in Place", "Pump your arms to sprint down the clear hallway"),
            Action("Act Natural", "Stand still to walk casually past colleagues"),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.course = 0.0
        self.phase = "clear"
        self.phase_time = 0.0
        self.phase_duration = FIRST_CLEAR_SECONDS
        self.encounter = 0
        self.exposure = 0.0
        self.caught_this_encounter = False
        self.chat_timer = 0.0
        self.intro_timer = INTRO_SECONDS
        self.result: bool | None = None
        self.result_timer = 0.0
        self.running_detected = False
        self.body_visible = False
        self.still_threshold = DEFAULT_STILL_THRESHOLD
        self.animation_time = 0.0
        self.status = "Hallway clear - run!"

    def read_sample(self) -> tuple[float, float] | None:
        body = self.tracker.body if self.tracker.available else None
        self.body_visible = body is not None
        return None if body is None else (body[2], body[1])

    def on_calibrated(self, samples: list[tuple[float, float]]) -> None:
        self.neutral = median(sample[0] for sample in samples)
        baseline = median(sample[1] for sample in samples)
        self.still_threshold = max(DEFAULT_STILL_THRESHOLD, baseline * 3.5)
        self.phase = "clear"
        self.phase_time = 0.0
        self.phase_duration = FIRST_CLEAR_SECONDS

    def calibration_prompt(self) -> str:
        if self.body_visible:
            return "Stand naturally - measuring your normal body sway"
        return "Show your head, shoulders and upper body"

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.animation_time += dt

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        if self.result is not None:
            self.result_timer += dt
            if self.result_timer >= RESULT_SECONDS:
                self.finish(self.result)
            return

        camera = self.tracker.available
        body = self.tracker.body if camera else None
        if camera and body is None:
            self.running_detected = False
            self.status = "Paused - step back into view"
            return

        pump, motion, width, hands_visible = body if camera else (0.0, 0.0, 0.0, True)
        if camera and not self.distance_ok(width):
            self.running_detected = False
            self.status = "Paused - return to your calibrated distance"
            return

        if self.intro_timer > 0:
            self.intro_timer = max(0.0, self.intro_timer - dt)
            return

        self.elapsed += dt
        self.phase_time += dt
        self.chat_timer = max(0.0, self.chat_timer - dt)
        self._update_phase()

        camera_running = hands_visible and pump >= PUMP_THRESHOLD
        running = camera_running
        moving = motion > self.still_threshold
        can_sprint = self.phase in ("clear", "approaching", "departing")
        self.running_detected = running and can_sprint and self.chat_timer <= 0

        if self.phase == "clear":
            self.exposure = max(0.0, self.exposure - dt * 3)
            if running:
                self.status = "Hallway clear - sprint!"
            elif camera and not hands_visible:
                self.status = "Bring both hands into view to run"
            else:
                self.status = "Clear, but you're only walking"
        elif self.phase == "approaching":
            self.exposure = max(0.0, self.exposure - dt * 3)
            self.status = "Act natural! Stop moving"
        elif self.phase == "watching":
            if self.phase_time < STOP_GRACE:
                self.exposure = max(0.0, self.exposure - dt * 2)
                self.status = "Act natural!"
            elif moving and not self.caught_this_encounter:
                self.exposure = min(CAUGHT_AFTER, self.exposure + dt)
                self.status = "They're noticing..."
                if self.exposure >= CAUGHT_AFTER:
                    self._get_caught()
            elif self.chat_timer > 0:
                self.status = "Got a quick minute?"
            else:
                self.exposure = max(0.0, self.exposure - dt * 3)
                self.status = "Casual. Completely normal."
        else:
            self.exposure = max(0.0, self.exposure - dt * 3)
            self.status = "They're gone - go!"

        if self.chat_timer <= 0:
            speed = SPRINT_SPEED if self.running_detected else WALK_SPEED
            self.course = min(100.0, self.course + speed * dt)

        if self.course >= 100.0:
            self._finish_game(True)
        elif self.elapsed >= MEETING_SECONDS:
            self._finish_game(False)

    def _get_caught(self) -> None:
        self.caught_this_encounter = True
        self.chat_timer = CHAT_SECONDS
        self.exposure = 0.0
        self.running_detected = False
        self.status = "Got a quick minute?"

    def _finish_game(self, won: bool) -> None:
        self.result = won
        self.result_timer = 0.0
        self.running_detected = False

    def _update_phase(self) -> None:
        if self.phase_time < self.phase_duration:
            return
        if self.phase == "clear":
            self.phase = "approaching"
            self.encounter += 1
            self.phase_duration = FIRST_APPROACH_SECONDS if self.encounter == 1 else APPROACH_SECONDS
            self.caught_this_encounter = False
        elif self.phase == "approaching":
            self.phase = "watching"
            self.phase_duration = random.uniform(WATCH_MIN, WATCH_MAX)
        elif self.phase == "watching":
            self.phase = "departing"
            self.phase_duration = DEPART_SECONDS
        else:
            self.phase = "clear"
            self.phase_duration = random.uniform(CLEAR_MIN, CLEAR_MAX)
        self.phase_time = 0.0
        self.exposure = 0.0

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        screen.fill(NAVY)
        horizon = int(height * 0.6)
        self._draw_hallway(screen, width, height, horizon)
        self._draw_destination(screen, width, horizon)
        self._draw_colleague(screen, width, height, horizon)
        self._draw_player(screen, width, height, horizon)
        self._draw_hud(screen, width, height)
        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            body = self.tracker.body
            hands = "visible" if body and body[3] else "lowered/off-screen"
            info = f"Body tracking: {self.tracker.backend}   hands: {hands}   C: recalibrate"
        else:
            info = "No camera tracking - A: run / D: act natural"
        draw_status_line(screen, self.small_font, info, WHITE)

        if self.intro_timer > 0 and self.mode == "play":
            self._draw_intro(screen, width, height)
        if self.result is not None:
            self._draw_result(screen, width, height)

    def _draw_hallway(self, screen: pygame.Surface, width: int, height: int, horizon: int) -> None:
        pygame.draw.rect(screen, WALL, (0, 0, width, horizon))
        pygame.draw.polygon(screen, CARPET, [(0, height), (width, height), (int(width * 0.62), horizon), (int(width * 0.38), horizon)])
        pygame.draw.polygon(screen, (201, 198, 188), [(0, 0), (int(width * 0.38), horizon), (0, horizon)])
        pygame.draw.polygon(screen, (210, 207, 197), [(width, 0), (int(width * 0.62), horizon), (width, horizon)])
        pygame.draw.line(screen, TRIM, (0, horizon), (width, horizon), 5)

        for index in range(1, 7):
            depth = index / 7
            y = int(height + (horizon - height) * depth * depth)
            left = int((width * 0.38) * depth)
            right = width - left
            pygame.draw.line(screen, (78, 89, 97), (left, y), (right, y), 2)

        for side in (-1, 1):
            for index in range(3):
                y = int(horizon * (0.3 + index * 0.23))
                door_w = max(35, int(width * (0.12 - index * 0.018)))
                door_h = max(70, int(height * (0.29 - index * 0.035)))
                if side < 0:
                    x = int(width * (0.03 + index * 0.09))
                else:
                    x = width - int(width * (0.03 + index * 0.09)) - door_w
                pygame.draw.rect(screen, DOOR, (x, y, door_w, door_h), border_radius=3)
                knob_x = x + door_w - 9 if side < 0 else x + 9
                pygame.draw.circle(screen, AMBER, (knob_x, y + door_h // 2), 3)

        for x in (int(width * 0.28), int(width * 0.72)):
            pygame.draw.line(screen, WHITE, (x, 16), (width // 2, horizon - 12), 5)

    def _draw_destination(self, screen: pygame.Surface, width: int, horizon: int) -> None:
        door = pygame.Rect(width // 2 - 62, horizon - 155, 124, 155)
        pygame.draw.rect(screen, NAVY, door, border_radius=5)
        pygame.draw.rect(screen, PALE_BLUE, door.inflate(-12, -12), border_radius=3)
        pygame.draw.line(screen, NAVY, (door.centerx, door.top + 6), (door.centerx, door.bottom - 6), 4)
        sign = self.small_font.render("MEETING ROOM", True, WHITE)
        sign_box = sign.get_rect(center=(door.centerx, door.top - 18)).inflate(18, 8)
        pygame.draw.rect(screen, NAVY, sign_box, border_radius=5)
        screen.blit(sign, sign.get_rect(center=sign_box.center))

    def _draw_colleague(self, screen: pygame.Surface, width: int, height: int, horizon: int) -> None:
        if self.phase == "clear":
            return
        progress = min(1.0, self.phase_time / max(self.phase_duration, 0.01))
        if self.phase == "approaching":
            x = int(width * (0.88 - progress * 0.22))
        elif self.phase == "watching":
            x = int(width * (0.66 - progress * 0.25))
        else:
            x = int(width * (0.41 - progress * 0.34))
        y = horizon + int(height * 0.08)
        scale = max(0.75, height / 720)
        head = int(19 * scale)
        body_h = int(76 * scale)
        pygame.draw.ellipse(screen, (35, 42, 47), (x - 35, y + body_h + 14, 70, 16))
        pygame.draw.rect(screen, (116, 79, 126), (x - 25, y, 50, body_h), border_radius=14)
        pygame.draw.circle(screen, (196, 148, 113), (x, y - head + 2), head)
        pygame.draw.arc(screen, (52, 37, 32), (x - head, y - head * 2, head * 2, head * 2), math.pi, math.pi * 2, 7)
        look = -5 if self.phase == "watching" else 3
        pygame.draw.circle(screen, INK, (x - 6 + look, y - head), 2)
        pygame.draw.circle(screen, INK, (x + 6 + look, y - head), 2)
        pygame.draw.line(screen, (196, 148, 113), (x - 20, y + 18), (x - 35, y + 58), 8)
        pygame.draw.line(screen, (196, 148, 113), (x + 20, y + 18), (x + 35, y + 58), 8)

    def _draw_player(self, screen: pygame.Surface, width: int, height: int, horizon: int) -> None:
        progress = max(0.0, min(1.0, self.course / 100))
        depth = progress ** 0.72
        x = width // 2
        y = int(height - 74 + (horizon + 30 - (height - 74)) * depth)
        scale = 1.0 - 0.6 * depth
        head = max(6, int(14 * scale))
        torso = max(13, int(38 * scale))
        limb = max(9, int(29 * scale))
        stroke = max(3, int(7 * scale))
        sprinting = self.running_detected
        frequency = 15 if sprinting else 5
        amount = 0.62 if sprinting else 0.2
        swing = int(math.sin(self.animation_time * frequency) * limb * amount)
        lean = int(8 * scale) if sprinting else 0
        shoulder_y = y - torso
        color = BLUE if sprinting else NAVY

        pygame.draw.circle(screen, (188, 135, 98), (x + lean, shoulder_y - head - 2), head)
        pygame.draw.line(screen, color, (x + lean, shoulder_y), (x, y), stroke)
        pygame.draw.line(screen, color, (x + lean, shoulder_y + 3), (x - limb // 2, shoulder_y + limb + swing), stroke)
        pygame.draw.line(screen, color, (x + lean, shoulder_y + 3), (x + limb // 2, shoulder_y + limb - swing), stroke)
        pygame.draw.line(screen, INK, (x, y), (x - limb // 3, y + limb - swing // 2), stroke)
        pygame.draw.line(screen, INK, (x, y), (x + limb // 3, y + limb + swing // 2), stroke)
        if sprinting:
            for offset in (18, 30, 42):
                pygame.draw.line(screen, PALE_BLUE, (x - int(offset * scale), shoulder_y + offset // 3), (x - int((offset + 12) * scale), shoulder_y + offset // 3), 3)

    def _draw_hud(self, screen: pygame.Surface, width: int, height: int) -> None:
        remaining = max(0, math.ceil(MEETING_SECONDS - self.elapsed))
        timer = self.countdown_font.render(f"Meeting starts in 00:{remaining:02d}", True, WHITE)
        timer_box = timer.get_rect(topleft=(22, 18)).inflate(24, 14)
        pygame.draw.rect(screen, NAVY, timer_box, border_radius=10)
        screen.blit(timer, timer.get_rect(center=timer_box.center))

        bar_width = min(390, int(width * 0.43))
        bar_x = width // 2 - bar_width // 2
        draw_bar(screen, (bar_x, 84, bar_width, 15), self.course / 100, GREEN, back=BAR_BACK, radius=7)
        draw_text_centered(screen, self.small_font, f"MEETING ROOM  {self.course:.0f}%", INK, (width // 2, 116))

        cue, cue_color = self._cue()
        cue_surface = self.cue_font.render(cue, True, WHITE)
        cue_box = cue_surface.get_rect(midtop=(width // 2, 138)).inflate(36, 18)
        pygame.draw.rect(screen, cue_color, cue_box, border_radius=12)
        screen.blit(cue_surface, cue_surface.get_rect(center=cue_box.center))

        status = self.font.render(self.status, True, WHITE)
        status_box = status.get_rect(midtop=(width // 2, cue_box.bottom + 10)).inflate(24, 10)
        pygame.draw.rect(screen, NAVY, status_box, border_radius=8)
        screen.blit(status, status.get_rect(center=status_box.center))

        if self.phase == "watching" and not self.caught_this_encounter:
            draw_bar(screen, (width // 2 - 120, status_box.bottom + 8, 240, 9), self.exposure / CAUGHT_AFTER, RED, back=BAR_BACK, radius=4)

        if self.mode == "calibrate":
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((13, 35, 57, 205))
            screen.blit(overlay, (0, 0))
            draw_text_centered(screen, self.heading_font, "GETTING YOUR BEARINGS", WHITE, (width // 2, height // 2 - 110))
            self.draw_calibration(screen)

    def _cue(self) -> tuple[str, tuple[int, int, int]]:
        if self.chat_timer > 0:
            return "QUICK CHAT", RED
        if self.phase == "clear":
            return "HALLWAY CLEAR - RUN", GREEN
        if self.phase == "approaching":
            return "ACT NATURAL!", AMBER
        if self.phase == "watching":
            return "WALK CASUALLY", BLUE
        return "THEY'RE GONE - GO!", GREEN

    def _draw_intro(self, screen: pygame.Surface, width: int, height: int) -> None:
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((13, 35, 57, 225))
        screen.blit(overlay, (0, 0))
        draw_text_centered(screen, self.heading_font, "LATE FOR YOUR MEETING", AMBER, (width // 2, height // 2 - 95))
        draw_text_centered(screen, self.font, "Run when the hallway is clear.", WHITE, (width // 2, height // 2 - 25))
        draw_text_centered(screen, self.font, "Stand still to walk casually past colleagues.", WHITE, (width // 2, height // 2 + 22))
        draw_text_centered(screen, self.small_font, "The meeting clock starts when this message disappears.", PALE_BLUE, (width // 2, height // 2 + 78))

    def _draw_result(self, screen: pygame.Surface, width: int, height: int) -> None:
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((13, 35, 57, 232))
        screen.blit(overlay, (0, 0))
        if self.result:
            heading = "MADE IT"
            line = "Morning. Been here ages."
            color = GREEN
        else:
            heading = "TOO LATE"
            line = "The meeting started without you."
            color = RED
        draw_text_centered(screen, self.heading_font, heading, color, (width // 2, height // 2 - 45))
        draw_text_centered(screen, self.font, line, WHITE, (width // 2, height // 2 + 25))
