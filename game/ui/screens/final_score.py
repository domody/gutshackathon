import math
from collections.abc import Callable, Sequence

import pygame

from game.assets import cover, get_font
from game.employee import EmployeeRecord
from game.ui.screen import BLANK, Screen


class FinalScoreScreen(Screen):
    sound = "success"
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
    def grade(self) -> str:
        if self.strikes >= 3:
            return "F"
        if self.percentage >= 90:
            return "A"
        if self.percentage >= 75:
            return "B"
        if self.percentage >= 60:
            return "C"
        return "D"

    @property
    def feedback(self) -> list[str]:
        if not self.results:
            return ["Your performance review is mysteriously blank."]
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
        weakest = sorted(self.results, key=lambda result: (result[2], result[1]))[:2]
        notes = [messages[name] for name, score, won in weakest if (not won or score < 850) and name in messages]
        if not notes:
            notes.append("No notes. HR is suspiciously impressed.")
        elif len(notes) == 1 and self.percentage >= 75:
            notes.insert(0, "Good first day. You might actually survive the internship.")
        return notes[:2]

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

        heading = "FIRST DAY REVIEW" if self.strikes >= 3 else "FIRST DAY COMPLETE"
        title = self.title_font.render(heading, True, (250, 215, 110))
        surface.blit(title, title.get_rect(midtop=(width // 2, int(height * 0.055))))

        score = self.score_font.render(f"{self.total_score:,} / {self.maximum_score:,}", True, (248, 249, 246))
        surface.blit(score, score.get_rect(midtop=(width // 2, int(height * 0.17))))

        summary = self.summary_font.render(
            f"GRADE {self.grade}     {self.percentage}% performance     {self.strikes} of 3 strikes",
            True,
            (164, 210, 238),
        )
        surface.blit(summary, summary.get_rect(midtop=(width // 2, int(height * 0.275))))
        rating = self.summary_font.render(self.rating, True, (115, 225, 150))
        surface.blit(rating, rating.get_rect(midtop=(width // 2, int(height * 0.315))))
        for index, line in enumerate(self.feedback):
            note = self.quip_font.render(line, True, (224, 229, 232))
            surface.blit(note, note.get_rect(midtop=(width // 2, int(height * 0.355) + index * 27)))

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
            hint_text = "PINCH TO FINISH"
            hint_color = (185, 211, 228)
        hint = self.hint_font.render(hint_text, True, hint_color)
        surface.blit(hint, hint.get_rect(midbottom=(width // 2, height - 28)))

    def _draw_keepsakes(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        card = pygame.Rect(int(width * 0.10), int(height * 0.425), int(width * 0.80), int(height * 0.20))
        pygame.draw.rect(surface, (247, 243, 225), card, border_radius=16)
        pygame.draw.rect(surface, (84, 139, 173), card, 2, border_radius=16)

        photo_box = pygame.Rect(card.x + 12, card.y + 10, int(card.width * 0.20), card.height - 20)
        record = self.employee_record
        if record and record.photo is not None:
            surface.blit(cover(record.photo, photo_box.size), photo_box)
            pygame.draw.rect(surface, (25, 55, 81), photo_box, 2, border_radius=8)
        else:
            pygame.draw.rect(surface, (202, 211, 207), photo_box, border_radius=8)
            head_y = photo_box.y + photo_box.height // 3
            pygame.draw.circle(surface, (112, 137, 145), (photo_box.centerx, head_y), max(8, photo_box.height // 7))
            pygame.draw.ellipse(
                surface,
                (112, 137, 145),
                (photo_box.x + photo_box.width // 4, photo_box.centery, photo_box.width // 2, photo_box.height // 2),
            )

        content_x = photo_box.right + 22
        badge = get_font(max(16, min(23, height // 31))).render("EMPLOYEE PERSONNEL FILE", True, (43, 103, 146))
        surface.blit(badge, (content_x, card.y + 10))
        signature_label = get_font(max(16, min(22, height // 32))).render("SIGNATURE", True, (25, 55, 81))
        surface.blit(signature_label, (content_x, card.y + 38))
        signature_area = pygame.Rect(
            content_x,
            card.y + 61,
            max(1, card.right - content_x - 20),
            max(1, card.bottom - card.y - 76),
        )
        pygame.draw.line(
            surface,
            (124, 137, 139),
            (signature_area.x, signature_area.bottom),
            (signature_area.right, signature_area.bottom),
            1,
        )
        if self.signature_art is not None:
            scale = min(
                signature_area.width / self.signature_art.get_width(),
                signature_area.height / self.signature_art.get_height(),
            )
            size = (
                max(1, round(self.signature_art.get_width() * scale)),
                max(1, round(self.signature_art.get_height() * scale)),
            )
            signature = pygame.transform.smoothscale(self.signature_art, size)
            surface.blit(signature, signature.get_rect(center=signature_area.center))
        else:
            placeholder = get_font(21).render("No signature recorded", True, (92, 107, 113))
            surface.blit(placeholder, placeholder.get_rect(midleft=(signature_area.x, signature_area.centery)))
        if record and record.save_error:
            warning = get_font(17).render("Saved for this run in memory only", True, (155, 72, 55))
            surface.blit(warning, warning.get_rect(bottomright=(card.right - 14, card.bottom - 5)))
