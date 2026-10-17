from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

from game.minigame import Action, Minigame
from game.tracking import HandTracker
from game.ui import draw_camera_preview, draw_status_line, draw_text_centered

TARGET_OBJECTS = 10
LIVES = 3
FALL_TIME = (1.65, 1.1)        # seconds from spawn to your hand, start -> end of round
SPAWN_INTERVAL = (1.5, 0.9)    # seconds between objects, start -> end of round
BAD_CHANCE = 0.4               # after the first two objects; never more than 2 in a row
PALM_HOLD = 0.05               # palm must be shown this long inside the zone to catch
FIST_HOLD = 0.05               # fist must be shown this long inside the zone to drop a bad item
READY_SECONDS = 3.5
FLASH_SECONDS = 0.7
OBJ_R = 34

GOOD_KINDS = ("contract", "document", "program")
BAD_KINDS = ("p45", "fired")
KIND_COLORS = {
    "contract": (245, 235, 200), "document": (170, 210, 255), "program": (90, 220, 140),
    "p45": (240, 210, 90), "fired": (235, 70, 70),
}
GOOD_FLASH = {"contract": "SIGNED OFF!", "document": "FILED!", "program": "DEPLOYED!"}

BG = (16, 18, 32)
FLOOR = (30, 32, 50)
GOOD_COLOR = (110, 210, 130)
BAD_COLOR = (235, 70, 70)
PALM_COLOR = (125, 195, 255)
FIST_COLOR = (255, 170, 90)
DARK = (25, 25, 35)
PAPER = (248, 246, 238)
INK = (90, 95, 120)


@dataclass
class Item:
    kind: str
    good: bool
    x: float
    y: float
    vy: float
    palm_t: float = 0.0
    fist_t: float = 0.0
    judged: bool = False
    state: str = "falling"   # falling | caught | gone
    fade: float = 0.0


def lerp(pair: tuple[float, float], t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * t


class CatchOrDrop(Minigame):
    """Palm to catch the good paperwork, fist to let the P45s fall. Don't get sacked."""

    title = "Don't Get Fired"
    tracker_cls = HandTracker

    def __init__(self, screen: pygame.Surface, tracker: HandTracker | None = None) -> None:
        super().__init__(screen, tracker)
        self.tiny_font = pygame.font.Font(None, 18)
        self._overlay: pygame.Surface | None = None
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Open Palm", "Show an open palm to catch good paperwork"),
            Action("Fist", "Make a fist to let a P45 fall"),
        )

    def start(self) -> None:
        super().start()
        self.elapsed = 0.0
        self.score = 0
        self.lives = LIVES
        self.spawned = 0
        self.resolved = 0
        self.bad_run = 0
        self.spawn_timer = 99.0     # spawn the first object as soon as play starts
        self.items: list[Item] = []
        self.particles: list[list] = []

        self.hand: str | None = None

        self.mode = "ready"
        self.ready_t = 0.0
        self.flash_t = 0.0
        self.flash_text = ""
        self.flash_color = GOOD_COLOR

    # ------------------------------------------------------------- geometry
    def _geom(self) -> tuple[int, int, int, int, int]:
        """(width, hand_y, zone_top, zone_bottom, ground_y)"""
        w, h = self.screen.get_size()
        hand_y = h - 120
        return w, hand_y, hand_y - 150, hand_y - 20, hand_y + 70

    # --------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(dt, 0.1)
        self.flash_t = max(0.0, self.flash_t - dt)
        self._read_hand()
        self._update_particles(dt)

        if self.mode == "ready":
            self.ready_t += dt
            if self.ready_t >= READY_SECONDS:
                self.mode = "play"
            return

        self.elapsed += dt
        self._spawn(dt)
        self._update_items(dt)

        if self.lives <= 0:
            self.finish(False)
        elif self.resolved >= TARGET_OBJECTS:
            self.finish(True)

    def _read_hand(self) -> None:
        self.hand = self.tracker.gesture if self.tracker.available else None

    def _spawn(self, dt: float) -> None:
        if self.spawned >= TARGET_OBJECTS:
            return
        self.spawn_timer += dt
        progress = self.spawned / max(1, TARGET_OBJECTS - 1)
        if self.spawn_timer < lerp(SPAWN_INTERVAL, progress):
            return
        self.spawn_timer = 0.0

        w, hand_y, _, _, _ = self._geom()
        bad = self.spawned >= 2 and self.bad_run < 2 and random.random() < BAD_CHANCE
        self.bad_run = self.bad_run + 1 if bad else 0
        kind = random.choice(BAD_KINDS if bad else GOOD_KINDS)
        spawn_y = -OBJ_R - 10
        vy = (hand_y - spawn_y) / lerp(FALL_TIME, progress)
        self.items.append(Item(kind, not bad, w / 2 + random.uniform(-70, 70), spawn_y, vy))
        self.spawned += 1

    def _update_items(self, dt: float) -> None:
        w, hand_y, zone_top, zone_bot, ground_y = self._geom()
        for it in self.items:
            if it.state == "caught":
                it.fade -= dt
                if it.fade <= 0:
                    it.state = "gone"
                continue
            it.y += it.vy * dt
            if not it.judged:
                if zone_top <= it.y <= zone_bot:
                    self._sample(it, dt)
                if not it.judged and it.y > zone_bot:
                    self._judge(it, caught=False)
            if it.y >= ground_y and it.state == "falling":
                self._burst(it.x, ground_y, KIND_COLORS[it.kind], 14, 260)
                it.state = "gone"
        self.items = [it for it in self.items if it.state != "gone"]

    def _sample(self, it: Item, dt: float) -> None:
        """Called every frame the item is inside the catch zone."""
        it.palm_t = it.palm_t + dt if self.hand == "palm" else max(0.0, it.palm_t - 2 * dt)
        it.fist_t = it.fist_t + dt if self.hand == "fist" else max(0.0, it.fist_t - 2 * dt)
        if it.palm_t >= PALM_HOLD:
            self._judge(it, caught=True)

    def _judge(self, it: Item, caught: bool) -> None:
        w, hand_y, _, _, _ = self._geom()
        it.judged = True
        self.resolved += 1
        if caught:
            it.state, it.fade = "caught", 0.3
            it.x, it.y = w / 2, hand_y - 30
            if it.good:
                self._success(GOOD_FLASH[it.kind])
            else:
                self._burst(it.x, it.y, KIND_COLORS[it.kind], 28, 380)
                self._failure("YOU'RE FIRED!" if it.kind == "fired" else "P45 ACCEPTED!")
        elif it.good:
            self._failure("PAPERWORK LOST!")
        elif it.fist_t >= FIST_HOLD:
            self._success("DODGED THE SACK!")
        else:
            self._failure("SHOW A FIST!")

    def _success(self, text: str) -> None:
        self.score += 1
        self.flash_text, self.flash_color, self.flash_t = text, GOOD_COLOR, FLASH_SECONDS

    def _failure(self, text: str) -> None:
        self.lives -= 1
        self.flash_text, self.flash_color, self.flash_t = text, BAD_COLOR, FLASH_SECONDS

    # ------------------------------------------------------------ particles
    def _burst(self, x: float, y: float, color: tuple[int, int, int], count: int, speed: float) -> None:
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            sp = random.uniform(0.3, 1.0) * speed
            self.particles.append(
                [x, y, math.cos(angle) * sp, math.sin(angle) * sp - 80, random.uniform(0.35, 0.7), color])

    def _update_particles(self, dt: float) -> None:
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 700 * dt
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]

    # ----------------------------------------------------------------- draw
    def draw(self, screen: pygame.Surface) -> None:
        w, hand_y, zone_top, zone_bot, ground_y = self._geom()
        h = screen.get_height()
        screen.fill(BG)
        pygame.draw.rect(screen, FLOOR, (0, ground_y, w, h - ground_y))

        # catch zone: brightens while an object you still need to deal with is inside it
        active = any(not it.judged and zone_top <= it.y <= zone_bot for it in self.items)
        if self._overlay is None or self._overlay.get_size() != (w, h):
            self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        self._overlay.fill((0, 0, 0, 0))
        pygame.draw.rect(self._overlay, (255, 255, 255, 70 if active else 25),
                         (w // 2 - 150, zone_top, 300, zone_bot - zone_top), border_radius=14)
        screen.blit(self._overlay, (0, 0))
        pygame.draw.rect(screen, (200, 200, 220) if active else (90, 90, 110),
                         (w // 2 - 150, zone_top, 300, zone_bot - zone_top), 2, border_radius=14)

        for it in self.items:
            self._draw_item(screen, it)
        self._draw_hand(screen, w // 2, hand_y)
        for x, y, _, _, life, color in self.particles:
            pygame.draw.circle(screen, color, (int(x), int(y)), max(2, int(life * 10)))

        self._draw_hud(screen)

        if self.mode == "ready":
            draw_text_centered(screen, self.big_font, "OPEN PALM = CATCH", GOOD_COLOR, (w // 2, 150))
            draw_text_centered(screen, self.big_font, "FIST = LET P45s FALL", BAD_COLOR, (w // 2, 215))
            draw_text_centered(screen, self.font, "Get ready...", (230, 230, 230), (w // 2, 270))
        elif self.flash_t > 0:
            draw_text_centered(screen, self.big_font, self.flash_text, self.flash_color, (w // 2, 110))

    def _paper(self, screen: pygame.Surface, x: int, y: int, w: int, h: int,
               fill=PAPER, border=DARK) -> pygame.Rect:
        rect = pygame.Rect(x - w // 2, y - h // 2, w, h)
        pygame.draw.rect(screen, fill, rect, border_radius=3)
        pygame.draw.rect(screen, border, rect, 3, border_radius=3)
        return rect

    def _text_lines(self, screen: pygame.Surface, rect: pygame.Rect, top: int, count: int,
                    color=INK, gap: int = 8, pad: int = 9) -> None:
        for i in range(count):
            end = rect.right - pad - (10 if i == count - 1 else 0)
            yy = rect.top + top + i * gap
            pygame.draw.line(screen, color, (rect.left + pad, yy), (end, yy), 2)

    def _draw_contract(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 52, 68)
        pygame.draw.rect(screen, INK, (r.left + 9, r.top + 8, r.w - 18, 4))
        self._text_lines(screen, r, 20, 4)
        sig = [(r.left + 9, r.bottom - 12), (r.left + 15, r.bottom - 20), (r.left + 20, r.bottom - 10),
               (r.left + 26, r.bottom - 19), (r.left + 32, r.bottom - 12)]
        pygame.draw.lines(screen, (40, 80, 200), False, sig, 2)
        pygame.draw.circle(screen, BAD_COLOR, (r.right - 12, r.bottom - 14), 7)
        pygame.draw.circle(screen, (150, 30, 30), (r.right - 12, r.bottom - 14), 7, 2)

    def _draw_document(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 52, 68, fill=(232, 240, 255))
        fold = [(r.right - 14, r.top), (r.right, r.top + 14), (r.right - 14, r.top + 14)]
        pygame.draw.polygon(screen, (170, 190, 230), fold)
        pygame.draw.polygon(screen, DARK, fold, 2)
        self._text_lines(screen, r, 20, 5, color=(110, 130, 170))

    def _draw_program(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = pygame.Rect(x - 34, y - 28, 68, 56)
        pygame.draw.rect(screen, (28, 32, 46), r, border_radius=5)
        bar = pygame.Rect(r.left, r.top, r.w, 13)
        pygame.draw.rect(screen, (70, 80, 115), bar, border_top_left_radius=5, border_top_right_radius=5)
        for i, c in enumerate(((255, 95, 90), (255, 190, 60), (60, 200, 90))):
            pygame.draw.circle(screen, c, (r.left + 8 + i * 9, r.top + 6), 3)
        for i, (indent, length) in enumerate(((0, 30), (8, 38), (8, 24), (0, 18))):
            yy = r.top + 22 + i * 8
            pygame.draw.line(screen, (90, 230, 140), (r.left + 7 + indent, yy), (r.left + 7 + indent + length, yy), 2)
        pygame.draw.rect(screen, DARK, r, 3, border_radius=5)

    def _draw_p45(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 52, 68, fill=(250, 240, 200))
        pygame.draw.rect(screen, (200, 60, 60), (r.left + 3, r.top + 3, r.w - 6, 18))
        draw_text_centered(screen, self.small_font, "P45", (255, 255, 255), (r.centerx, r.top + 12))
        self._text_lines(screen, r, 30, 4, color=(140, 120, 70))

    def _draw_fired(self, screen: pygame.Surface, x: int, y: int) -> None:
        r = self._paper(screen, x, y, 58, 68, fill=(255, 235, 235), border=(160, 30, 30))
        draw_text_centered(screen, self.tiny_font, "YOU'RE", (190, 30, 30), (r.centerx, r.top + 17))
        draw_text_centered(screen, self.small_font, "FIRED!", (190, 30, 30), (r.centerx, r.top + 33))
        self._text_lines(screen, r, 48, 3, color=(190, 120, 120))

    def _draw_item(self, screen: pygame.Surface, it: Item) -> None:
        x, y = int(it.x), int(it.y)
        getattr(self, f"_draw_{it.kind}")(screen, x, y)

        ring = GOOD_COLOR if it.good else BAD_COLOR
        pygame.draw.circle(screen, ring, (x, y), OBJ_R + 14, 3)
        draw_text_centered(screen, self.small_font, "CATCH" if it.good else "DROP", ring, (x, y - OBJ_R - 32))

    def _draw_hand(self, screen: pygame.Surface, cx: int, cy: int) -> None:
        if self.hand == "palm":
            c = PALM_COLOR
            pygame.draw.circle(screen, c, (cx, cy + 10), 34)
            for off, ht in ((-27, 46), (-9, 56), (9, 52), (27, 40)):
                pygame.draw.rect(screen, c, (cx + off - 7, cy - 5 - ht, 14, ht), border_radius=7)
            thumb = [(cx - 30, cy + 22), (cx - 60, cy - 2), (cx - 49, cy - 14), (cx - 22, cy + 6)]
            pygame.draw.polygon(screen, c, thumb)
            label = "OPEN PALM"
        elif self.hand == "fist":
            c = FIST_COLOR
            pygame.draw.circle(screen, c, (cx, cy), 38)
            for kx, ky in ((-27, -24), (-9, -28), (9, -28), (27, -24)):
                pygame.draw.circle(screen, c, (cx + kx, cy + ky), 12)
                pygame.draw.circle(screen, DARK, (cx + kx, cy + ky), 12, 2)
            pygame.draw.ellipse(screen, c, (cx - 54, cy - 2, 40, 22))
            pygame.draw.ellipse(screen, DARK, (cx - 54, cy - 2, 40, 22), 2)
            label = "FIST"
        else:
            pygame.draw.circle(screen, (90, 90, 110), (cx, cy), 38, 3)
            label = "no hand / unclear"
        draw_text_centered(screen, self.small_font, label, (210, 210, 220), (cx, cy + 62))

    def _draw_hud(self, screen: pygame.Surface) -> None:
        screen.blit(self.font.render(f"{self.resolved} / {TARGET_OBJECTS}", True, (240, 240, 240)), (10, 10))
        for i in range(LIVES):
            alive = i < self.lives
            pygame.draw.circle(screen, BAD_COLOR if alive else (60, 60, 75), (22 + i * 28, 56), 10)

        draw_camera_preview(screen, self.tracker)

        if self.tracker.available:
            info = f"Hand tracking: {self.tracker.backend}"
        else:
            info = "Hand tracking unavailable"
        draw_status_line(screen, self.small_font, info)
