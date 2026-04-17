from __future__ import annotations


def clamp(value: float, minimum: float, maximum: float):
    return max(minimum, min(maximum, value))


def tune_threshold(current: float, direction: float, minimum: float, maximum: float):
    return clamp(round(current + direction, 2), minimum, maximum)

