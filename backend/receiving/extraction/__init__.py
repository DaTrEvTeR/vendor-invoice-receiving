"""Extract: turn an uploaded file into a ParsedInvoice using the parser registry (R9).

A file that no parser recognizes, or that a parser cannot read, raises
ExtractionError and is logged at ERROR level with a stable code, so a changed
vendor format is an explicit alert rather than silently wrong data. Content of the
file is never logged, only its name, hash and the structural difference.
"""

import logging
from dataclasses import replace

from . import parsers  # noqa: F401  (registers the built-in parsers)
from .layouts import FormatError
from .registry import candidates
from .types import ParsedInvoice, SourceFile

log = logging.getLogger("receiving.extraction")

NO_PARSER = "EXTRACTION_NO_PARSER"
PARSER_FAILED = "EXTRACTION_FAILED"
DECODE_FAILED = "EXTRACTION_DECODE_FAILED"


class ExtractionError(Exception):
    """The file could not be read. `code` is the alert code that was logged."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def explain_all(src: SourceFile) -> str:
    """How the file differs from every registered format of the same kind."""
    diffs = []
    for parser in candidates():
        explain = getattr(parser.detect, "explain", None)
        text = explain(src) if explain else None
        if text is not None:
            diffs.append(f"{parser.key}: {text}")
    return "; ".join(diffs)


def extract(src: SourceFile) -> ParsedInvoice:
    """Pick the first parser whose detector recognizes the file and parse it."""
    short_hash = src.sha256[:12]
    if not src.decoded:
        log.error("%s file=%s sha256=%s reason=not valid UTF-8", DECODE_FAILED, src.name, short_hash)
        raise ExtractionError(DECODE_FAILED, "The file is not valid UTF-8 text.")

    for parser in candidates():
        if not parser.detect(src):
            continue
        try:
            parsed = replace(parser.parse(src), parser_key=parser.key)
        except FormatError as exc:
            log.error("%s file=%s sha256=%s parser=%s reason=%s", PARSER_FAILED, src.name, short_hash, parser.key, exc)
            raise ExtractionError(PARSER_FAILED, f"Recognized as {parser.key} but could not be read: {exc}.") from exc
        log.info(
            "extracted file=%s parser=%s lines=%d unparsed_values=%d",
            src.name,
            parser.key,
            len(parsed.lines),
            parsed.unparsed_count(),
        )
        return parsed

    log.error("%s file=%s sha256=%s diff=[%s]", NO_PARSER, src.name, short_hash, explain_all(src))
    raise ExtractionError(NO_PARSER, "The file format is not recognized by any registered parser.")
