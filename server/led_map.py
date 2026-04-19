"""
Map chess squares to simple 1D LED strip indices for WS2812-style layouts.

Convention (matches a typical edge-mounted strip layout):
- **base_strip**: 8 LEDs, one per **file** (a=0 … h=7). Use to highlight which
  vertical file the square sits on (strip along the bottom rank edge).
- **side_strip**: 8 LEDs, one per **rank** (rank 1 = index 0 … rank 8 = index 7).
  Use to highlight which horizontal rank the square sits on (strip along the a-file edge).

Firmware can light **both** indices at once to identify a square in the grid
(intersection of column + row), or drive a full perimeter strip with a lookup table
you replace later — this stays a stable server-side contract.
"""

from __future__ import annotations


def uci_to_from_to(uci: str) -> tuple[str, str]:
    u = (uci or "").strip().lower()
    if len(u) < 4:
        raise ValueError("UCI must be at least 4 characters (e.g. e2e4)")
    from_sq = u[0:2]
    to_sq = u[2:4]
    for sq in (from_sq, to_sq):
        if not _valid_square(sq):
            raise ValueError(f"Invalid square in UCI: {uci!r}")
    return from_sq, to_sq


def _valid_square(sq: str) -> bool:
    if len(sq) != 2:
        return False
    f, r = sq[0], sq[1]
    return "a" <= f <= "h" and "1" <= r <= "8"


def square_to_led_indices(square: str) -> dict:
    sq = square.strip().lower()
    if not _valid_square(sq):
        raise ValueError(f"Invalid square: {square!r}")
    file_i = ord(sq[0]) - ord("a")
    rank_n = int(sq[1])
    side_led = rank_n - 1  # rank 1 -> 0
    return {
        "square": sq,
        "file": sq[0],
        "rank": rank_n,
        "base_led": file_i,  # column / file
        "side_led": side_led,  # row / rank
    }


def rgb_for_phase(phase: str, *, from_rgb=(255, 80, 0), to_rgb=(0, 200, 255)) -> tuple[int, int, int]:
    if phase == "from":
        return from_rgb
    if phase == "to":
        return to_rgb
    return (0, 0, 0)
