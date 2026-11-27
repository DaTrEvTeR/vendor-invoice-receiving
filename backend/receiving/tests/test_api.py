"""The HTTP contract the frontend relies on."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from .conftest import sample_bytes


@pytest.fixture
def api(seeded) -> APIClient:
    """A client against a seeded database."""
    return APIClient()


def upload(api: APIClient, name: str, data: bytes | None = None):
    """POST a file the way the upload form does."""
    file = SimpleUploadedFile(name, sample_bytes(name) if data is None else data)
    return api.post("/api/invoices/", {"file": file}, format="multipart")


def test_upload_creates_once_and_returns_the_same_invoice_for_the_same_bytes(api):
    """201 with the review data, then 200 and `already_uploaded` for an identical file."""
    first = upload(api, "inv_01.json")
    assert first.status_code == 201
    assert (first.data["status"], first.data["already_uploaded"]) == ("received", False)
    again = upload(api, "inv_01.json")
    assert again.status_code == 200
    assert (again.data["id"], again.data["already_uploaded"]) == (first.data["id"], True)
    assert len(api.get("/api/invoices/").data) == 1


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("inv_01.txt", b"{}", "Only .csv, .json files are accepted."),
        ("inv_01.json", b"", "The file is empty."),
    ],
)
def test_upload_refuses_what_cannot_be_an_invoice(api, name, data, message):
    """Wrong extension or empty: 400 and nothing stored."""
    response = api.post("/api/invoices/", {"file": SimpleUploadedFile(name, data)}, format="multipart")
    assert (response.status_code, response.data["detail"]) == (400, message)
    assert api.get("/api/invoices/").data == []


def test_upload_refuses_a_file_over_the_size_limit(api, settings):
    """The size is checked before the file is read."""
    settings.MAX_UPLOAD_BYTES = 100
    response = upload(api, "inv_01.json")
    assert response.status_code == 400 and "larger than 100 bytes" in response.data["detail"]


def test_upload_needs_a_file_field(api):
    """A request without the file is a validation error."""
    assert api.post("/api/invoices/", {}, format="multipart").status_code == 400


def test_review_data_shows_the_vendor_values_next_to_the_interpretation(api):
    """inv_10: the raw '25 DWT' and the interpreted grams, with exact decimal strings."""
    data = upload(api, "inv_10.json").data
    first = data["lines"][0]
    assert (first["raw"]["quantity"], first["raw"]["uom"]) == ("25", "DWT")
    assert (first["quantity"], first["product_unit"], first["amount"]) == ("38.879346", "gram", "1866.25")
    assert first["po_line"]["remaining"] == "40"
    assert data["actions"] == {
        "edit": True,
        "approve": True,
        "needs_confirmation": True,
        "reject": True,
        "close": False,
    }
    assert {issue["code"] for issue in data["issues"]} == {"PRICE_MISMATCH", "SHORT_SHIPMENT", "UNIT_CONVERTED"}


def test_line_edit_validates_input_and_revalidates_the_invoice(api):
    """A value outside the API's plain notation is refused; a valid edit refreshes issues and audit."""
    invoice = upload(api, "inv_09.json").data
    line_id = invoice["lines"][0]["id"]
    url = f"/api/invoices/{invoice['id']}/lines/{line_id}/"
    assert api.patch(url, {"quantity": "1.125,00"}, format="json").status_code == 400
    assert api.patch(url, {}, format="json").status_code == 400  # nothing to change

    response = api.patch(url, {"quantity": "2"}, format="json")
    assert response.status_code == 200
    assert response.data["lines"][0]["edited_fields"] == ["quantity"]
    assert response.data["issue_counts"]["hard"] == 0
    assert response.data["audit_events"][-1]["payload"]["changed"] == {"quantity": {"from": "3", "to": "2"}}


def test_approve_needs_explicit_acceptance_of_discrepancies(api):
    """409 lists the discrepancies; accepting them receives; a second approve is refused."""
    invoice = upload(api, "inv_08.json").data
    url = f"/api/invoices/{invoice['id']}/approve/"
    refused = api.post(url, {}, format="json")
    assert refused.status_code == 409
    assert refused.data["code"] == "NeedsConfirmation"
    assert [issue["code"] for issue in refused.data["issues"]] == ["PRICE_MISMATCH"]

    accepted = api.post(url, {"accept_discrepancies": True}, format="json")
    assert (accepted.status_code, accepted.data["status"]) == (200, "received")
    assert api.post(url, {"accept_discrepancies": True}, format="json").data["code"] == "InvalidTransition"
    movements = api.get("/api/stock-movements/").data
    assert (movements[0]["sku"], movements[0]["total_cost"], movements[0]["invoice"]["id"]) == (
        "DIA-5003",
        "4536.00",
        invoice["id"],
    )


def test_decisions_must_be_sent_as_json(api):
    """A form post or an empty post (what another website can send without a preflight) decides nothing."""
    invoice = upload(api, "inv_08.json").data
    url = f"/api/invoices/{invoice['id']}"
    assert api.post(f"{url}/approve/", {"accept_discrepancies": "true"}).status_code == 415  # multipart
    assert api.generic("POST", f"{url}/reject/").status_code == 415  # no body
    assert api.get(f"{url}/").data["status"] == "needs_review"


def test_blocking_issues_and_wrong_actions_are_conflicts(api):
    """Hard issues block approve; close is only for memos; both answer 409 with a reason."""
    invoice = upload(api, "inv_09.json").data
    blocked = api.post(f"/api/invoices/{invoice['id']}/approve/", {"accept_discrepancies": True}, format="json")
    assert (blocked.status_code, blocked.data["code"]) == (409, "CannotApprove")
    assert blocked.data["issues"][0]["line_no"] == 1
    assert api.post(f"/api/invoices/{invoice['id']}/close/", {}, format="json").status_code == 409


def test_reject_and_close_record_the_optional_reason(api):
    """Reject an invoice, close a memo; the reason ends up in the notes and the audit trail."""
    invoice = upload(api, "inv_02.json").data
    rejected = api.post(f"/api/invoices/{invoice['id']}/reject/", {"reason": "Wrong totals."}, format="json")
    assert (rejected.data["status"], rejected.data["status_notes"]) == ("rejected", "Rejected by staff: Wrong totals.")
    memo = upload(api, "inv_05.json").data
    assert memo["actions"]["close"] is True
    closed = api.post(f"/api/invoices/{memo['id']}/close/", {}, format="json")
    assert (closed.data["status"], closed.data["audit_events"][-1]["payload"]) == (
        "closed_no_receipt",
        {"reason": ""},
    )


def test_header_edit_with_an_unknown_po_is_a_validation_error(api):
    """Related values must exist."""
    invoice = upload(api, "inv_06.csv").data
    response = api.patch(f"/api/invoices/{invoice['id']}/", {"purchase_order": "PO-NOPE"}, format="json")
    assert response.status_code == 400 and "purchase_order" in response.data


def test_unknown_invoice_or_line_is_404(api):
    """Missing rows are 404, also inside a use case."""
    assert api.get("/api/invoices/999/").status_code == 404
    invoice = upload(api, "inv_06.csv").data
    assert api.patch(f"/api/invoices/{invoice['id']}/lines/999/", {"amount": "1"}, format="json").status_code == 404


def test_health_answers_without_touching_data(client):
    """The container healthcheck endpoint needs no database."""
    response = client.get("/api/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_reference_endpoints_return_exact_strings_with_or_without_the_slash(api):
    """Stock, POs and vendors for the screens; the trailing slash is optional."""
    products = {p["sku"]: p for p in api.get("/api/products").data}
    assert len(products) == 40 and products["MTL-6001"]["on_hand"] == "120"
    pos = {po["po_number"]: po for po in api.get("/api/purchase-orders/").data}
    assert pos["PO-2026-045"]["lines"][0]["unit_cost"] == "48.00"
    assert [v["vendor_id"] for v in api.get("/api/vendors").data][:2] == ["V01", "V02"]
