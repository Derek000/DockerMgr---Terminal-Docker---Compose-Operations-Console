from __future__ import annotations

import difflib


def unified_text_diff(old: str, new: str, fromfile: str = "before", tofile: str = "after") -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile)
    return "".join(diff)
