from __future__ import annotations

import re

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def normalize_id(value: str) -> str:
    return re.sub(r"\s", "", value).upper()


def gb11643_valid(value: str) -> bool:
    """18 位居民身份证号校验（GB 11643 mod 11-2）。"""
    value = normalize_id(value)
    if len(value) != 18 or not re.fullmatch(r"[1-9]\d{16}[0-9X]", value):
        return False
    total = sum(int(value[i]) * _ID_WEIGHTS[i] for i in range(17))
    return _ID_CHECK[total % 11] == value[17]


def luhn_valid(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not digits or len(digits) < 12:
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def verify(kind: str | None, value: str) -> bool:
    if not kind:
        return True
    if kind == "gb11643":
        return gb11643_valid(value)
    if kind == "not_gb11643":
        return not gb11643_valid(value)
    if kind == "luhn":
        return luhn_valid(value)
    return True