"""Parser registry (R9): every file format registers a parser under a string key.

A parser is chosen by its detector, which inspects the file's structure. Detectors run
in priority order (highest first, then by key, so the choice is deterministic) and the
first one that recognizes the file wins.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from .types import ParsedInvoice, SourceFile

Detector = Callable[[SourceFile], bool]
Parser = Callable[[SourceFile], ParsedInvoice]


@dataclass(frozen=True)
class Registered:
    """A parser together with the detector that recognizes its format."""

    key: str
    detect: Detector
    priority: int
    parse: Parser


_PARSERS: dict[str, Registered] = {}


def register(key: str, detect: Detector, priority: int = 0) -> Callable[[Parser], Parser]:
    """Decorator: register `fn` as the parser for files that `detect` recognizes."""

    def decorator(fn: Parser) -> Parser:
        """Add `fn` to the registry and return it unchanged."""
        if key in _PARSERS:
            raise ImproperlyConfigured(f"parser {key!r} is registered twice")
        _PARSERS[key] = Registered(key, detect, priority, fn)
        return fn

    return decorator


def candidates() -> list[Registered]:
    """Registered parsers in the order they are tried."""
    return sorted(_PARSERS.values(), key=lambda p: (-p.priority, p.key))
