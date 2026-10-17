import pygame

BAR_BACK = (50, 50, 60)
STATUS_COLOR = (140, 140, 160)


def draw_text_centered(screen: pygame.Surface, font: pygame.font.Font, text: str,
                       color: tuple[int, int, int], center: tuple[int, int]) -> None:
    surf = font.render(text, True, color)
    screen.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))


def draw_bar(screen: pygame.Surface, rect: tuple[int, int, int, int], frac: float,
             color: tuple[int, int, int], back: tuple[int, int, int] = BAR_BACK,
             radius: int = 4) -> None:
    x, y, w, h = rect
    pygame.draw.rect(screen, back, rect, border_radius=radius)
    pygame.draw.rect(screen, color, (x, y, int(w * max(0.0, min(1.0, frac))), h), border_radius=radius)


def draw_camera_preview(screen: pygame.Surface, tracker) -> None:
    """Top-right camera thumbnail, if the tracker has one."""
    preview = tracker.preview_surface() if tracker.available else None
    if preview is None:
        return
    pw, ph = preview.get_size()
    pos = (screen.get_width() - pw - 10, 10)
    screen.blit(preview, pos)
    pygame.draw.rect(screen, (200, 200, 200), (*pos, pw, ph), 2)


def draw_status_line(screen: pygame.Surface, font: pygame.font.Font, text: str,
                     color: tuple[int, int, int] = STATUS_COLOR) -> None:
    screen.blit(font.render(text, True, color), (10, screen.get_height() - 28))
