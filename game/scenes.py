from dataclasses import dataclass

from game.games import Dalgona, DodgeTheManager, RedLightGreenLight, simonsays
from game.minigame import Minigame


@dataclass(frozen=True)
class Scene:
    """A cutscene image with one line of dialogue (narration if no speaker)."""

    image: str
    text: str
    speaker: str | None = None


# Shown before the given minigame; minigames without an entry go straight to their intro.
SCENES: dict[type[Minigame], Scene] = {
    Dalgona: Scene("receptionist_welcome", "Welcome, just sign here please.", "Receptionist"),
    RedLightGreenLight: Scene("receptionist_late", "You are late for your meeting, you better hurry!", "Receptionist"),
    simonsays: Scene("metting_late", "Come on! Sit down, you're late!", "Boss"),  # file name is misspelled
    DodgeTheManager: Scene("boss_looking", "You notice your manager looking for volunteers; make sure you avoid him!"),
}
