"""modules.alias reader and deterministic matcher (SPEC §7 layer 3).

Design constraints:
- Pure core: ``match`` takes lines in and returns module names in *file order*
  (ADR 0003 D4: same input -> same output, readdir/mtime independent).
- Hostile input is data, not a crash (ADR 0002 S6): alias patterns and modalias
  strings are validated against closed grammars before any comparison runs.
- Matching follows kernel semantics field-wise (usb_device_id match_flags):
  '*' or an absent field in the pattern is unconstrained; a concrete field in
  the pattern must equal the modalias field. This is structural comparison —
  no fnmatch/glob regex, so hostile patterns cannot widen the match.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..host import Host

MODULES_ALIAS_FMT = "/lib/modules/{release}/modules.alias"

#: A modules.alias row: "alias <pattern> <module>", horizontal space only
#: (a newline inside a row means it is not one row -> must not match).
_ROW = re.compile(r"^alias[^\S\n]+([^\s]+)[^\S\n]+([^\s]+)[^\S\n]*$")

#: Closed grammar for a USB modalias string we are willing to match against.
_MODALIAS_OK = re.compile(
    r"^usb:v[0-9A-Fa-f]{4}p[0-9A-Fa-f]{4}d[0-9A-Fa-f]{4}"
    r"(dc[0-9A-Fa-f]{2})?(dsc[0-9A-Fa-f]{2})?(dp[0-9A-Fa-f]{2})?"
    r"(ic(?:\*|[0-9A-Fa-f]{2}))?(isc(?:\*|[0-9A-Fa-f]{2}))?"
    r"(ip(?:\*|[0-9A-Fa-f]{2}))?(in(?:\*|[0-9A-Fa-f]{2}))?$"
)

#: Ordered usb: body fields: (name, hex width for concrete values).
_FIELDS: tuple[tuple[str, int], ...] = (
    ("v", 4),
    ("p", 4),
    ("d", 4),
    ("dc", 2),
    ("dsc", 2),
    ("dp", 2),
    ("ic", 2),
    ("isc", 2),
    ("ip", 2),
    ("in", 2),
)

_HEX = set("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class AliasLine:
    """One parsed alias row plus its exact source line (for evidence)."""

    pattern: str
    module: str
    raw: str


def modules_alias_path(release: str) -> str:
    return MODULES_ALIAS_FMT.format(release=release)


def read_alias_lines(host: Host, release: str) -> list[str]:
    """Raw lines of modules.alias for one kernel release via host.read."""
    return host.read(modules_alias_path(release)).splitlines()


def parse_alias_lines(lines: Iterable[str]) -> list[AliasLine]:
    """Parse well-formed USB rows only; comments/blanks/malformed rows drop.

    Rows whose pattern does not start with ``usb:`` are irrelevant for this
    product and are dropped here so downstream consumers see exactly the
    candidate universe (file order preserved).
    """
    out: list[AliasLine] = []
    for raw in lines:
        m = _ROW.match(raw.strip("\r\n\t "))
        if m and m.group(1).startswith("usb:"):
            out.append(AliasLine(pattern=m.group(1), module=m.group(2), raw=raw))
    return out


def sanitize_modalias(value: str) -> str | None:
    """Closed check for a modalias string; None when it violates the grammar.

    Returns the normalized (uppercase hex) form; sysfs emits uppercase and
    so do the alias files, but we accept either on input.
    """
    v = value.strip()
    if not _MODALIAS_OK.match(v):
        return None
    return v.upper()


def _parse_body(body: str) -> dict[str, str] | None:
    """Parse 'vXXXXpYYYY...' (case-insensitive names, hex or '*') to a map.

    A bare '*' body means 'match anything' -> empty constraint map.
    Returns None on any structural violation — hostile input never matches.
    """
    if body == "*":
        return {}
    fields: dict[str, str] = {}
    pos = 0
    for name, width in _FIELDS:
        if pos >= len(body):
            break
        token = body[pos : pos + len(name)]
        if token.lower() != name:
            return None
        pos += len(name)
        rest = body[pos:]
        if rest.startswith("*"):
            fields[name] = "*"
            pos += 1
        else:
            take = rest[:width]
            if len(take) != width or any(c not in _HEX for c in take):
                return None
            fields[name] = take.upper()
            pos += width
    if pos != len(body):
        return None
    return fields


def _pattern_matches(pattern: str, modalias_str: str) -> bool:
    """Kernel-semantics field-wise comparison (structural, no fnmatch).

    - '*' in a pattern field matches anything.
    - Absent pattern field = unconstrained (kernel match_flags semantics).
    - A concrete pattern field must equal the modalias field; when the
      modalias lacks that field entirely (device-level modalias without
      ic/isc/ip/in), only '*' or absent pattern fields still match.
    """
    if not pattern.lower().startswith("usb:") or len(pattern) <= 4:
        return False
    pf = _parse_body(pattern[4:])
    mf = _parse_body(modalias_str[4:])
    if pf is None or mf is None:
        return False
    for name, _width in _FIELDS:
        pv = pf.get(name)
        if pv is None or pv == "*":
            continue
        if mf.get(name) != pv:
            return False
    return True


def _as_rows(alias_lines: Sequence[str | AliasLine]) -> list[AliasLine]:
    rows: list[AliasLine] = []
    for item in alias_lines:
        if isinstance(item, AliasLine):
            rows.append(item)
        else:
            rows.extend(parse_alias_lines([item]))
    return rows


def match_with_lines(
    modalias_str: str, alias_lines: Sequence[str | AliasLine]
) -> list[AliasLine]:
    """All alias rows whose pattern claims this modalias, file order (pure)."""
    mod = sanitize_modalias(modalias_str)
    if mod is None:
        return []
    return [row for row in _as_rows(alias_lines) if _pattern_matches(row.pattern, mod)]


def match(modalias_str: str, alias_lines: Sequence[str | AliasLine]) -> list[str]:
    """Module names claiming this modalias, file order, duplicates kept."""
    return [row.module for row in match_with_lines(modalias_str, alias_lines)]
