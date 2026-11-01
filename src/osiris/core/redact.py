"""Redaction des secrets avant stockage.

La redaction precede le hash : le hash porte sur la version **stockee**
(redigee), pas sur le contenu d'origine. La preuve d'integrite porte donc
sur ce qu'OSIRIS a reellement conserve.
"""

from __future__ import annotations

import re

#: (nom, motif) — tous en mode multi-ligne.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN[A-Z ]*PRIVATE KEY-----.*?-----END[A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    ("url_credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+@")),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|"
            r"refresh[_-]?token|client[_-]?secret|private[_-]?key)\b"
            r"(\s*[:=]\s*)(\"[^\"]{3,}\"|'[^']{3,}'|[^\s,;]{3,})"
        ),
    ),
    (
        "authorization_header",
        re.compile(r"(?i)\b(authorization|proxy-authorization)\b(\s*[:=]\s*)(\S+)"),
    ),
)

#: Masque applique au contenu secret detecte.
_MASK = "[REDACTED:{kind}]"


def redact_text(text: str) -> tuple[str, int]:
    """Redige les secrets d'un texte.

    Returns:
        (texte_redige, nombre_de_detections)
    """
    if not text:
        return text, 0
    out = text
    count = 0
    for kind, pattern in _PATTERNS:

        def _sub(match: re.Match[str], _kind: str = kind) -> str:
            nonlocal count
            count += 1
            if _kind == "assigned_secret":
                return f"{match.group(1)}{match.group(2)}{_MASK.format(kind=_kind)}"
            if _kind == "authorization_header":
                return f"{match.group(1)}{match.group(2)}{_MASK.format(kind=_kind)}"
            if _kind == "url_credentials":
                return _MASK.format(kind=_kind)
            return _MASK.format(kind=_kind)

        out = pattern.sub(_sub, out)
    return out, count


def redact_chunk(chunks: list[str]) -> tuple[list[str], int]:
    """Redige une liste de chunks."""
    total = 0
    out = []
    for chunk in chunks:
        red, n = redact_text(chunk)
        out.append(red)
        total += n
    return out, total
