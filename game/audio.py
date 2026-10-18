from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pygame


class SoundBank:
    def __init__(self) -> None:
        self.enabled = False
        self.scratch_channel: pygame.mixer.Channel | None = None
        self.running_channel: pygame.mixer.Channel | None = None
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
            "correct": ((587.33, 698.46), 0.10, 0.055),
            "mistake": ((220.0, 174.61), 0.14, 0.05),
            "paper": ((440.0, 493.88), 0.08, 0.035),
            "pull": ((164.81, 220.0), 0.11, 0.045),
            "combo": ((659.25, 783.99), 0.11, 0.06),
        }
        spec = sounds.get(name)
        if not spec:
            return
        sound = self._tone(*spec)
        if sound is not None:
            sound.play()

    @lru_cache(maxsize=1)
    def _scratch(self) -> pygame.mixer.Sound | None:
        if not self.enabled:
            return None
        sample_rate = pygame.mixer.get_init()[0]
        count = max(1, int(sample_rate * 1.35))
        generator = np.random.default_rng(7319)
        noise = generator.normal(0.0, 1.0, count)
        grain = noise - np.convolve(noise, np.ones(13) / 13, mode="same")
        envelope = np.full(count, 0.16, dtype=np.float64)
        for center, width, strength in ((0.13, 0.20, 0.72), (0.54, 0.29, 1.0), (1.04, 0.24, 0.82)):
            distance = (np.arange(count) / sample_rate - center) / width
            envelope += np.exp(-(distance * distance) * 4.0) * strength
        slow_drag = 0.78 + 0.22 * np.sin(np.arange(count) * math.tau * 1.15 / sample_rate + 0.6)
        edge_fade = np.sin(np.linspace(0, math.pi, count)) ** 0.32
        samples = np.clip(grain * envelope * slow_drag * edge_fade * 0.018 * 32767,
                          -32767, 32767).astype(np.int16)
        stereo = np.column_stack((samples, samples))
        return pygame.sndarray.make_sound(stereo)

    def set_pen_scratching(self, active: bool) -> None:
        if not self.enabled:
            return
        if active:
            if self.scratch_channel is None or not self.scratch_channel.get_busy():
                sound = self._scratch()
                if sound is not None:
                    self.scratch_channel = sound.play(loops=-1, fade_ms=35)
        elif self.scratch_channel is not None:
            self.scratch_channel.fadeout(45)
            self.scratch_channel = None

    @lru_cache(maxsize=1)
    def _running(self) -> pygame.mixer.Sound | None:
        if not self.enabled:
            return None
        sample_rate = pygame.mixer.get_init()[0]
        duration = 0.40
        count = max(1, int(sample_rate * duration))
        wave = np.zeros(count, dtype=np.float64)
        generator = np.random.default_rng(8451)
        for moment in (0.0, 0.20):
            start = int(moment * sample_rate)
            length = min(count - start, int(sample_rate * 0.095))
            local = np.arange(length, dtype=np.float64) / sample_rate
            decay = np.exp(-local * 38.0)
            thump = np.sin(2 * math.pi * 78.0 * local) * decay
            texture = generator.normal(0.0, 0.18, length) * decay
            wave[start:start + length] += thump + texture
        samples = np.clip(wave * 0.075 * 32767, -32767, 32767).astype(np.int16)
        stereo = np.column_stack((samples, samples))
        return pygame.sndarray.make_sound(stereo)

    def set_running(self, active: bool) -> None:
        if not self.enabled:
            return
        if active:
            if self.running_channel is None or not self.running_channel.get_busy():
                sound = self._running()
                if sound is not None:
                    self.running_channel = sound.play(loops=-1, fade_ms=45)
        elif self.running_channel is not None:
            self.running_channel.fadeout(70)
            self.running_channel = None


sound_bank = SoundBank()
