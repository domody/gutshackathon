import pygame


class Game:
    """Owns the window, the main loop, and top-level lifecycle."""

    TITLE = "Guts Hackathon"
    SIZE = (800, 600)
    FPS = 60
    BACKGROUND = (20, 20, 30)
    TEXT_COLOR = (240, 240, 240)

    def __init__(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode(self.SIZE)
        pygame.display.set_caption(self.TITLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 72)
        self.running = False

    def run(self) -> None:
        self.running = True
        while self.running:
            dt = self.clock.tick(self.FPS) / 1000
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

    def update(self, dt: float) -> None:
        pass

    def draw(self) -> None:
        self.screen.fill(self.BACKGROUND)
        text = self.font.render("Hello, World!", True, self.TEXT_COLOR)
        self.screen.blit(text, text.get_rect(center=self.screen.get_rect().center))
        pygame.display.flip()
