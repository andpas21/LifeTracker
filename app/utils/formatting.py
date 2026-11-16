"""Formattazione e lettura di numeri e durate (convenzioni italiane)."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def fmt_number(value, max_decimals: int = 2) -> str:
    """1234.5 → '1.234,5'  ·  2.0 → '2'"""
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    quantized = round(number, max_decimals)
    text = f"{quantized:,.{max_decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_duration(seconds) -> str:
    """5400 → '1:30'  ·  3725 → '1:02:05'"""
    if seconds is None or seconds == "":
        return ""
    total = int(round(float(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if secs else f"{hours}:{minutes:02d}"


def fmt_hours(seconds) -> str:
    """Durata in forma leggibile per i riepiloghi: '12 h 30 min'."""
    total_minutes = int(round(float(seconds or 0) / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


_DURATION_RE = re.compile(r"^(\d+):([0-5]?\d)(?::([0-5]?\d))?$")


def parse_duration(text: str) -> int:
    """'1:30' → 5400 s  ·  '1:02:05' → 3725 s  ·  '45' (minuti) → 2700 s  ·  '1,5' (minuti) → 90 s."""
    text = (text or "").strip().replace(" ", "")
    match = _DURATION_RE.match(text)
    if match:
        hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    try:
        minutes = Decimal(text.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Durata non valida: usa ore:minuti (es. 1:30) oppure i minuti (es. 90).") from exc
    if minutes < 0:
        raise ValueError("La durata non può essere negativa.")
    return int(minutes * 60)


def parse_decimal(text: str) -> Decimal:
    """Accetta sia la virgola sia il punto come separatore decimale."""
    text = (text or "").strip().replace(" ", "")
    if text.count(",") == 1 and "." in text:  # 1.234,5
        text = text.replace(".", "")
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Numero non valido.") from exc
