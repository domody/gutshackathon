"""Example game implementation using the Minigame superclass."""

import random

import pygame

from game.minigame import Action, Minigame

LANES = 3
SURVIVE_SECONDS = 10.0
SPAWN_INTERVAL = 0.6
FALL_SPEED = 300
BLOCK_SIZE = 60


class LaneDodge(Minigame):
    """Dodge falling blocks by switching lanes. Survive to win."""

    title = "Lane Dodge"

    def __init__(self, screen: pygame.Surface) -> None:
        super().__init__(screen)
        self.start()

    @property
    def actions(self) -> tuple[Action, Action]:
        return (
            Action("Move Left", "Shift one lane left (A / Left)", self.move_left),
            Action("Move Right", "Shift one lane right (D / Right)", self.move_right),
        )

    def start(self) -> None:
        self.finished = False
        self.won = False
        self.lane = LANES // 2
        self.elapsed = 0.0
        self.spawn_timer = 0.0
        self.blocks: list[pygame.Rect] = []

    def move_left(self) -> None:
        self.lane = max(0, self.lane - 1)

    def move_right(self) -> None:
        self.lane = min(LANES - 1, self.lane + 1)

    def _lane_x(self, lane: int) -> int:
        lane_w = self.screen.get_width() // LANES
        return lane * lane_w + (lane_w - BLOCK_SIZE) // 2

    def _player_rect(self) -> pygame.Rect:
        y = self.screen.get_height() - BLOCK_SIZE * 2
        return pygame.Rect(self._lane_x(self.lane), y, BLOCK_SIZE, BLOCK_SIZE)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        left, right = self.actions
        if event.key in (pygame.K_a, pygame.K_LEFT):
            left.perform()
        elif event.key in (pygame.K_d, pygame.K_RIGHT):
            right.perform()

    def update(self, dt: float) -> None:
        if self.finished:
            return
        self.elapsed += dt
        self.spawn_timer += dt
        if self.spawn_timer >= SPAWN_INTERVAL:
            self.spawn_timer = 0.0
            x = self._lane_x(random.randrange(LANES))
            self.blocks.append(pygame.Rect(x, -BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE))

        height = self.screen.get_height()
        for block in self.blocks:
            block.y += int(FALL_SPEED * dt)
        self.blocks = [b for b in self.blocks if b.y < height]

        if self._player_rect().collidelist(self.blocks) != -1:
            self.finish(False)
        elif self.elapsed >= SURVIVE_SECONDS:
            self.finish(True)

    def draw(self, screen: pygame.Surface) -> None:
        for block in self.blocks:
            pygame.draw.rect(screen, (220, 70, 70), block)
        pygame.draw.rect(screen, (80, 200, 120), self._player_rect())
        font = pygame.font.Font(None, 36)
        remaining = max(0.0, SURVIVE_SECONDS - self.elapsed)
        screen.blit(font.render(f"{remaining:.1f}s", True, (240, 240, 240)), (10, 10))
