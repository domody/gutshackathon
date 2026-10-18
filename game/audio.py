from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pygame


class SoundBank:
    def __init__(self) -> None:
        self.enabled = False
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self.enabled = pygame.mixer.get_init() is not None
        except pygame.error:
            self.enabled = False

    @lru_cache(maxsize=None)
    def _tone(self, frequencies: tuple[float, ...], duration: float, volume: float) -> pygame.mixer.Sound | None:
        if not self.enabled:
            return None
        sample_rate = pygame.mixer.get_init()[0]
        count = max(1, int(sample_rate * duration))
        times = np.arange(count, dtype=np.float64) / sample_rate
        wave = np.zeros(count, dtype=np.float64)
        segment = count / len(frequencies)
        for index, frequency in enumerate(frequencies):
            start = round(index * segment)
            end = round((index + 1) * segment)
            local = times[start:end] - times[start]
            wave[start:end] = np.sin(2 * math.pi * frequency * local)
        attack = max(1, int(sample_rate * 0.012))
        release = max(1, int(sample_rate * min(0.08, duration * 0.35)))
        envelope = np.ones(count)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-release:] = np.linspace(1, 0, release)
        samples = np.clip(wave * envelope * volume * 32767, -32767, 32767).astype(np.int16)
        stereo = np.column_stack((samples, samples))
        return pygame.sndarray.make_sound(stereo)

    def play(self, name: str) -> None:
        sounds = {
            "transition": ((392.0, 523.25), 0.16, 0.07),
            "confirm": ((523.25, 659.25), 0.13, 0.08),
            "success": ((523.25, 659.25, 783.99), 0.27, 0.09),
            "failure": ((293.66, 246.94), 0.24, 0.07),
            "shutter": ((185.0, 110.0), 0.09, 0.10),
        }
        spec = sounds.get(name)
        if not spec:
            return
        sound = self._tone(*spec)
        if sound is not None:
            sound.play()


sound_bank = SoundBank()
