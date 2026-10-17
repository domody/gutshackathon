from __future__ import annotations

import random

import pygame

from game.minigame import Action, Minigame
from game.tracking import HandTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

TOTAL_FILES = 10
MAX_MISTAKES = 3
ROUND_SECONDS = 28.0
RESULT_SECONDS = 1.8
SWIPE_LIMIT = 0.27
RESET_LEFT = 0.36
RESET_RIGHT = 0.64

NAVY = (8, 37, 67)
BLUE = (30, 103, 164)
PALE = (211, 230, 241)
PAPER = (250, 248, 238)
INK = (29, 38, 48)
WOOD = (158, 105, 64)
WOOD_LIGHT = (193, 139, 87)
GREEN = (57, 164, 102)
RED = (207, 66, 62)
WHITE = (250, 250, 247)


class PaperSort(Minigame):
    title = "A Quick Favour"
    tracker_cls = HandTracker

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.title_font = pygame.font.Font(None, 58)
        self.file_font = pygame.font.Font(None, 42)
        self.label_font = pygame.font.Font(None, 29)
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Swipe Left", "Send contracts to the CONTRACTS pile"),
            Action("Swipe Right", "Send expenses to the EXPENSES pile"),
        )

    @property
    def negative_progress(self) -> float:
        return self.mistakes / MAX_MISTAKES

    def start(self) -> None:
        super().start()
        kinds = ["CONTRACT", "EXPENSE"] * (TOTAL_FILES // 2)
        random.shuffle(kinds)
        self.files = kinds
        self.index = 0
        self.mistakes = 0
        self.elapsed = 0.0
        self.result: bool | None = None
        self.result_t = 0.0
        self.armed = False
        self.last_x: float | None = None
        self.card_x = 0.5
        self.card_target = 0.5
        self.flash = 0.0
        self.transition_t = 0.0
        self.message = "Bring your hand to the middle"
        self.key_down = False

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.flash = max(0.0, self.flash - dt)
        self.card_x += (self.card_target - self.card_x) * min(1.0, dt * 13.0)

        if self.result is not None:
            self.result_t += dt
            if self.result_t >= RESULT_SECONDS:
                self.finish(self.result)
            return

        if self.transition_t > 0.0:
            self.transition_t = max(0.0, self.transition_t - dt)
            if self.transition_t == 0.0:
                self.index += 1
                if self.mistakes >= MAX_MISTAKES:
                    self._end(False, "These are all in the wrong folders")
                elif self.index >= len(self.files):
                    self._end(True, "Perfect. Exactly where I wanted them")
                else:
                    self.card_x = 0.5
                    self.card_target = 0.5
            return

        hand = self.tracker.hand if self.tracker.available else None
        if self.tracker.available and hand is None:
            self.message = "Show one hand to continue"
            self.last_x = None
            self.armed = False
            return

        self.elapsed += dt
        if self.elapsed >= ROUND_SECONDS:
            self._end(False, "The manager is still waiting")
            return

        if hand is not None:
            self._read_swipe(hand[0])
        else:
            keys = pygame.key.get_pressed()
            pressed = keys[pygame.K_a] or keys[pygame.K_LEFT] or keys[pygame.K_d] or keys[pygame.K_RIGHT]
            if pressed and not self.key_down:
                self._sort(-1 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 1)
            self.key_down = pressed

    def _read_swipe(self, x: float) -> None:
        if RESET_LEFT <= x <= RESET_RIGHT:
            self.armed = True
            self.message = "Swipe the file left or right"
        if self.armed and self.last_x is not None:
            if x <= SWIPE_LIMIT and x < self.last_x:
                self._sort(-1)
            elif x >= 1.0 - SWIPE_LIMIT and x > self.last_x:
                self._sort(1)
        self.last_x = x

    def _sort(self, direction: int) -> None:
        if self.result is not None or self.index >= len(self.files):
            return
        expected = -1 if self.files[self.index] == "CONTRACT" else 1
        self.card_target = -0.35 if direction < 0 else 1.35
        self.flash = 0.55
        self.transition_t = 0.38
        if direction == expected:
            self.message = "Filed correctly"
        else:
            self.mistakes += 1
            self.message = "Wrong pile"
        self.armed = False
        self.last_x = None

    def _end(self, won: bool, message: str) -> None:
        self.result = won
        self.result_t = 0.0
        self.message = message

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        screen.fill(NAVY)
        pygame.draw.rect(screen, WOOD, (0, int(height * 0.31), width, int(height * 0.69)))
        for y in range(int(height * 0.35), height, 60):
            pygame.draw.line(screen, WOOD_LIGHT, (0, y), (width, y + 12), 2)

        draw_text_centered(screen, self.title_font, "SORT THESE FOR ME", WHITE, (width // 2, 48))
        remaining = max(0, int(ROUND_SECONDS - self.elapsed + 0.999))
        draw_text_centered(screen, self.small_font, f"{remaining}s   •   {self.index}/{TOTAL_FILES} FILED", PALE,
                           (width // 2, 86))

        self._draw_pile(screen, int(width * 0.18), int(height * 0.72), "CONTRACTS", -1)
        self._draw_pile(screen, int(width * 0.82), int(height * 0.72), "EXPENSES", 1)

        if self.index < len(self.files) and self.result is None:
            self._draw_file(screen, int(self.card_x * width), int(height * 0.50), self.files[self.index])

        draw_bar(screen, (width // 2 - 145, 106, 290, 13), self.index / TOTAL_FILES, GREEN,
                 back=(54, 78, 99), radius=6)
        color = RED if self.message in ("Wrong pile", "These are all in the wrong folders") else WHITE
        draw_text_centered(screen, self.font, self.message, color, (width // 2, 151))
        draw_text_centered(screen, self.small_font, f"MISTAKES  {self.mistakes}/{MAX_MISTAKES}", WHITE,
                           (width // 2, height - 32))
        draw_camera_preview(screen, self.tracker)
        info = "Hand tracking on" if self.tracker.available else "No camera - A/left or D/right to test"
        draw_status_line(screen, self.small_font, info, WHITE)

        if self.result is not None:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((8, 28, 47, 190))
            screen.blit(overlay, (0, 0))
            heading = "FILES SORTED" if self.result else "FILING DISASTER"
            draw_text_centered(screen, self.title_font, heading, GREEN if self.result else RED,
                               (width // 2, height // 2 - 25))
            draw_text_centered(screen, self.font, self.message, WHITE, (width // 2, height // 2 + 28))

    def _draw_pile(self, screen: pygame.Surface, x: int, y: int, label: str, direction: int) -> None:
        for offset in range(4):
            paper = pygame.Rect(0, 0, 190, 116)
            paper.center = (x + direction * offset * 4, y - offset * 5)
            pygame.draw.rect(screen, PAPER, paper, border_radius=5)
            pygame.draw.rect(screen, INK, paper, 2, border_radius=5)
        text = self.label_font.render(label, True, INK)
        screen.blit(text, text.get_rect(center=(x, y - 10)))
        arrow = "< SWIPE LEFT" if direction < 0 else "SWIPE RIGHT >"
        draw_text_centered(screen, self.small_font, arrow, WHITE, (x, y + 88))

    def _draw_file(self, screen: pygame.Surface, x: int, y: int, kind: str) -> None:
        card = pygame.Rect(0, 0, 270, 190)
        card.center = (x, y)
        pygame.draw.rect(screen, (45, 31, 24), card.move(9, 10), border_radius=8)
        pygame.draw.rect(screen, PAPER, card, border_radius=8)
        pygame.draw.rect(screen, INK, card, 3, border_radius=8)
        screen.blit(self.small_font.render("JPMORGANCHASE", True, BLUE), (card.x + 20, card.y + 17))
        label = self.file_font.render(kind, True, INK)
        screen.blit(label, label.get_rect(center=(card.centerx, card.centery - 5)))
        for offset in range(3):
            pygame.draw.line(screen, (166, 171, 172), (card.x + 28, card.y + 130 + offset * 14),
                             (card.right - 28, card.y + 130 + offset * 14), 2)
