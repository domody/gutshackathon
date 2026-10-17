from collections.abc import Sequence
from pathlib import Path

import pygame

from game.ui.screen import Screen
from game.ui.screens.item import MenuItem


class Menu(Screen):
    """Opening title screen."""

    TITLE_SIZE = 48
    ITEM_SIZE = 42
    SPACING = 20
    TITLE_COLOR = (250, 250, 247)
    ITEM_COLOR = (225, 237, 246)
    SELECTED_COLOR = (255, 255, 255)

    def __init__(self, title: str, items: Sequence[MenuItem]) -> None:
        if not items:
            raise ValueError("Menu needs at least one item")
        self.title = title
        self.items = list(items)
        self.selected = 0
        self._title_font = pygame.font.Font(None, self.TITLE_SIZE)
        self._item_font = pygame.font.Font(None, self.ITEM_SIZE)
        self._subtitle_font = pygame.font.Font(None, 26)
        self._item_rects: list[pygame.Rect] = []
        path = Path(__file__).resolve().parents[3] / "assets" / "menu" / "jpmorgan_building.png"
        self._background = pygame.image.load(path).convert()
        self._scaled: pygame.Surface | None = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            if (index := self._index_at(event.pos)) is not None:
                self.selected = index
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if (index := self._index_at(event.pos)) is not None:
                self.selected = index
                self._activate()

    def gesture_continue(self) -> None:
        self._activate()

    def draw(self, surface: pygame.Surface) -> None:
        surface.blit(self._cover(surface.get_size()), (0, 0))
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((28, 42, 55, 64))
        surface.blit(shade, (0, 0))

        panel = pygame.Surface((390, 204), pygame.SRCALPHA)
        pygame.draw.rect(panel, (8, 29, 48, 195), panel.get_rect(), border_radius=18)
        surface.blit(panel, (38, 38))

        x = 62
        y = 54
        for line in ("MY FIRST DAY AT", "JPMORGANCHASE"):
            text = self._title_font.render(line, True, self.TITLE_COLOR)
            surface.blit(text, (x, y))
            y += text.get_height() - 3
        subtitle = self._subtitle_font.render("AN INTERN'S SURVIVAL STORY", True, (172, 211, 235))
        surface.blit(subtitle, (x + 2, y + 5))
        y += subtitle.get_height() + 20

        self._item_rects = []
        for i, item in enumerate(self.items):
            color = self.SELECTED_COLOR if i == self.selected else self.ITEM_COLOR
            label = "PINCH TO START" if i == 0 else item.label.upper()
            text = self._item_font.render(label, True, color)
            rect = text.get_rect(topleft=(x + 2, y))
            surface.blit(text, rect)
            self._item_rects.append(rect)
            y = rect.bottom + self.SPACING

    def _cover(self, size: tuple[int, int]) -> pygame.Surface:
        if self._scaled is None or self._scaled.get_size() != size:
            iw, ih = self._background.get_size()
            scale = max(size[0] / iw, size[1] / ih)
            big = pygame.transform.smoothscale(
                self._background, (max(size[0], round(iw * scale)), max(size[1], round(ih * scale))))
            crop = pygame.Rect(0, 0, *size)
            crop.center = big.get_rect().center
            self._scaled = big.subsurface(crop).copy()
        return self._scaled

    def _activate(self) -> None:
        self.items[self.selected].action()

    def _index_at(self, pos: tuple[int, int]) -> int | None:
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(pos):
                return i
        return None
