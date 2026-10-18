import math
from collections.abc import Callable, Sequence

import pygame

from game.assets import get_font
from game.employee import EmployeeRecord
from game.ui.screen import BLANK, Screen


class FinalScoreScreen(Screen):
    fade_in = 0.6
    fade_out = 0.5
    background = BLANK
    suppress_corner_score = True
    LOCK_SECONDS = 5.0

    def __init__(self, on_continue: Callable[[], None], results: Sequence[tuple[str, int, bool]],
                 total_score: int, strikes: int, *, employee_record: EmployeeRecord | None = None) -> None:
        self.on_continue = on_continue
        self.results = list(results)
        self.total_score = total_score
        self.strikes = strikes
        self.employee_record = employee_record
        self.signature_art = employee_record.signature_surface() if employee_record else None
        self.elapsed = 0.0
        self.title_font = get_font(76)
        self.score_font = get_font(68)
        self.summary_font = get_font(34)
        self.quip_font = get_font(29)
        self.row_font = get_font(25)
        self.hint_font = get_font(27)

    @property
    def maximum_score(self) -> int:
        return max(1, len(self.results)) * 1000

    @property
    def percentage(self) -> int:
        return round(self.total_score / self.maximum_score * 100)

    @property
    def rating(self) -> str:
        if self.strikes >= 3:
            return "HR would like a word."
        if self.percentage >= 90:
            return "Fast tracked already."
        if self.percentage >= 75:
            return "A very solid first day."
        if self.percentage >= 55:
            return "You survived. That counts."
        return "Tomorrow is another spreadsheet."

    @property
    def quip(self) -> str:
        if not self.results:
            return "Your performance review is mysteriously blank."
        name, score, won = min(self.results, key=lambda result: result[1])
        if score >= 900 and won:
            return "No notes. HR is suspiciously impressed."
        messages = {
            "Contract Signing Day": "Maybe keep the signature inside the lines next time.",
            "Act Natural": "Casual walking needs a little more casual.",
            "Who's Talking?": "Next meeting, try looking at whoever is actually talking.",
            "Any Volunteers?": "Avoiding eye contact is a useful workplace skill.",
            "A Quick Favour": "Expenses left, contracts right. Your manager remembers.",
            "Merge Request Review": "A green check is usually a fairly strong hint.",
            "Coffee Run": "Try not to spill the boss's coffee next time.",
            "One Last Print": "The printer won that round, but only just.",
        }
        return messages.get(name, "There is always tomorrow's performance review.")

    def update(self, dt: float) -> None:
        self.elapsed += dt

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.elapsed >= self.LOCK_SECONDS and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.on_continue()

    def gesture_continue(self) -> None:
        if self.elapsed >= self.LOCK_SECONDS:
            self.on_continue()

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        surface.fill((8, 28, 50))
        glow = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.circle(glow, (20, 105, 175, 65), (width // 2, int(height * 0.18)), int(width * 0.36))
        surface.blit(glow, (0, 0))

        title = self.title_font.render("FIRST DAY REVIEW" if self.strikes >= 3 else "FIRST DAY COMPLETE", True, (250, 215, 110))
        surface.blit(title, title.get_rect(midtop=(width // 2, int(height * 0.055))))

        score = self.score_font.render(f"{self.total_score:,} / {self.maximum_score:,}", True, (248, 249, 246))
        surface.blit(score, score.get_rect(midtop=(width // 2, int(height * 0.17))))

        summary = self.summary_font.render(
            f"{self.percentage}% performance     {self.strikes} of 3 strikes", True, (164, 210, 238)
        )
        surface.blit(summary, summary.get_rect(midtop=(width // 2, int(height * 0.275))))
        rating = self.summary_font.render(self.rating, True, (115, 225, 150))
        surface.blit(rating, rating.get_rect(midtop=(width // 2, int(height * 0.315))))
        quip = self.quip_font.render(self.quip, True, (224, 229, 232))
        surface.blit(quip, quip.get_rect(midtop=(width // 2, int(height * 0.36))))

        self._draw_keepsakes(surface)
        panel = pygame.Rect(int(width * 0.10), int(height * 0.655), int(width * 0.80), int(height * 0.23))
        pygame.draw.rect(surface, (15, 46, 77), panel, border_radius=18)
        pygame.draw.rect(surface, (52, 105, 145), panel, 2, border_radius=18)

        columns = 2
        rows = max(1, (len(self.results) + columns - 1) // columns)
        column_width = panel.width // columns
        row_height = panel.height // rows
        pygame.draw.line(surface, (44, 83, 113), (panel.centerx, panel.top + 18),
                         (panel.centerx, panel.bottom - 18), 1)
        for index, (name, points, won) in enumerate(self.results):
            column = index // rows
            row = index % rows
            x = panel.left + column * column_width + 26
            y = panel.top + row * row_height + row_height // 2
            dot_color = (83, 205, 126) if won else (232, 91, 79)
            pygame.draw.circle(surface, dot_color, (x, y), 7)
            label = self.row_font.render(name, True, (232, 239, 244))
            surface.blit(label, label.get_rect(midleft=(x + 17, y)))
            value = self.row_font.render(f"{points:,}", True, (250, 215, 110))
            value_right = panel.left + (column + 1) * column_width - 24
            surface.blit(value, value.get_rect(midright=(value_right, y)))

        if self.elapsed < self.LOCK_SECONDS:
            remaining = max(1, math.ceil(self.LOCK_SECONDS - self.elapsed))
            hint_text = f"Final results     {remaining}"
            hint_color = (145, 163, 180)
        else:
            hint_text = "Pinch your fingers together to finish"
            hint_color = (185, 211, 228)
        hint = self.hint_font.render(hint_text, True, hint_color)
        surface.blit(hint, hint.get_rect(midbottom=(width // 2, height - 28)))

    def _draw_keepsakes(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        card = pygame.Rect(int(width * 0.10), int(height * 0.425), int(width * 0.80), int(height * 0.20))
        pygame.draw.rect(surface, (247, 243, 225), card, border_radius=16)
        photo_box = pygame.Rect(card.x + 12, card.y + 10, int(card.width * 0.20), card.height - 20)
        record = self.employee_record
        if record and record.photo is not None:
            from game.assets import cover
            surface.blit(cover(record.photo, photo_box.size), photo_box)
        else:
            pygame.draw.rect(surface, (202, 211, 207), photo_box, border_radius=10)
            pygame.draw.circle(surface, (112, 137, 145), (photo_box.centerx, photo_box.y + photo_box.height // 3), max(8, photo_box.height // 6))
            pygame.draw.ellipse(surface, (112, 137, 145), (photo_box.x + photo_box.width // 4, photo_box.centery, photo_box.width // 2, photo_box.height // 2))
        x = photo_box.right + 20
        heading = get_font(max(18, min(28, height // 30))).render("EMPLOYEE SIGNATURE", True, (25, 55, 81))
        surface.blit(heading, (x, card.y + 12))
        area = pygame.Rect(x, card.y + 42, max(1, card.right - x - 20), max(1, card.height - 62))
        if self.signature_art is not None:
            factor = min(area.width / self.signature_art.get_width(), area.height / self.signature_art.get_height())
            art = pygame.transform.smoothscale(self.signature_art, (
                max(1, round(self.signature_art.get_width() * factor)),
                max(1, round(self.signature_art.get_height() * factor))))
            surface.blit(art, art.get_rect(center=area.center))
        else:
            note = get_font(22).render("No signature recorded", True, (92, 107, 113))
            surface.blit(note, note.get_rect(midleft=(x, area.centery)))
        if record and record.save_error:
            note = get_font(18).render("Shown for this run; local save unavailable.", True, (155, 72, 55))
            surface.blit(note, (x, card.bottom - 20))
