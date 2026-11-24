from collections import deque


class SilenceGate:
    def __init__(
        self,
        *,
        enabled: bool = True,
        rms_threshold: float = 120.0,
        hangover_frames: int = 24,
        preroll_frames: int = 4,
    ):
        self.enabled = enabled
        self.rms_threshold = rms_threshold
        self.hangover_frames = hangover_frames
        self._speaking = False
        self._hangover_left = 0
        self._preroll: deque[bytes] = deque(maxlen=preroll_frames)
        self.dropped_frames = 0
        self.passed_frames = 0

    def process(self, pcm: bytes, rms: float) -> list[bytes]:
        if not self.enabled:
            self.passed_frames += 1
            return [pcm]

        if rms >= self.rms_threshold:
            frames = [] if self._speaking else list(self._preroll)
            self._preroll.clear()
            frames.append(pcm)
            self._speaking = True
            self._hangover_left = self.hangover_frames
            self.passed_frames += len(frames)
            return frames

        if self._speaking and self._hangover_left > 0:
            self._hangover_left -= 1
            if self._hangover_left == 0:
                self._speaking = False
            self.passed_frames += 1
            return [pcm]

        self._preroll.append(pcm)
        self.dropped_frames += 1
        return []

    def reset(self) -> None:
        self._speaking = False
        self._hangover_left = 0
        self._preroll.clear()
