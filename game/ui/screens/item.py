from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: Callable[[], None]
