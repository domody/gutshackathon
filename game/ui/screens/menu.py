from collections.abc import Sequence

import pygame

from game.ui.screen import Screen
from game.ui.screens.item import MenuItem


class Menu(Screen):
    """Vertical menu: handles input, selection, and rendering."""

    TITLE_SIZE = 96
    ITEM_SIZE = 56
    SPACING = 20
    TITLE_COLOR = (255, 215, 90)
    ITEM_COLOR = (170, 170, 185)
    SELECTED_COLOR = (255, 255, 255)

    def __init__(self, title: str, items: Sequence[MenuItem]) -> None:
        if not items:
            raise ValueError("Menu needs at least one item")
        self.title = title
        self.items = list(items)
        self.selected = 0
        self._title_font = pygame.font.Font(None, self.TITLE_SIZE)
        self._item_font = pygame.font.Font(None, self.ITEM_SIZE)
        self._item_rects: list[pygame.Rect] = []

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self._move(-1)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._move(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._activate()
        elif event.type == pygame.MOUSEMOTION:
            if (index := self._index_at(event.pos)) is not None:
                self.selected = index
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if (index := self._index_at(event.pos)) is not None:
                self.selected = index
                self._activate()

    def draw(self, surface: pygame.Surface) -> None:
        center_x = surface.get_width() // 2
        title = self._title_font.render(self.title, True, self.TITLE_COLOR)
        title_rect = title.get_rect(midtop=(center_x, surface.get_height() // 6))
        surface.blit(title, title_rect)

        y = title_rect.bottom + self.SPACING * 3
        self._item_rects = []
        for i, item in enumerate(self.items):
            color = self.SELECTED_COLOR if i == self.selected else self.ITEM_COLOR
            text = self._item_font.render(item.label, True, color)
            rect = text.get_rect(midtop=(center_x, y))
            surface.blit(text, rect)
            self._item_rects.append(rect)
            y = rect.bottom + self.SPACING

    def _move(self, step: int) -> None:
        self.selected = (self.selected + step) % len(self.items)

    def _activate(self) -> None:
        self.items[self.selected].action()

    def _index_at(self, pos: tuple[int, int]) -> int | None:
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(pos):
                return i
        return None
