from __future__ import annotations

import math

import pygame

from game.minigame import Action, Minigame
from game.tracking import HandTracker
from game.ui import draw_bar, draw_camera_preview, draw_status_line


TOLERANCE = 0.035          # on-line distance, fraction of screen height
MAX_OFF_LINE = 0.12        # off-line crack length allowed, fraction of screen height
WIN_COVERAGE = 0.95        # fraction of the outline to crack
SAMPLE_SPACING = 6         # px between outline sample points
END_DELAY = 1.5            # seconds the result stays up

BG = (30, 24, 20)
COOKIE = (214, 163, 84)
COOKIE_EDGE = (170, 120, 52)
LINE = (120, 78, 30)
CRACK_OK = (90, 50, 20)
CRACK_BAD = (200, 50, 40)
CUT_DONE = (250, 232, 170)


class Dalgona(Minigame):
    """Pinch and trace the shape without cracking outside the line."""

    title = "Dalgona"
    tracker_cls = HandTracker

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Move Hand", "Your index finger is the pointer (or the mouse)", self.move_hand),
            Action("Pinch", "Pinch thumb and index to crack (or hold click / SPACE)", self.pinch),
        )

    # Input is polled in update(); these exist for the tutorial.
    def move_hand(self) -> None:
        pass

    def pinch(self) -> None:
        pass

    def start(self) -> None:
        super().start()
        self.end_timer = 0.0
        self.result: bool | None = None

        w, h = self.screen.get_size()
        self.center = (w / 2, h / 2)
        radius = h * 0.26
        self.cookie_radius = radius * 1.55
        self.tolerance = TOLERANCE * h
        self.max_off = MAX_OFF_LINE * h
        self.verts = [
            (self.center[0] + radius * math.cos(math.radians(a)),
             self.center[1] + radius * math.sin(math.radians(a)))
            for a in (-90, 30, 150)
        ]
        self.samples = self._sample_outline()
        self.covered = [False] * len(self.samples)

        self.pointer = self.center
        self.prev_pointer: tuple[float, float] | None = None
        self.pinching = False
        self.face_lost = False
        self.off_length = 0.0
        self.cracks: list[list[tuple[float, float, bool]]] = []
        self._keys_pinch = False

    def _sample_outline(self) -> list[tuple[float, float]]:
        pts = []
        for i in range(3):
            (x0, y0), (x1, y1) = self.verts[i], self.verts[(i + 1) % 3]
            n = max(1, int(math.dist((x0, y0), (x1, y1)) / SAMPLE_SPACING))
            pts += [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n)]
        return pts

    # Handle input
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._keys_pinch = True
        elif event.type == pygame.KEYUP and event.key == pygame.K_SPACE:
            self._keys_pinch = False

    def _read_input(self) -> tuple[tuple[float, float], bool]:
        w, h = self.screen.get_size()
        hand = self.tracker.hand if self.tracker.available else None
        if self.tracker.available:
            self.face_lost = hand is None
            if hand is None:
                return self.pointer, False
            return (hand[0] * w, hand[1] * h), hand[2]
        return pygame.mouse.get_pos(), self._keys_pinch or pygame.mouse.get_pressed()[0]

    # Update state
    def update(self, dt: float) -> None:
        if self.finished:
            return
        if self.result is not None:
            self.end_timer += dt
            if self.end_timer >= END_DELAY:
                self.finish(self.result)
            return

        pos, pinch = self._read_input()
        was_pinching = self.pinching
        self.pinching = pinch
        if not pinch:
            self.pointer, self.prev_pointer = pos, None
            return

        # Crack from the last pointer position (or here, if the pinch just began).
        start = self.prev_pointer if was_pinching and self.prev_pointer else pos
        if not was_pinching:
            self.cracks.append([])
        self._crack_along(start, pos)
        self.pointer, self.prev_pointer = pos, pos

        if self.off_length > self.max_off:
            self.result = False
        elif sum(self.covered) / len(self.covered) >= WIN_COVERAGE:
            self.result = True

    def _crack_along(self, a: tuple[float, float], b: tuple[float, float]) -> None:
        dist = math.dist(a, b)
        steps = max(1, int(dist / 6))
        step_len = dist / steps
        for i in range(1, steps + 1):
            t = i / steps
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            near = min(math.dist(p, s) for s in self.samples)
            on_line = near <= self.tolerance
            if on_line:
                for j, s in enumerate(self.samples):
                    if math.dist(p, s) <= self.tolerance:
                        self.covered[j] = True
            else:
                self.off_length += step_len
            self.cracks[-1].append((p[0], p[1], on_line))

    # Draw the scene
    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        screen.fill(BG)
        cx, cy = int(self.center[0]), int(self.center[1])
        pygame.draw.circle(screen, COOKIE_EDGE, (cx, cy), int(self.cookie_radius) + 6)
        pygame.draw.circle(screen, COOKIE, (cx, cy), int(self.cookie_radius))
        pygame.draw.polygon(screen, LINE, self.verts, 4)

        # cracked stretches of the outline
        for (x, y), done in zip(self.samples, self.covered):
            if done:
                pygame.draw.circle(screen, CUT_DONE, (int(x), int(y)), 4)
        for stroke in self.cracks:
            for (x0, y0, _), (x1, y1, ok) in zip(stroke, stroke[1:]):
                pygame.draw.line(screen, CRACK_OK if ok else CRACK_BAD, (x0, y0), (x1, y1), 3)

        color = (255, 90, 70) if self.pinching else (255, 255, 255)
        px, py = int(self.pointer[0]), int(self.pointer[1])
        pygame.draw.circle(screen, color, (px, py), 10 if self.pinching else 14, 3)

        self._draw_hud(screen, w, h)
        if self.result is not None:
            msg, col = ("COOKIE CLEARED!", (110, 230, 130)) if self.result else ("CRACKED!", (240, 80, 70))
            text = self.big_font.render(msg, True, col)
            screen.blit(text, (w // 2 - text.get_width() // 2, 60))

    def _draw_hud(self, screen: pygame.Surface, w: int, h: int) -> None:
        bx, bw, bh = 20, 220, 14
        for i, (label, frac, col) in enumerate((
            ("PROGRESS", sum(self.covered) / len(self.covered) / WIN_COVERAGE, (110, 220, 130)),
            ("CRACK DAMAGE", self.off_length / self.max_off, (230, 70, 60)),
        )):
            y = 20 + i * 44
            draw_bar(screen, (bx, y + 20, bw, bh), frac, col, back=(60, 52, 46))
            screen.blit(self.small_font.render(label, True, (210, 200, 190)), (bx, y))

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = "Hand tracking on - pinch to crack"
            if self.face_lost:
                info = "Hand lost!"
        else:
            info = "No camera - mouse to move, hold click or SPACE to pinch"
        draw_status_line(screen, self.small_font, info, (160, 150, 140))
