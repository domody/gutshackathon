from __future__ import annotations

import random

import pygame

from game.audio import sound_bank
from game.assets import get_font, key_pink, load_image
from game.minigame import Action, Minigame
from game.tracking import HandTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line, draw_text_centered

# Gameplay
TOTAL_FILES = 10
MAX_MISTAKES = 3
ROUND_SECONDS = 28.0
RESULT_SECONDS = 1.8

# Swipe
SWIPE_LIMIT = 0.27
RESET_LEFT = 0.36
RESET_RIGHT = 0.64

# Colors
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


def _load_documents() -> dict[str, pygame.Surface]:
    image = load_image("paper_sort_documents.png")
    key_pink(image)
    half = image.get_width() // 2
    expense_half = image.subsurface((0, 0, half, image.get_height())).copy()
    contract_half = image.subsurface((half, 0, image.get_width() - half, image.get_height())).copy()
    expense_bounds = expense_half.get_bounding_rect(min_alpha=8)
    contract_bounds = contract_half.get_bounding_rect(min_alpha=8)
    return {
        "EXPENSE": expense_half.subsurface(expense_bounds).copy(),
        "CONTRACT": contract_half.subsurface(contract_bounds).copy(),
    }


class PaperSort(Minigame):
    title = "A Quick Favour"
    objective = "Sort every document into the correct tray before your manager returns."
    success_title = "FILES SORTED"
    success_description = "Everything landed in the right tray."
    tracker_cls = HandTracker

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.tracker.full_hand = True

        self.title_font = get_font(58)
        self.file_font = get_font(42)
        self.label_font = get_font(29)
        self.desk_source = load_image("paper_sort_desk.png", alpha=False)
        self.document_sources = _load_documents()
        self._art_size: tuple[int, int] | None = None
        self.desk_art: pygame.Surface | None = None
        self.document_art: dict[str, pygame.Surface] = {}
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Swipe Left", "Send expenses to the blue EXPENSES tray"),
            Action("Swipe Right", "Send contracts to the red CONTRACTS tray"),
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
        self.card_y = 0.48
        self.card_target_y = 0.48
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
        self.card_y += (self.card_target_y - self.card_y) * min(1.0, dt * 11.0)

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
                    self.card_y = 0.48
                    self.card_target_y = 0.48
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
        expected = -1 if self.files[self.index] == "EXPENSE" else 1
        self.card_target = 0.20 if direction < 0 else 0.80
        self.card_target_y = 0.54
        self.flash = 0.55
        self.transition_t = 0.38
        if direction == expected:
            self.register_combo_success()
            sound_bank.play("paper")
            self.message = "Filed correctly"
        else:
            self.reset_combo()
            sound_bank.play("mistake")
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
        self._prepare_art(width, height)
        screen.blit(self.desk_art, (0, 0))
        top = pygame.Surface((width, 74), pygame.SRCALPHA)
        top.fill((7, 32, 58, 222))
        screen.blit(top, (0, 0))
        title = self.font.render("A QUICK FAVOUR", True, WHITE)
        screen.blit(title, (18, 13))
        remaining = max(0, int(ROUND_SECONDS - self.elapsed + 0.999))
        timer = self.font.render(f"{remaining}s", True, WHITE)
        screen.blit(timer, timer.get_rect(topright=(width - 18, 13)))
        draw_text_centered(screen, self.small_font, f"{self.index}/{TOTAL_FILES} FILED", PALE,
                           (width // 2, 22))
        draw_bar(screen, (width // 2 - 145, 46, 290, 11), self.index / TOTAL_FILES, GREEN,
                 back=(54, 78, 99), radius=5)

        if self.index < len(self.files) and self.result is None:
            progress = 0.0 if self.transition_t <= 0.0 else 1.0 - self.transition_t / 0.38
            self._draw_file(screen, int(self.card_x * width), int(self.card_y * height),
                            self.files[self.index], 1.0 - progress * 0.42)

        color = RED if self.message in ("Wrong pile", "These are all in the wrong folders") else WHITE
        message = self.font.render(self.message, True, color)
        message_box = message.get_rect(midbottom=(width // 2, height - 42)).inflate(24, 10)
        pygame.draw.rect(screen, (7, 32, 58), message_box, border_radius=9)
        screen.blit(message, message.get_rect(center=message_box.center))
        mistakes = self.small_font.render(f"MISTAKES {self.mistakes}/{MAX_MISTAKES}", True, WHITE)
        screen.blit(mistakes, mistakes.get_rect(bottomright=(width - 14, height - 12)))
        left_count = sum(kind == "EXPENSE" for kind in self.files[:self.index])
        right_count = sum(kind == "CONTRACT" for kind in self.files[:self.index])
        self._draw_count(screen, int(width * 0.20), int(height * 0.39), left_count)
        self._draw_count(screen, int(width * 0.80), int(height * 0.39), right_count)
        draw_camera_preview(screen, self.tracker)
        info = "Hand tracking on" if self.tracker.available else "No camera"
        draw_status_line(screen, self.small_font, info, WHITE)

        if self.result is False:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((8, 28, 47, 190))
            screen.blit(overlay, (0, 0))
            heading = "FILING DISASTER"
            draw_text_centered(screen, self.title_font, heading, RED,
                               (width // 2, height // 2 - 25))
            draw_text_centered(screen, self.font, self.message, WHITE, (width // 2, height // 2 + 28))

    def _prepare_art(self, width: int, height: int) -> None:
        if self._art_size == (width, height):
            return
        self._art_size = (width, height)
        self.desk_art = pygame.transform.smoothscale(self.desk_source, (width, height))
        target_h = int(height * 0.39)
        self.document_art = {}
        for kind, source in self.document_sources.items():
            target_w = round(source.get_width() * target_h / source.get_height())
            self.document_art[kind] = pygame.transform.smoothscale(source, (target_w, target_h))

    def _draw_count(self, screen: pygame.Surface, x: int, y: int, count: int) -> None:
        text = self.font.render(str(count), True, WHITE)
        box = text.get_rect(center=(x, y)).inflate(22, 12)
        pygame.draw.rect(screen, (7, 32, 58), box, border_radius=12)
        screen.blit(text, text.get_rect(center=box.center))

    def _draw_file(self, screen: pygame.Surface, x: int, y: int, kind: str, scale: float) -> None:
        source = self.document_art[kind]
        if scale < 0.99:
            source = pygame.transform.smoothscale(
                source, (max(1, round(source.get_width() * scale)), max(1, round(source.get_height() * scale))))
        shadow = pygame.Surface(source.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (28, 20, 14, 90), shadow.get_rect(), border_radius=8)
        screen.blit(shadow, shadow.get_rect(center=(x + 8, y + 10)))
        screen.blit(source, source.get_rect(center=(x, y)))
