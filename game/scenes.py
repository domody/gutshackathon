from dataclasses import dataclass

from game.games import MergeRequestReview, CoffeeRun, ContractSigningDay, DodgeTheManager, PaperSort, RunToMeeting, OneLastPrint, WhosTalking
from game.minigame import Minigame


@dataclass(frozen=True)
class Scene:
    image: str
    text: str
    speaker: str | None = None


BEFORE_SCENES: dict[type[Minigame], tuple[Scene, ...]] = {
    ContractSigningDay: (
        Scene("receptionist_welcome", "Welcome! Put your name here, then sign both agreements.", "Receptionist"),
    ),
    RunToMeeting: (
        Scene("receptionist_late", "Your meeting has already started. You should probably run.", "Receptionist"),
    ),
    WhosTalking: (
        Scene("metting_late", "There you are. Sit down and try to follow who's speaking.", "Colleague"),
    ),
    DodgeTheManager: (
        Scene("boss_looking", "The manager is looking for volunteers. Reach your office before he reaches you."),
    ),
    PaperSort: (
        Scene("papers_unsorted", "Perfect, thank you for volunteering! Expenses left, contracts right.", "Manager"),
    ),
    MergeRequestReview: (
        Scene("desk", "Back at your desk, the merge requests are already piling up."),
    ),
    CoffeeRun: (
        Scene("boss_coffee", "Before you go, could you grab me some coffee?", "Boss"),
    ),
    OneLastPrint: (
        Scene("printer", "One last print. Then you can go home."),
    ),
}

AFTER_SCENES: dict[type[Minigame], tuple[Scene, ...]] = {
    PaperSort: (
        Scene("papers_sorted", "Excellent. I knew volunteering was the right choice for you.", "Manager"),
    ),
    OneLastPrint: (
        Scene("jpmc_building", "Wow. What a first day."),
    ),
}

SCENES = {game: scenes[0] for game, scenes in BEFORE_SCENES.items()}
