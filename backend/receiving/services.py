"""Use cases: ingest a file, edit the interpretation, approve, reject, close.

The automatic path and a person's Approve button call the same `approve()`, so every
invariant is enforced in one place. Each use case runs in one transaction and locks
the rows it changes; a failure anywhere rolls the whole step back.
"""

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .decimals import plain
from .extraction import ExtractionError, extract
from .extraction.types import DocumentType, LineType, ParsedInvoice, SourceFile, to_json_value
from .matching import interpret, interpret_line
from .models import AuditEvent, Invoice, InvoiceLine, Issue, POLine, Product, PurchaseOrder, SerialUnit, StockMovement
from .validation import Finding, by_severity, validate

log = logging.getLogger("receiving.services")

Status = Invoice.Status
Kind = Issue.Kind
SYSTEM = AuditEvent.SYSTEM
ALLOWED_EXTENSIONS = frozenset({".json", ".csv"})


class ServiceError(Exception):
    """A request that the current state does not allow."""


class UploadRejected(ServiceError):
    """The upload is not an invoice file at all (extension, size), so nothing is stored."""


class InvalidTransition(ServiceError):
    """The invoice's status does not allow this action (for example, approving twice)."""


class FindingsError(ServiceError):
    """An action blocked by validation findings, which are attached."""

    def __init__(self, message: str, findings: list[Finding]):
        super().__init__(message)
        self.findings = findings


class CannotApprove(FindingsError):
    """Hard or terminal issues remain: the interpretation must be fixed, or the invoice rejected."""


class NeedsConfirmation(FindingsError):
    """Only discrepancies remain: approving requires accepting them explicitly."""


@dataclass(frozen=True)
class IngestResult:
    """The stored invoice, and whether this upload created it."""

    invoice: Invoice
    created: bool


# --- Ingest ---------------------------------------------------------------------


def check_upload(filename: str, data: bytes) -> None:
    """Refuse uploads that cannot be invoice files before anything is stored."""
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"Only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are accepted.")
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise UploadRejected(f"The file is larger than {settings.MAX_UPLOAD_BYTES} bytes.")


def same_file(sha256: str) -> Invoice | None:
    """An earlier upload of the exact same bytes that still stands (M2).

    A rejected upload does not count, and neither does a duplicate whose original has since
    been rejected: uploading that file again processes it as the invoice it now is.
    """
    uploads = Invoice.objects.filter(file_sha256=sha256).exclude(status=Status.REJECTED)
    for invoice in uploads.select_related("duplicate_of").order_by("id"):
        if invoice.status == Status.DUPLICATE and invoice.duplicate_of.status == Status.REJECTED:
            continue
        return invoice
    return None


def live_duplicate_of(invoice: Invoice) -> Invoice | None:
    """A live invoice with the same vendor and number (M2). Rejected and duplicates do not count."""
    number = Invoice.normalize_number(invoice.invoice_number)
    if invoice.vendor_id is None or not number:
        return None
    return (
        Invoice.objects.filter(vendor_id=invoice.vendor_id, invoice_number_norm=number)
        .exclude(status__in=[Status.DUPLICATE, Status.REJECTED])
        .exclude(pk=invoice.pk)
        .order_by("id")
        .first()
    )


def ingest_file(filename: str, data: bytes) -> IngestResult:
    """Extract, stage, interpret, validate and decide one uploaded file."""
    name = Path(filename).name  # never used as a path: the content is stored in the database
    check_upload(name, data)
    src = SourceFile.from_bytes(name, data)
    existing = same_file(src.sha256)
    if existing is not None:
        log.info("already uploaded file=%s invoice=%s", name, existing.pk)
        return IngestResult(existing, created=False)

    try:
        parsed, error = extract(src), None
    except ExtractionError as exc:
        parsed, error = None, exc

    for attempt in (1, 2):
        try:
            with transaction.atomic():  # IMMEDIATE: holds the write lock, so concurrent uploads queue here
                existing = same_file(src.sha256)
                if existing is not None:  # the same bytes were stored while this file was being read
                    return IngestResult(existing, created=False)
                invoice = stage(src, parsed, error)
                decide(invoice)
            break
        except IntegrityError:
            # A concurrent upload of the same invoice committed first; the retry sees it
            # and stores this one as its duplicate.
            if attempt == 2:
                raise
    invoice.refresh_from_db()
    log.info("ingested file=%s invoice=%s status=%s", name, invoice.pk, invoice.status)
    return IngestResult(invoice, created=True)


def stage(src: SourceFile, parsed: ParsedInvoice | None, error: ExtractionError | None) -> Invoice:
    """Store the raw data and the first interpretation. Nothing touches stock here."""
    invoice = Invoice(
        source_filename=src.name,
        file_sha256=src.sha256,
        raw_content=src.text,
        raw_header=parsed.raw_header() if parsed else {},
        parsed_header=parsed.parsed_header() if parsed else {},
        parser_key=parsed.parser_key if parsed else "",
    )
    lines = [
        InvoiceLine(line_no=p.line_no, raw=p.raw_dict(), parsed=p.parsed_dict(), line_type=p.line_type)
        for p in (parsed.lines if parsed else ())
    ]
    interpret(invoice, lines)

    original = live_duplicate_of(invoice)
    if original is not None:
        invoice.status = Status.DUPLICATE
        invoice.duplicate_of = original
        invoice.decided_at = timezone.now()
        invoice.status_notes = (
            f"Duplicate of {original.source_filename}: same vendor ({invoice.vendor_id}) and invoice number "
            f"({invoice.invoice_number}), already {original.status}. Nothing was received."
        )
    invoice.save()
    for line in lines:
        line.invoice = invoice
    InvoiceLine.objects.bulk_create(lines)
    AuditEvent.objects.create(
        invoice=invoice,
        action=AuditEvent.Action.UPLOADED,
        actor=SYSTEM,
        payload={
            "file": src.name,
            "sha256": src.sha256,
            "parser_key": invoice.parser_key,
            "extraction_error": {"code": error.code, "message": str(error)} if error else None,
            "duplicate_of": original.pk if original else None,
        },
    )
    return invoice


def decide(invoice: Invoice) -> None:
    """Receive automatically only when nothing needs a person; otherwise queue for review."""
    if invoice.status == Status.DUPLICATE:
        return
    findings = refresh_issues(invoice)
    if any(f.kind != Kind.INFO for f in findings):
        invoice.status = Status.NEEDS_REVIEW
        invoice.status_notes = review_notes(findings)
        invoice.save(update_fields=["status", "status_notes"])
    else:
        approve(invoice.pk, actor=SYSTEM)


def refresh_issues(invoice: Invoice) -> list[Finding]:
    """Validate and replace the invoice's stored issues."""
    findings = validate(invoice)
    Issue.objects.filter(invoice=invoice).delete()
    Issue.objects.bulk_create(
        Issue(invoice=invoice, line=f.line, code=f.code, kind=f.kind, message=f.message) for f in findings
    )
    return findings


# --- Review edits (R5) ----------------------------------------------------------

# What a person may correct. The raw and parsed values never change.
HEADER_FIELDS = (
    "document_type",
    "invoice_number",
    "invoice_date",
    "vendor",
    "purchase_order",
    "currency",
    "subtotal",
    "tax",
    "total",
)
LINE_FIELDS = ("line_type", "product", "quantity", "amount", "serials")
# Only merchandise has a product, a quantity in stock units and certificates.
PRODUCT_ONLY_FIELDS = ("product", "quantity", "serials")
# Line fields the interpretation derives; saved after a header edit re-derives them.
DERIVED_LINE_FIELDS = ("product", "po_line", "quantity", "amount", "serials", "edited_fields")


def lock_for_review(invoice_id: int) -> Invoice:
    """The invoice, locked, if it is still waiting for a person and has data to correct."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.status != Status.NEEDS_REVIEW:
        raise InvalidTransition(f"Invoice {invoice.pk} is {invoice.status}; only invoices in review can be edited.")
    if not invoice.raw_header:
        raise InvalidTransition("Nothing could be read from this file, so there is nothing to correct; reject it.")
    return invoice


def apply_edits(
    obj: Invoice | InvoiceLine, changes: Mapping[str, Any], revert: Collection[str], allowed: tuple[str, ...]
) -> None:
    """Set the values a person entered and mark them edited; reverted fields go back to the system's value."""
    unknown = sorted((set(changes) | set(revert)) - set(allowed))
    if unknown:
        raise ServiceError(f"These fields cannot be edited: {', '.join(unknown)}.")
    both = sorted(set(changes) & set(revert))
    if both:
        raise ServiceError(f"A field cannot be both set and reverted: {', '.join(both)}.")
    edited = [name for name in obj.edited_fields if name not in revert]
    for name, value in changes.items():
        setattr(obj, name, value)
        if name not in edited:
            edited.append(name)
    obj.edited_fields = edited


def snapshot(obj: Invoice | InvoiceLine, fields: tuple[str, ...]) -> dict[str, Any]:
    """Interpretation values in JSON form, for the audit trail. Equal numbers give equal text."""
    values = {}
    for name in fields:
        value = getattr(obj, name)
        if isinstance(value, models.Model):
            value = value.pk
        elif isinstance(value, Decimal):
            value = plain(value)  # 4350.000000 from the database equals 4350.00 from the file
        values[name] = to_json_value(value)
    return values


@transaction.atomic
def edit_invoice(invoice_id: int, actor: str, changes: Mapping[str, Any], revert: Collection[str] = ()) -> Invoice:
    """Correct the header interpretation. Everything derived from it is recomputed, then validated again."""
    invoice = lock_for_review(invoice_id)
    lines = list(invoice.lines.order_by("line_no"))
    before = snapshot(invoice, HEADER_FIELDS)
    apply_edits(invoice, changes, revert, HEADER_FIELDS)
    interpret(invoice, lines)  # a new PO can change the vendor, the SKUs and the PO lines
    original = live_duplicate_of(invoice)
    if original is not None:
        raise ServiceError(
            f"{original.source_filename} already has vendor {invoice.vendor_id} and invoice number "
            f"{invoice.invoice_number} ({original.status}); if this is the same invoice, reject this one."
        )
    invoice.save()
    InvoiceLine.objects.bulk_update(lines, DERIVED_LINE_FIELDS)
    return after_edit(invoice, actor, None, before, snapshot(invoice, HEADER_FIELDS), revert)


@transaction.atomic
def edit_line(
    invoice_id: int, line_id: int, actor: str, changes: Mapping[str, Any], revert: Collection[str] = ()
) -> Invoice:
    """Correct one line's interpretation: line type, SKU, quantity in the SKU's unit, amount, certificates."""
    invoice = lock_for_review(invoice_id)
    line = invoice.lines.get(pk=line_id)
    before = snapshot(line, LINE_FIELDS)
    apply_edits(line, changes, revert, LINE_FIELDS)
    interpret_line(invoice, line)  # also restores the parser's line type when that edit is reverted
    if line.line_type != LineType.PRODUCT:
        # A charge or summary row has no product of its own; earlier product edits no longer apply.
        line.edited_fields = [name for name in line.edited_fields if name not in PRODUCT_ONLY_FIELDS]
    line.save()
    return after_edit(invoice, actor, line, before, snapshot(line, LINE_FIELDS), revert)


def after_edit(
    invoice: Invoice,
    actor: str,
    line: InvoiceLine | None,
    before: dict[str, Any],
    after: dict[str, Any],
    revert: Collection[str],
) -> Invoice:
    """Validate again, refresh the notes and record who changed what. The invoice stays in review."""
    findings = refresh_issues(invoice)
    invoice.status_notes = review_notes(findings)
    invoice.save(update_fields=["status_notes"])
    changed = {name: {"from": before[name], "to": value} for name, value in after.items() if before[name] != value}
    AuditEvent.objects.create(
        invoice=invoice,
        action=AuditEvent.Action.EDITED,
        actor=actor,
        payload={"line": line.line_no if line else None, "changed": changed, "reverted": sorted(revert)},
    )
    log.info("edited invoice=%s line=%s actor=%s", invoice.pk, line.line_no if line else "-", actor)
    return invoice


# --- Decisions ------------------------------------------------------------------


def approve(invoice_id: int, actor: str, accept_discrepancies: bool = False) -> Invoice:
    """Receive the whole invoice into stock (R1), after validating it again on current data.

    A refused approval rolls back, but the issues found by the new validation are saved
    anyway, so the review screen shows the current reasons (for example, a discrepancy
    that appeared because another invoice received the same PO line meanwhile).
    """
    try:
        return receive(invoice_id, actor, accept_discrepancies)
    except FindingsError:
        save_current_issues(invoice_id)
        raise


@transaction.atomic
def save_current_issues(invoice_id: int) -> None:
    """Store the result of validating an invoice in review again, with matching notes."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.status == Status.NEEDS_REVIEW:
        invoice.status_notes = review_notes(refresh_issues(invoice))
        invoice.save(update_fields=["status_notes"])


@transaction.atomic
def receive(invoice_id: int, actor: str, accept_discrepancies: bool) -> Invoice:
    """The approval itself: one transaction that receives everything or nothing."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.status not in (Status.PENDING, Status.NEEDS_REVIEW):
        raise InvalidTransition(f"Invoice {invoice.pk} is {invoice.status}; only invoices in review can be approved.")
    findings = refresh_issues(invoice)
    blocking = [f for f in findings if f.kind in (Kind.TERMINAL, Kind.HARD)]
    if blocking:
        raise CannotApprove("Issues must be fixed before approval.", by_severity(blocking))
    discrepancies = [f for f in findings if f.kind == Kind.SOFT]
    if discrepancies and not accept_discrepancies:
        raise NeedsConfirmation("Approving means accepting these discrepancies.", discrepancies)

    receive_lines(invoice)
    invoice.status = Status.RECEIVED
    invoice.decided_at = timezone.now()
    invoice.status_notes = receipt_notes(invoice, actor, findings)
    invoice.save(update_fields=["status", "decided_at", "status_notes"])
    AuditEvent.objects.create(
        invoice=invoice,
        action=AuditEvent.Action.APPROVED,
        actor=actor,
        payload={"accepted_discrepancies": [{"code": f.code, "message": f.message} for f in discrepancies]},
    )
    log.info("received invoice=%s actor=%s", invoice.pk, actor)
    return invoice


def receive_lines(invoice: Invoice) -> None:
    """Write the ledger, stock, PO progress and certificates. Rows are locked before changing."""
    touched_pos: set[str] = set()
    for line in invoice.lines.filter(line_type=LineType.PRODUCT).order_by("line_no"):
        product = Product.objects.select_for_update().get(pk=line.product_id)
        product.on_hand += line.quantity  # Decimal arithmetic in Python, not REAL arithmetic in SQLite
        product.save(update_fields=["on_hand"])
        movement = StockMovement.objects.create(
            kind=StockMovement.Kind.RECEIPT,
            product=product,
            quantity=line.quantity,
            total_cost=line.amount,
            currency=invoice.currency,
            invoice_line=line,
            po_line_id=line.po_line_id,
        )
        if line.po_line_id is not None:
            po_line = POLine.objects.select_for_update().get(pk=line.po_line_id)
            po_line.qty_received += line.quantity
            po_line.save(update_fields=["qty_received"])
            touched_pos.add(po_line.purchase_order_id)
        if product.serialized:
            # serial_number is unique: a certificate received twice aborts the whole approval.
            SerialUnit.objects.bulk_create(
                SerialUnit(product=product, serial_number=s, stock_movement=movement) for s in line.serials
            )
    for po_number in sorted(touched_pos):
        refresh_po_status(po_number)


def refresh_po_status(po_number: str) -> None:
    """Derive a PO's status from its lines."""
    po = PurchaseOrder.objects.select_for_update().get(pk=po_number)
    lines = list(po.lines.all())
    if all(line.qty_received >= line.qty_ordered for line in lines):
        po.status = PurchaseOrder.Status.RECEIVED
    elif any(line.qty_received > 0 for line in lines):
        po.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
    else:
        po.status = PurchaseOrder.Status.OPEN
    po.save(update_fields=["status"])


@transaction.atomic
def reject(invoice_id: int, actor: str, reason: str = "") -> Invoice:
    """Refuse the whole invoice. Stock is untouched; the raw file stays on record. The reason is optional."""
    return _close_review(invoice_id, actor, reason, Status.REJECTED, AuditEvent.Action.REJECTED, "Rejected")


@transaction.atomic
def close(invoice_id: int, actor: str, reason: str = "") -> Invoice:
    """Close a MEMO or CREDIT_MEMO without any stock movement (R6). The reason is optional."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.document_type not in (DocumentType.MEMO, DocumentType.CREDIT_MEMO):
        raise InvalidTransition("Only a MEMO or CREDIT_MEMO can be closed without receipt; reject an invoice instead.")
    return _close_review(
        invoice_id, actor, reason, Status.CLOSED_NO_RECEIPT, AuditEvent.Action.CLOSED, "Closed without receipt"
    )


def _close_review(invoice_id: int, actor: str, reason: str, status: str, action: str, verb: str) -> Invoice:
    """Shared end of review without receipt."""
    reason = reason.strip()
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.status != Status.NEEDS_REVIEW:
        raise InvalidTransition(
            f"Invoice {invoice.pk} is {invoice.status}; only invoices in review can be {verb.lower()}."
        )
    invoice.status = status
    invoice.decided_at = timezone.now()
    invoice.status_notes = f"{verb} by {actor}" + (f": {reason}" if reason else ".")
    invoice.save(update_fields=["status", "decided_at", "status_notes"])
    AuditEvent.objects.create(invoice=invoice, action=action, actor=actor, payload={"reason": reason})
    return invoice


# --- Notes ----------------------------------------------------------------------


def review_notes(findings: list[Finding]) -> str:
    """Why the invoice waits for a person: blocking findings first, then context."""
    head = "Needs review." if any(f.kind != Kind.INFO for f in findings) else "Ready for approval: no open issues."
    return " ".join([head, *(f.message for f in by_severity(findings))])


def receipt_notes(invoice: Invoice, actor: str, findings: list[Finding]) -> str:
    """What was received and on what grounds."""
    po = invoice.purchase_order_id or "no purchase order"
    if actor == SYSTEM:
        head = f"Received automatically against {po}: no discrepancies."
    else:
        accepted = [f.message for f in findings if f.kind == Kind.SOFT]
        head = f"Approved by {actor} against {po}." + (
            f" Accepted discrepancies: {' '.join(accepted)}" if accepted else ""
        )
    context = [f.message for f in findings if f.kind == Kind.INFO]
    return " ".join([head, *context])
