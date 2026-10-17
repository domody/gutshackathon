from __future__ import annotations

import math

import pygame

from game.minigame import Action, Minigame
from game.tracking import HandTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

TOLERANCE = 0.034
MAX_OFF_LINE = 0.085
WIN_COVERAGE = 0.92
SAMPLE_SPACING = 6
SLIDE_SECONDS = 0.72
PAGE_PAUSE = 1.15
RETRY_PAUSE = 1.25
END_DELAY = 2.2

DESK = (75, 55, 43)
DESK_GRAIN = (98, 72, 55)
PAPER = (247, 244, 232)
PAPER_SHADOW = (39, 30, 25)
INK = (30, 39, 49)
MUTED = (105, 108, 107)
BLUE = (30, 103, 164)
GUIDE = (137, 168, 192)
SIGNED = (25, 74, 124)
BAD = (205, 62, 62)
GREEN = (67, 161, 103)
AMBER = (226, 157, 47)
WHITE = (250, 250, 247)


class Dalgona(Minigame):
    title = "Contract Signing Day"
    tracker_cls = HandTracker

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.heading_font = pygame.font.Font(None, 58)
        self.document_font = pygame.font.Font(None, 32)
        self.name_font = pygame.font.Font(None, 40)
        self.body_font = pygame.font.Font(None, 25)
        self.meter_font = pygame.font.Font(None, 18)
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Move Pen", "Move your index finger along the signature guide"),
            Action("Sign", "Pinch thumb and index to put pen to paper"),
        )

    @property
    def negative_progress(self) -> float:
        return self.max_off_length / (MAX_OFF_LINE * self.screen.get_height())

    def start(self) -> None:
        super().start()
        width, height = self.screen.get_size()
        self.name = "WM"
        self.state = "name"
        self.page_index = 0
        self.page_y = -height
        self.slide_time = 0.0
        self.pause_timer = 0.0
        self.end_timer = 0.0
        self.result: bool | None = None
        self.paper_rect = self._paper_rect(width, height)
        self.pointer = (width / 2, height / 2)
        self.prev_pointer: tuple[float, float] | None = None
        self.pinching = False
        self.hand_lost = False
        self.off_length = 0.0
        self.max_off_length = 0.0
        self.samples: list[tuple[float, float]] = []
        self.covered: list[bool] = []
        self.strokes: list[list[tuple[float, float, bool]]] = []
        self.retry_count = 0
        self.retry_stage = "name"
        self.status = "Pinch and trace WM"
        self._reset_name_trace()

    def _paper_rect(self, width: int, height: int) -> pygame.Rect:
        paper_width = min(700, int(width * 0.72))
        paper_top = max(138, int(height * 0.1))
        paper_height = min(540, height - paper_top - 38)
        return pygame.Rect(width // 2 - paper_width // 2, paper_top, paper_width, paper_height)

    def _begin_page(self, index: int) -> None:
        self.page_index = index
        self.state = "sliding"
        self.slide_time = 0.0
        self.page_y = -self.paper_rect.height - 30
        self._reset_signature()
        self.status = "Document incoming..."

    def _reset_signature(self) -> None:
        self.samples = self._build_signature(self.page_index)
        self.covered = [False] * len(self.samples)
        self.off_length = 0.0
        self.strokes = []
        self.prev_pointer = None
        self.pinching = False

    def _build_signature(self, page_index: int) -> list[tuple[float, float]]:
        rect = self.paper_rect
        left = rect.x + int(rect.width * 0.19)
        right = rect.right - int(rect.width * 0.14)
        center_y = rect.y + int(rect.height * 0.81)
        width = right - left
        points: list[tuple[float, float]] = []
        count = max(80, int(width / SAMPLE_SPACING) * 2)
        for index in range(count):
            t = index / (count - 1)
            x = left + width * t
            if page_index == 0:
                wave = math.sin(t * math.pi * 7.5) * (1 - t * 0.5)
                flourish = math.sin(t * math.pi * 2) * 0.35
                y = center_y + (wave + flourish) * rect.height * 0.055
            else:
                wave = math.sin(t * math.pi * 5.5)
                underline = math.sin(t * math.pi) * 0.28
                y = center_y + (wave - underline) * rect.height * 0.05
            points.append((x, y))
        return points

    def _read_input(self) -> tuple[tuple[float, float], bool]:
        width, height = self.screen.get_size()
        hand = self.tracker.hand if self.tracker.available else None
        if self.tracker.available:
            self.hand_lost = hand is None
            if hand is None:
                return self.pointer, False
            return (hand[0] * width, hand[1] * height), hand[2]
        self.hand_lost = True
        return pygame.mouse.get_pos(), pygame.mouse.get_pressed()[0]

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)

        if self.result is not None:
            self.end_timer += dt
            if self.end_timer >= END_DELAY:
                self.finish(self.result)
            return

        if self.state == "name":
            position, pinch = self._read_input()
            self._trace_input(position, pinch)
            if self.off_length > MAX_OFF_LINE * self.screen.get_height():
                self.retry_stage = "name"
                self.state = "retry"
                self.pause_timer = 0.0
                self.retry_count += 1
                self.pinching = False
                self.status = "Outside the letters - try WM again"
            elif self.coverage >= WIN_COVERAGE:
                self.state = "name_complete"
                self.pause_timer = 0.0
                self.pinching = False
                self.status = "Name added"
            return
        if self.state == "sliding":
            self.slide_time = min(SLIDE_SECONDS, self.slide_time + dt)
            amount = 1 - (1 - self.slide_time / SLIDE_SECONDS) ** 3
            self.page_y = -self.paper_rect.height + (self.paper_rect.y + self.paper_rect.height) * amount
            if self.slide_time >= SLIDE_SECONDS:
                self.page_y = self.paper_rect.y
                self.state = "signing"
                self.status = "Pinch and trace inside the signature guide"
            return
        if self.state in ("name_complete", "page_complete", "retry"):
            self.pause_timer += dt
            pause = PAGE_PAUSE if self.state in ("name_complete", "page_complete") else RETRY_PAUSE
            if self.pause_timer < pause:
                return
            if self.state == "retry":
                if self.retry_stage == "name":
                    self.state = "name"
                    self._reset_name_trace()
                    self.status = "Try again - trace WM inside the guide"
                else:
                    self.state = "signing"
                    self._reset_signature()
                    self.status = "Try again - keep the pen inside the guide"
            elif self.state == "name_complete":
                self._begin_page(0)
            else:
                self.result = True
                self.end_timer = 0.0
            return

        position, pinch = self._read_input()
        self._trace_input(position, pinch)

        if self.off_length > MAX_OFF_LINE * self.screen.get_height():
            self.retry_stage = "signing"
            self.state = "retry"
            self.pause_timer = 0.0
            self.retry_count += 1
            self.pinching = False
            self.status = "Outside the lines - this copy is void"
        elif self.coverage >= WIN_COVERAGE:
            self.state = "page_complete"
            self.pause_timer = 0.0
            self.pinching = False
            self.status = "Signed and witnessed"

    def _trace_input(self, position: tuple[float, float], pinch: bool) -> None:
        was_pinching = self.pinching
        self.pinching = pinch
        if not pinch:
            self.pointer = position
            self.prev_pointer = None
            return

        start = self.prev_pointer if was_pinching and self.prev_pointer else position
        if not was_pinching:
            self.strokes.append([])
        self._sign_along(start, position)
        self.pointer = position
        self.prev_pointer = position

    @property
    def coverage(self) -> float:
        return sum(self.covered) / max(1, len(self.covered))

    def _reset_name_trace(self) -> None:
        width, height = self.screen.get_size()
        center_x = width // 2
        top = int(height * 0.39)
        bottom = int(height * 0.66)
        middle = (top + bottom) // 2
        w_left = center_x - 190
        m_left = center_x + 15
        polylines = (
            ((w_left, top), (w_left + 42, bottom), (w_left + 84, middle), (w_left + 126, bottom), (w_left + 168, top)),
            ((m_left, bottom), (m_left, top), (m_left + 70, middle), (m_left + 140, top), (m_left + 140, bottom)),
        )
        self.samples = []
        for polyline in polylines:
            for start, end in zip(polyline, polyline[1:]):
                count = max(2, int(math.dist(start, end) / SAMPLE_SPACING))
                self.samples.extend(
                    (start[0] + (end[0] - start[0]) * amount / count,
                     start[1] + (end[1] - start[1]) * amount / count)
                    for amount in range(count)
                )
        self.covered = [False] * len(self.samples)
        self.off_length = 0.0
        self.strokes = []
        self.prev_pointer = None
        self.pinching = False

    def _sign_along(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        distance = math.dist(start, end)
        steps = max(1, int(distance / SAMPLE_SPACING))
        step_length = distance / steps
        tolerance = TOLERANCE * self.screen.get_height()
        for index in range(1, steps + 1):
            amount = index / steps
            point = (start[0] + (end[0] - start[0]) * amount, start[1] + (end[1] - start[1]) * amount)
            near = min(math.dist(point, sample) for sample in self.samples)
            on_line = near <= tolerance
            if on_line:
                for sample_index, sample in enumerate(self.samples):
                    if math.dist(point, sample) <= tolerance:
                        self.covered[sample_index] = True
            else:
                self.off_length += step_length
                self.max_off_length = max(self.max_off_length, self.off_length)
            self.strokes[-1].append((point[0], point[1], on_line))

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._draw_desk(screen, width, height)
        if self.state in ("name", "name_complete") or (self.state == "retry" and self.retry_stage == "name"):
            self._draw_name_entry(screen, width, height)
            self._draw_pointer(screen)
        else:
            self._draw_document(screen, width, height)
            self._draw_pointer(screen)
            self._draw_hud(screen, width, height)
        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = "Hand tracking on - pinch to put pen to paper"
            if self.hand_lost:
                info = "Hand lost - signing paused"
        else:
            info = "No camera - mouse to move, hold click or SPACE to sign"
        draw_status_line(screen, self.small_font, info, WHITE)

        if self.result is not None:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((15, 24, 31, 225))
            screen.blit(overlay, (0, 0))
            draw_text_centered(screen, self.heading_font, "PAPERWORK COMPLETE", GREEN, (width // 2, height // 2 - 40))
            draw_text_centered(screen, self.font, "Welcome aboard. Legal will be in touch.", WHITE, (width // 2, height // 2 + 25))

    def _draw_desk(self, screen: pygame.Surface, width: int, height: int) -> None:
        screen.fill(DESK)
        for y in range(20, height, 54):
            pygame.draw.line(screen, DESK_GRAIN, (0, y), (width, y + 14), 2)
        pygame.draw.rect(screen, (25, 31, 37), (20, 14, 255, 54), border_radius=10)
        title = self.document_font.render("CONTRACT SIGNING DAY", True, WHITE)
        screen.blit(title, title.get_rect(center=(147, 41)))

    def _draw_name_entry(self, screen: pygame.Surface, width: int, height: int) -> None:
        card = pygame.Rect(width // 2 - min(350, width // 2 - 30), 82, min(700, width - 60), height - 120)
        pygame.draw.rect(screen, PAPER_SHADOW, card.move(10, 12), border_radius=14)
        pygame.draw.rect(screen, PAPER, card, border_radius=14)
        draw_text_centered(screen, self.heading_font, "Add Your Name", INK, (width // 2, card.y + 58))
        draw_text_centered(screen, self.font, "Pinch and trace the outlined WM", MUTED, (width // 2, card.y + 101))
        for sample, done in zip(self.samples, self.covered):
            pygame.draw.circle(screen, SIGNED if done else GUIDE, (int(sample[0]), int(sample[1])), 4 if done else 3)
        for stroke in self.strokes:
            for first, second in zip(stroke, stroke[1:]):
                pygame.draw.line(screen, SIGNED if second[2] else BAD, (first[0], first[1]), (second[0], second[1]), 4)
        line_y = int(height * 0.7)
        pygame.draw.line(screen, MUTED, (card.x + 95, line_y), (card.right - 95, line_y), 2)
        draw_text_centered(screen, self.small_font, "Lift your fingers between W and M", BLUE, (width // 2, line_y + 30))
        draw_bar(screen, (card.x + 120, card.bottom - 35, card.width - 240, 10), self.coverage / WIN_COVERAGE, GREEN, back=(210, 210, 201), radius=5)
        footer = self.small_font.render("Page 1 of 2", True, MUTED)
        screen.blit(footer, footer.get_rect(midbottom=(card.centerx, card.bottom - 8)))
        if self.state == "name_complete":
            draw_text_centered(screen, self.font, "NAME ADDED", GREEN, (width // 2, card.bottom - 64))
        elif self.state == "retry":
            draw_text_centered(screen, self.font, "OUTSIDE THE LETTERS", BAD, (width // 2, card.bottom - 64))

    def _draw_document(self, screen: pygame.Surface, width: int, height: int) -> None:
        rect = self.paper_rect.copy()
        rect.y = int(self.page_y)
        offset = rect.y - self.paper_rect.y
        pygame.draw.rect(screen, PAPER_SHADOW, rect.move(10, 12), border_radius=5)
        pygame.draw.rect(screen, PAPER, rect, border_radius=5)
        pygame.draw.rect(screen, (221, 216, 201), rect, width=2, border_radius=5)

        page_title = "INTERNSHIP AGREEMENT + NDA"
        title = self.heading_font.render(page_title, True, INK)
        if title.get_width() > rect.width - 50:
            title = self.document_font.render(page_title, True, INK)
        screen.blit(title, title.get_rect(midtop=(rect.centerx, rect.y + 28)))
        pygame.draw.line(screen, BLUE, (rect.x + 45, rect.y + 90), (rect.right - 45, rect.y + 90), 3)

        name_label = self.small_font.render("EMPLOYEE NAME", True, MUTED)
        screen.blit(name_label, (rect.x + 48, rect.y + 112))
        name = self.name_font.render(self.name, True, INK)
        screen.blit(name, (rect.x + 48, rect.y + 134))
        pygame.draw.line(screen, INK, (rect.x + 45, rect.y + 176), (rect.right - 45, rect.y + 176), 2)

        lines = (
            "INTERNSHIP: I agree to attend meetings, answer emails,",
            "and pretend to understand the shared drive",
            "naming convention.",
            "NDA: I agree not to disclose confidential information,",
            "including who keeps stealing lunch from the fridge.",
        )
        for index, line in enumerate(lines):
            body = self.body_font.render(line, True, INK)
            screen.blit(body, (rect.x + 48, rect.y + 190 + index * 22))

        signature_y = rect.y + int(rect.height * 0.70)
        label = self.small_font.render("AUTHORIZED SIGNATURE - TRACE THE GUIDE", True, BLUE)
        screen.blit(label, (rect.x + 48, signature_y))
        pygame.draw.line(screen, MUTED, (rect.x + 48, rect.y + int(rect.height * 0.89)), (rect.right - 48, rect.y + int(rect.height * 0.89)), 2)

        if abs(offset) < 1:
            for sample, done in zip(self.samples, self.covered):
                color = SIGNED if done else GUIDE
                radius = 4 if done else 3
                pygame.draw.circle(screen, color, (int(sample[0]), int(sample[1])), radius)
            for stroke in self.strokes:
                for first, second in zip(stroke, stroke[1:]):
                    color = SIGNED if second[2] else BAD
                    pygame.draw.line(screen, color, (first[0], first[1]), (second[0], second[1]), 4)

        footer = self.small_font.render("Page 2 of 2", True, MUTED)
        screen.blit(footer, footer.get_rect(midbottom=(rect.centerx, rect.bottom - 18)))

        if self.state == "page_complete":
            stamp = self.heading_font.render("SIGNED", True, GREEN)
            stamp_rect = stamp.get_rect(center=(rect.right - 120, rect.y + 118)).inflate(20, 10)
            pygame.draw.rect(screen, GREEN, stamp_rect, width=5, border_radius=5)
            screen.blit(stamp, stamp.get_rect(center=stamp_rect.center))
        elif self.state == "retry":
            stamp = self.heading_font.render("VOID", True, BAD)
            stamp_rect = stamp.get_rect(center=(rect.right - 105, rect.y + 118)).inflate(20, 10)
            pygame.draw.rect(screen, BAD, stamp_rect, width=5, border_radius=5)
            screen.blit(stamp, stamp.get_rect(center=stamp_rect.center))

    def _draw_pointer(self, screen: pygame.Surface) -> None:
        if self.state not in ("name", "signing"):
            return
        color = BAD if self.pinching else BLUE
        x, y = int(self.pointer[0]), int(self.pointer[1])
        pygame.draw.circle(screen, WHITE, (x, y), 13)
        pygame.draw.circle(screen, color, (x, y), 13, 3)
        pygame.draw.line(screen, color, (x + 9, y - 9), (x + 25, y - 25), 5)

    def _draw_hud(self, screen: pygame.Surface, width: int, height: int) -> None:
        if self.state == "sliding":
            return
        panel = pygame.Rect(10, self.paper_rect.y + 18, max(94, self.paper_rect.x - 20), 112)
        pygame.draw.rect(screen, (25, 31, 37), panel, border_radius=10)
        progress = self.coverage / WIN_COVERAGE
        damage = self.off_length / (MAX_OFF_LINE * height)
        screen.blit(self.meter_font.render("TRACE", True, WHITE), (panel.x + 9, panel.y + 10))
        draw_bar(screen, (panel.x + 9, panel.y + 31, panel.width - 18, 10), progress, GREEN, back=(66, 72, 77), radius=5)
        screen.blit(self.meter_font.render("ERROR", True, WHITE), (panel.x + 9, panel.y + 56))
        draw_bar(screen, (panel.x + 9, panel.y + 77, panel.width - 18, 10), damage, BAD, back=(66, 72, 77), radius=5)
        status = self.small_font.render(self.status, True, WHITE)
        status_box = status.get_rect(midtop=(width // 2, 82)).inflate(24, 10)
        pygame.draw.rect(screen, (25, 31, 37), status_box, border_radius=8)
        screen.blit(status, status.get_rect(center=status_box.center))
