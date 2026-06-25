"""A small, dependency-free progress bar styled after the `ord` indexer.

Renders a single self-updating line to stderr when attached to a TTY, e.g.:

    Indexing  62%|███████████████████░░░░░░░░░░░| 0 counters

When stderr is not a TTY (piped/redirected) it degrades to nothing on the bar
itself; callers should still emit periodic log lines in that case.
"""

from __future__ import annotations

import shutil
import sys
import time
from typing import TextIO


class ProgressBar:
    def __init__(
        self,
        total: int,
        desc: str = "Indexing",
        width: int = 30,
        stream: TextIO | None = None,
        min_interval: float = 0.1,
        initial: int = 0,
    ) -> None:
        self.total = max(total, 0)
        self.desc = desc
        self.width = width
        self.stream = stream or sys.stderr
        self.min_interval = min_interval
        self.enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.start = time.monotonic()
        self._last_render = 0.0
        # `initial` = absolute position already completed before this session
        # (e.g. blocks indexed in a previous run). The displayed position `n`
        # is absolute so it never resets on resume, while rate/ETA are based on
        # work done THIS session (n - initial).
        self.initial = max(initial, 0)
        self.n = self.initial
        self.postfix = ""

    def update(self, n: int, postfix: str = "") -> None:
        self.n = n
        if postfix:
            self.postfix = postfix
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last_render < self.min_interval and n < self.total:
            return
        self._last_render = now
        self._render()

    def _render(self) -> None:
        total = self.total or 1
        frac = min(max(self.n / total, 0.0), 1.0)
        filled = int(round(self.width * frac))
        bar = "█" * filled + "░" * (self.width - filled)
        line = f"{self.desc} {frac * 100:3.0f}%|{bar}| {self.n}/{self.total}"
        if self.postfix:
            line += f" · {self.postfix}"
        # Truncate to the terminal width so the line never wraps onto a second
        # physical row (wrapping would defeat the in-place \r redraw and spew
        # lines). \r returns to col 0, \033[K clears the rest of the line.
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        if len(line) > cols:
            line = line[: max(cols - 1, 0)]
        self.stream.write(f"\r\033[K{line}")
        self.stream.flush()

    def write(self, msg: str) -> None:
        """Print a message above the bar without corrupting it."""
        if self.enabled:
            self.stream.write("\r\033[K")
            self.stream.write(msg + "\n")
            self._render()
        else:
            self.stream.write(msg + "\n")
        self.stream.flush()

    def close(self) -> None:
        if self.enabled:
            self._render()
            self.stream.write("\n")
            self.stream.flush()
