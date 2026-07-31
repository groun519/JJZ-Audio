from __future__ import annotations

from pathlib import Path

from jang_app.config import LOG_FILE


def read_log_tail(path: Path = LOG_FILE, *, max_lines: int = 400, max_bytes: int = 512_000) -> str:
    source = path.expanduser().resolve()
    if not source.is_file():
        return ""

    line_limit = max(1, int(max_lines))
    byte_limit = max(1, int(max_bytes))
    with source.open("rb") as stream:
        stream.seek(0, 2)
        file_size = stream.tell()
        read_size = min(file_size, byte_limit)
        start = file_size - read_size
        stream.seek(max(0, start - 1))
        data = stream.read(read_size + (1 if start > 0 else 0))

    starts_on_line_boundary = start == 0 or data.startswith(b"\n")
    if start > 0 and starts_on_line_boundary:
        data = data[1:]
    text = data.decode("utf-8", errors="replace")
    if start > 0 and not starts_on_line_boundary:
        _, separator, text = text.partition("\n")
        if not separator:
            return ""
    return "\n".join(text.splitlines()[-line_limit:])
