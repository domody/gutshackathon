from __future__ import annotations

import math
import os
import random
from statistics import median

import pygame

from game.calibrated_minigame import CalibratedMinigame
from game.minigame import Action
from game.tracking import PullTracker
from game.tracking.pull import HandReading, PullReading
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

REACH_MINIMUM = 0.24
PULL_SIZE_RATIO = 0.79
PULL_CHEST_GAIN = 0.22
PULL_PROGRESS = 8.0
PRINTER_RESISTANCE = 0.52
RESISTANCE_DELAY = 0.85
ROUND_SECONDS = 38.0
RESULT_SECONDS = 3.4

WALL = (218, 218, 208)
DESK = (112, 80, 58)
DESK_EDGE = (71, 49, 38)
PRINTER = (67, 76, 84)
PRINTER_DARK = (35, 42, 48)
SCREEN = (143, 214, 181)
PAPER = (250, 249, 239)
PAPER_LINE = (186, 199, 201)
BLUE = (34, 111, 177)
GREEN = (64, 166, 105)
AMBER = (244, 171, 52)
RED = (215, 63, 67)
INK = (28, 35, 41)
WHITE = (248, 248, 243)
MUTED = (134, 143, 149)


class TugOfWar(CalibratedMinigame):
    title = "One Last Print"
    tracker_cls = PullTracker
    calibrate_timeout = 6.0
    distance_tolerance = 0.42

    def __init__(self, screen: pygame.Surface, tracker: PullTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.title_font = pygame.font.Font(None, 64)
        self.clock_font = pygame.font.Font(None, 46)
        self.printer_font = pygame.font.Font(None, 25)
        self.result_font = pygame.font.Font(None, 58)
        asset_dir = os.path.join(os.path.dirname(__file__), "assets")
        self.room_source = pygame.image.load(os.path.join(asset_dir, "printer_room.png")).convert()
        self.printer_source = pygame.image.load(os.path.join(asset_dir, "printer_machine.png")).convert_alpha()
        self.paper_source = pygame.image.load(os.path.join(asset_dir, "printer_paper.png")).convert_alpha()
        self.art_size: tuple[int, int] | None = None
        self.room_art: pygame.Surface | None = None
        self.printer_art: pygame.Surface | None = None
        self.paper_art: pygame.Surface | None = None
        self.paper_pile_art: pygame.Surface | None = None
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Left Pull", "Reach, make a fist, then pull your left hand to your chest"),
            Action("Right Pull", "Reach, make a fist, then pull your right hand to your chest"),
        )

    @property
    def negative_progress(self) -> float:
        return 1.0 - self.best_extraction / 100.0

    def start(self) -> None:
        super().start()
        self.result: bool | None = None
        self.result_time = 0.0
        self.elapsed = 0.0
        self.intro_timer = 0.0
        self.extraction = 0.0
        self.best_extraction = 0.0
        self.body_visible = False
        self.expected_side: str | None = None
        self.armed_sides: set[str] = set()
        self.pull_side: str | None = None
        self.pull_size = 0.0
        self.pull_distance = 0.0
        self.pull_flash = 0.0
        self.idle_time = 0.0
        self.total_pulls = 0
        self.message_index = 0
        self.next_message = 4.0
        self.status = "Reach forward with either open hand"
        self.printer_message = "Paper jam."

    def read_sample(self) -> float | None:
        reading = self.tracker.reading if self.tracker.available else None
        self.body_visible = reading is not None and reading.body_visible
        return reading.shoulder_width if self.body_visible else None

    def on_calibrated(self, samples: list[float]) -> None:
        self.neutral = median(samples)

    def calibration_prompt(self) -> str:
        if self.body_visible:
            return "Hold still - calibrating your distance"
        return "Show both shoulders to the camera"

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.pull_flash = max(0.0, self.pull_flash - dt)

        if self.result is not None:
            self.result_time += dt
            if self.result_time >= RESULT_SECONDS:
                self.finish(self.result)
            return

        if self.mode == "calibrate":
            self.update_calibration(dt)
            return

        if self.tracker.available:
            reading = self.tracker.reading
            if not reading.body_visible:
                self.status = "Paused - keep both shoulders visible"
                return
            if not self.distance_ok(reading.shoulder_width):
                self.status = "Paused - return to your calibrated distance"
                return
        else:
            reading = None

        self.elapsed += dt
        self.idle_time += dt

        if reading is not None:
            self._update_gesture(reading)

        if self.idle_time >= RESISTANCE_DELAY and self.extraction > 0:
            self.extraction = max(0.0, self.extraction - PRINTER_RESISTANCE * dt)
        self.best_extraction = max(self.best_extraction, self.extraction)

        if self.elapsed >= self.next_message:
            messages = ("Please wait.", "Still waiting.", "PC LOAD LETTER.", "Paper jam.")
            self.message_index = (self.message_index + 1) % len(messages)
            self.printer_message = messages[self.message_index]
            self.next_message += random.uniform(4.0, 6.0)

        if self.extraction >= 100.0:
            self._set_result(True)
        elif self.elapsed >= ROUND_SECONDS:
            self._set_result(False)

    def _shoulder_for(self, reading: PullReading, side: str) -> tuple[float, float]:
        return reading.left_shoulder if side == "left" else reading.right_shoulder

    def _hand_distance(self, reading: PullReading, hand: HandReading) -> float:
        shoulder = self._shoulder_for(reading, hand.side)
        return math.hypot(hand.wrist_x - shoulder[0], hand.wrist_y - shoulder[1]) / max(reading.shoulder_width, 0.055)

    def _update_gesture(self, reading: PullReading) -> None:
        hands = {hand.side: hand for hand in reading.hands}

        if self.pull_side is not None:
            hand = hands.get(self.pull_side)
            if hand is None:
                self.status = f"Keep your {self.pull_side} fist visible"
                return
            if hand.open_hand:
                self.pull_side = None
                self.status = f"Reach again with your {self.expected_side or hand.side} hand"
                return
            if not hand.fist:
                self.status = "Keep the grabbing hand closed"
                return

            current_distance = self._hand_distance(reading, hand)
            size_pull = hand.palm_size <= self.pull_size * PULL_SIZE_RATIO
            chest_pull = self.pull_distance - current_distance >= PULL_CHEST_GAIN
            if size_pull or chest_pull:
                self._complete_pull(hand.side)
            else:
                self.status = f"Pull your {hand.side} fist back to your chest"
            return

        valid_sides = {self.expected_side} if self.expected_side is not None else {"left", "right"}
        for side in valid_sides:
            hand = hands.get(side)
            if hand is None:
                continue
            distance = self._hand_distance(reading, hand)
            reach_ratio = hand.palm_size / max(reading.shoulder_width, 0.055)
            if hand.open_hand and (distance >= 0.58 or reach_ratio >= REACH_MINIMUM):
                self.armed_sides.add(side)
                self.status = f"Close your {side} hand to grab the paper"
            elif hand.fist and side in self.armed_sides:
                self.pull_side = side
                self.pull_size = hand.palm_size
                self.pull_distance = distance
                self.armed_sides.clear()
                self.status = f"Pull your {side} fist back to your chest"
                return

        if self.expected_side is not None and self.expected_side not in hands:
            self.status = f"Reach forward with your {self.expected_side} open hand"
        elif not reading.hands:
            self.status = "Relax, or reach forward with an open hand"

    def _complete_pull(self, side: str) -> None:
        self.extraction = min(100.0, self.extraction + PULL_PROGRESS)
        self.expected_side = "right" if side == "left" else "left"
        self.pull_side = None
        self.armed_sides.clear()
        self.pull_flash = 0.34
        self.idle_time = 0.0
        self.total_pulls += 1
        self.status = f"Good pull! Reach with your {self.expected_side} hand"

    def _set_result(self, won: bool) -> None:
        self.result = won
        self.result_time = 0.0
        self.pull_side = None
        self.printer_message = "Ready." if won else "Contact IT."
        self.status = "The paper is finally free." if won else "IT support is now offline."

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._draw_office(screen, width, height)
        self._draw_paper(screen, width, height)
        self._draw_printer(screen, width, height)
        self._draw_hud(screen, width, height)
        draw_camera_preview(screen, self.tracker)

        if self.mode == "calibrate":
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((20, 31, 40, 210))
            screen.blit(overlay, (0, 0))
            draw_text_centered(screen, self.title_font, "PRINTER SETUP", WHITE, (width // 2, height // 2 - 115))
            self.draw_calibration(screen)

        if self.result is not None:
            self._draw_result(screen, width, height)

    def _draw_office(self, screen: pygame.Surface, width: int, height: int) -> None:
        self._prepare_art(width, height)
        screen.blit(self.room_art, (0, 0))

        clock = pygame.Rect(0, 0, 116, 48)
        clock.midtop = (width // 2, 18)
        pygame.draw.rect(screen, (9, 28, 48), clock, border_radius=12)
        pygame.draw.rect(screen, (239, 190, 91), clock, 2, border_radius=12)
        time_text = self.clock_font.render("17:00" if self.result is True else "16:59", True, WHITE)
        screen.blit(time_text, time_text.get_rect(center=clock.center))

    def _prepare_art(self, width: int, height: int) -> None:
        if self.art_size == (width, height):
            return
        self.art_size = (width, height)
        self.room_art = pygame.transform.smoothscale(self.room_source, (width, height))
        printer_h = int(height * 0.34)
        printer_w = round(self.printer_source.get_width() * printer_h / self.printer_source.get_height())
        printer = pygame.transform.smoothscale(self.printer_source, (printer_w, printer_h))
        self.printer_art = pygame.transform.flip(printer, True, False)
        paper_h = max(92, int(height * 0.18))
        paper_w = int(width * 0.50)
        self.paper_art = pygame.transform.smoothscale(self.paper_source, (paper_w, paper_h))
        pile_h = max(68, int(height * 0.13))
        pile_w = int(width * 0.24)
        self.paper_pile_art = pygame.transform.smoothscale(self.paper_source, (pile_w, pile_h))

    def _printer_rect(self, width: int, height: int) -> pygame.Rect:
        rect = self.printer_art.get_rect()
        rect.bottomright = (int(width * 0.94), int(height * 0.72))
        return rect

    def _draw_printer(self, screen: pygame.Surface, width: int, height: int) -> None:
        shaking = self.pull_flash > 0 and self.result is None
        shake = int(math.sin(self.pull_flash * 90) * 5) if shaking else 0
        printer = self._printer_rect(width, height).move(shake, 0)
        shadow = pygame.Surface((printer.width + 24, 32), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (31, 25, 21, 70), shadow.get_rect())
        screen.blit(shadow, (printer.x - 4, printer.bottom - 15))
        screen.blit(self.printer_art, printer)

        display = pygame.Rect(
            printer.x + int(printer.width * 0.08),
            printer.y + int(printer.height * 0.36),
            int(printer.width * 0.16),
            max(24, int(printer.height * 0.105)),
        )
        pygame.draw.rect(screen, (12, 29, 42), display, border_radius=5)
        display_color = GREEN if self.result is True else (153, 211, 242)
        message = self.printer_font.render(self.printer_message, True, display_color)
        if message.get_width() > display.width - 6:
            message = pygame.transform.smoothscale(
                message, (display.width - 6, max(1, round(message.get_height() * (display.width - 6) / message.get_width())))
            )
        screen.blit(message, message.get_rect(center=display.center))
        light = GREEN if self.result is True else RED
        if self.result is not True and int(self.elapsed * 5) % 2:
            light = AMBER
        light_pos = (printer.x + int(printer.width * 0.055), printer.y + int(printer.height * 0.37))
        pygame.draw.circle(screen, (30, 36, 43), light_pos, 10)
        pygame.draw.circle(screen, light, light_pos, 7)

    def _draw_paper(self, screen: pygame.Surface, width: int, height: int) -> None:
        printer = self._printer_rect(width, height)
        slot_x = printer.x + int(printer.width * 0.34)
        slot_y = printer.y + int(printer.height * 0.70)
        progress = max(0.0, min(1.0, self.extraction / 100))
        twitch = int(math.sin(self.pull_flash * 100) * 5) if self.pull_flash > 0 else 0
        visible_width = max(82, int(self.paper_art.get_width() * (0.16 + progress * 0.84)))
        paper = pygame.transform.smoothscale(self.paper_art, (visible_width, self.paper_art.get_height()))
        paper = pygame.transform.rotate(paper, -2 + math.sin(self.pull_flash * 80) * 2 if self.pull_flash > 0 else -2)
        paper_rect = paper.get_rect(midright=(slot_x + 10, slot_y + twitch))
        screen.blit(paper, paper_rect)

        pile_layers = int(progress * 8)
        base_y = int(height * 0.68)
        for layer in range(pile_layers):
            sheet = pygame.transform.rotate(self.paper_pile_art, -7 + (layer % 4) * 5)
            x = int(width * 0.06) + int(math.sin(layer * 1.7) * 24)
            y = base_y + layer * 10
            screen.blit(sheet, sheet.get_rect(midleft=(x, y)))

    def _draw_hud(self, screen: pygame.Surface, width: int, height: int) -> None:
        title = self.title_font.render("ONE LAST PRINT", True, INK)
        screen.blit(title, (22, 18))
        objective = self.small_font.render("Clear the jam before home time.", True, INK)
        screen.blit(objective, (25, 76))

        remaining = max(0, math.ceil(ROUND_SECONDS - self.elapsed))
        timer = self.clock_font.render(f"00:{remaining:02d}", True, RED if remaining <= 8 else INK)
        screen.blit(timer, timer.get_rect(midtop=(int(width * 0.74), 22)))

        panel = pygame.Rect(20, 112, min(410, int(width * 0.48)), 70)
        pygame.draw.rect(screen, (29, 39, 47), panel, border_radius=12)
        screen.blit(self.small_font.render("EXTRACTION", True, WHITE), (panel.x + 16, panel.y + 12))
        draw_bar(screen, (panel.x + 16, panel.y + 35, panel.width - 32, 14), self.extraction / 100, BLUE, back=(67, 77, 84), radius=7)
        status = self.font.render(self.status, True, WHITE)
        status_box = status.get_rect(midbottom=(width // 2, height - 36)).inflate(24, 10)
        pygame.draw.rect(screen, (29, 39, 47), status_box, border_radius=8)
        screen.blit(status, status.get_rect(center=status_box.center))

        if self.tracker.available:
            info = "Open hand - fist - pull to chest - release and alternate; C recalibrates"
        else:
            detail = self.tracker.error or "camera unavailable"
            info = f"{detail} - camera tracking is required"
        draw_status_line(screen, self.small_font, info, INK)

    def _draw_result(self, screen: pygame.Surface, width: int, height: int) -> None:
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((8, 23, 39, 190))
        screen.blit(overlay, (0, 0))
        if self.result:
            heading = "PRINT JOB COMPLETE"
            line = "17:00. You are officially off the clock."
            color = GREEN
        else:
            heading = "CONTACT IT"
            line = "IT support is now offline."
            color = RED
        card = pygame.Rect(0, 0, min(680, width - 60), 245 if self.result else 170)
        card.center = (width // 2, height // 2)
        pygame.draw.rect(screen, (9, 34, 57), card, border_radius=22)
        pygame.draw.rect(screen, (76, 139, 181), card, 2, border_radius=22)
        draw_text_centered(screen, self.result_font, heading, color, (width // 2, card.top + 48))
        draw_text_centered(screen, self.font, line, WHITE, (width // 2, card.top + 96))
        if self.result:
            reveal = pygame.Rect(width // 2 - 230, card.top + 130, 460, 72)
            pygame.draw.rect(screen, PAPER, reveal, border_radius=7)
            pygame.draw.rect(screen, BLUE, reveal, width=3, border_radius=7)
            draw_text_centered(screen, self.font, "Have a nice evening.", INK, reveal.center)
