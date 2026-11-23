"""Bounded, dependency-free sensitivity hints; never an external-send grant.

Only fixed booleans leave this detector. Origin/privacy/permission remain Guard-owned.
"""
import re

MAX_SCAN_CHARS = 262_144

_CREDENTIAL = re.compile(
    r"(?m)-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----"
    r"|(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9_]{20,}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,}(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])glpat-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_])glrt-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_-])xox[baprs]-[A-Za-z0-9-]{16,}(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_PERSONAL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z])"
    r"|(?<![0-9])(?:\+81[- ]?[789]0|0[789]0)[- ]?[0-9]{4}[- ]?[0-9]{4}(?![0-9])"
)


def contains_sensitive_value(text: str) -> bool:
    """True also means unknown/too large; never interpret False as public consent."""
    if not isinstance(text, str) or len(text) > MAX_SCAN_CHARS:
        return True
    return bool(_CREDENTIAL.search(text) or _PERSONAL.search(text))
