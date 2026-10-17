from pathlib import Path
from typing import Callable

import pygame

from game.ui.screen import BLANK, Screen
from game.ui.typewriter import Typewriter

SCENES_DIR = Path(__file__).resolve().parents[3] / "assets" / "scenes"


class SceneScreen(Screen):
    """Full-screen image with a dialogue box; the speaker talks, or a narrator if none."""

    NAME_SIZE = 52
    TEXT_SIZE = 46
    HINT_SIZE = 30
    NAME_COLOR = (255, 215, 90)
    TEXT_COLOR = (240, 240, 240)
    HINT_COLOR = (170, 170, 185)
    BOX_COLOR = (10, 10, 18, 205)
    MARGIN = 60
    PAD = 28

    fade_in = 0.5
    fade_out = 0.5
    background = BLANK

    def __init__(self, image: str, text: str, speaker: str | None,
                 on_continue: Callable[[], None]) -> None:
        self.text = text
        self.speaker = speaker
        self.on_continue = on_continue
        path = next((candidate for candidate in (SCENES_DIR / f"{image}.png", SCENES_DIR / f"{image}.jpg")
                     if candidate.exists()), SCENES_DIR / f"{image}.png")
        self._image = pygame.image.load(path).convert()
        self._scaled: pygame.Surface | None = None
        self._name_font = pygame.font.Font(None, self.NAME_SIZE)
        self._text_font = pygame.font.Font(None, self.TEXT_SIZE)
        self._text_font.set_italic(speaker is None)
        self._hint_font = pygame.font.Font(None, self.HINT_SIZE)
        self._writer = Typewriter(45)

    def update(self, dt: float) -> None:
        self._writer.update(dt)

    def handle_event(self, event: pygame.event.Event) -> None:
        is_click = event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
        if not is_click:
            return
        if self._writer.done:
            self.on_continue()
        else:
            self._writer.finish()

    def gesture_continue(self) -> None:
        if self._writer.done:
            self.on_continue()
        else:
            self._writer.finish()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        surface.blit(self._cover(surface.get_size()), (0, 0))

        lines = self._wrap(self.text, width - 2 * (self.MARGIN + self.PAD))
        line_h = self._text_font.get_linesize()
        name_h = self._name_font.get_linesize() + 8 if self.speaker else 0
        box = pygame.Rect(0, 0, width - 2 * self.MARGIN, name_h + line_h * len(lines) + 2 * self.PAD)
        box.midbottom = (width // 2, height - 70)
        panel = pygame.Surface(box.size, pygame.SRCALPHA)
        pygame.draw.rect(panel, self.BOX_COLOR, panel.get_rect(), border_radius=16)
        surface.blit(panel, box)

        w = self._writer
        w.begin()
        x, y = box.left + self.PAD, box.top + self.PAD
        if self.speaker:
            w.draw(surface, self._name_font, self.speaker, self.NAME_COLOR, topleft=(x, y))
            y += name_h
        for line in lines:
            w.draw(surface, self._text_font, line, self.TEXT_COLOR, topleft=(x, y))
            y += line_h
        w.end()
        if w.done:
            hint = self._hint_font.render("Pinch your fingers together to continue", True, self.HINT_COLOR)
            surface.blit(hint, hint.get_rect(midbottom=(width // 2, height - 20)))

    def _cover(self, size: tuple[int, int]) -> pygame.Surface:
        """The image scaled to fill `size`, cropped to the centre."""
        if self._scaled is None or self._scaled.get_size() != size:
            iw, ih = self._image.get_size()
            scale = max(size[0] / iw, size[1] / ih)
            big = pygame.transform.smoothscale(
                self._image, (max(size[0], round(iw * scale)), max(size[1], round(ih * scale))))
            crop = pygame.Rect(0, 0, *size)
            crop.center = big.get_rect().center
            self._scaled = big.subsurface(crop).copy()
        return self._scaled

    def _wrap(self, text: str, max_width: int) -> list[str]:
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if line and self._text_font.size(trial)[0] > max_width:
                lines.append(line)
                line = word
            else:
                line = trial
        return lines + [line] if line else lines
