"""
Voice announcements via VoxCPM (clone timbre from a reference .wav).

Use VoiceAnnouncerStub (--stub-voice) when developing without the model.
"""

from __future__ import annotations

import threading
from typing import Optional

_PIECE_WORD = {
    "K": "king",
    "Q": "queen",
    "R": "rook",
    "B": "bishop",
    "N": "knight",
}
_PROMO_WORD = {"Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}


def san_to_speech(san: str) -> str:
    """Turn SAN (e.g. Nf3, O-O, exd5+) into short spoken English."""
    check_suffix = ""
    s = san
    if s.endswith("#"):
        check_suffix = ", checkmate"
        s = s[:-1]
    elif s.endswith("+"):
        check_suffix = ", check"
        s = s[:-1]

    promo_suffix = ""
    if "=" in s:
        main, promo = s.rsplit("=", 1)
        s = main
        pw = _PROMO_WORD.get(promo, promo.lower())
        promo_suffix = f", promotes to {pw}"

    if s == "O-O-O":
        return f"queenside castle{check_suffix}{promo_suffix}"
    if s == "O-O":
        return f"kingside castle{check_suffix}{promo_suffix}"

    if s and s[0] in _PIECE_WORD:
        piece = _PIECE_WORD[s[0]]
        rest = s[1:]
        if "x" in rest:
            before, after = rest.split("x", 1)
            dest = after
            if before:
                return f"{piece} on {before} takes {dest}{check_suffix}{promo_suffix}"
            return f"{piece} takes {dest}{check_suffix}{promo_suffix}"
        return f"{piece} to {rest}{check_suffix}{promo_suffix}"

    if "x" in s:
        ffile, rest = s.split("x", 1)
        return f"{ffile} pawn takes {rest}{check_suffix}{promo_suffix}"
    return f"pawn to {s}{check_suffix}{promo_suffix}"


class VoiceAnnouncerStub:
    def say(self, text: str) -> None:
        print(f"[VOICE] {text}")

    def wait(self) -> None:
        pass


class VoiceAnnouncer:
    """Non-blocking TTS: each say() queues after the previous clip finishes."""

    def __init__(self, reference_wav: str):
        from voxcpm import VoxCPM
        import sounddevice as sd

        self._model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
        self._ref = reference_wav
        self._sd = sd
        self._thread: Optional[threading.Thread] = None

    def say(self, text: str) -> None:
        def _run() -> None:
            wav = self._model.generate(
                text=text,
                reference_wav_path=self._ref,
                cfg_value=2.0,
                inference_timesteps=10,
            )
            self._sd.play(wav, self._model.tts_model.sample_rate)
            self._sd.wait()

        if self._thread and self._thread.is_alive():
            self._thread.join()
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def wait(self) -> None:
        if self._thread:
            self._thread.join()
