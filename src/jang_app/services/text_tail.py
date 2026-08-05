from __future__ import annotations


def text_tail(value: object, *, max_lines: int = 40, max_chars: int = 6000) -> str:
    lines = str(value or "").splitlines()
    tail = "\n".join(lines[-max(1, max_lines) :]).strip()
    if len(tail) <= max_chars:
        return tail
    return tail[-max(1, max_chars) :].lstrip()


def combined_output(*values: object) -> str:
    parts = [str(value).strip() for value in values if str(value or "").strip()]
    return "\n".join(dict.fromkeys(parts))
