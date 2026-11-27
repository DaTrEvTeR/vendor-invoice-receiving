# Vendor Invoice Receiving

A Django + Next.js app that loads vendor invoice files (JSON or CSV), matches every line to the
store's catalog, the vendor item-code map and open purchase orders, and then does one of two things:

- receives the invoice into inventory automatically, when every value is exact and unambiguous;
- or holds it for staff review, with the reasons spelled out.

On the review screen a person sees the vendor's original values next to the system's interpretation,
corrects the interpretation where needed, and approves, rejects or closes the document.

The owner's rule drives every decision: **wrong numbers must never silently reach inventory.** Matching is
exact only (no fuzzy matching, no tolerances), and anything uncertain goes to a person.

The reasoning behind the design is in [DECISIONS.md](DECISIONS.md). The original take-home brief is in
the first commit of this repository.

## Quick start

Requirements: Docker with Compose, and `make`. It works on Linux (including rootless Docker, Podman and
SELinux hosts), on macOS and on Windows through WSL. The backend container runs as the owner of the
checkout, so the files it writes (`backend/db.sqlite3`, `results/outcomes.json`) stay yours.

```sh
make run
```

`make run` creates `.env` from `.env.example`, builds both images, applies migrations, loads `data/` into
the database and starts the app.

| What                     | Where                                                                       |
| ------------------------ | --------------------------------------------------------------------------- |
| Web UI                   | http://localhost:3000                                                       |
| REST API                 | http://localhost:8000/api/invoices/ (the UI reaches it through its own `/api` proxy) |
| Django admin (view-only) | http://localhost:8000/admin/ (create a user first; see below)               |

Both ports are published on `127.0.0.1` only, because the API has no login yet. If port 3000 or 8000
is already taken, change `FRONTEND_PORT` or `BACKEND_PORT` in `.env`.

## Commands

| Command        | What it does                                                                           |
| -------------- | -------------------------------------------------------------------------------------- |
| `make run`     | One command from a clean clone: build, migrate, load `data/`, start.                   |
| `make up`      | `docker compose up --build`.                                                           |
| `make migrate` | Apply migrations. This is an explicit step; containers never migrate on start-up.      |
| `make seed`    | Load `data/` into an empty database. Does nothing if data is already loaded.           |
| `make reset`   | Wipe the dev database (invoices, stock movements, PO progress) and reload `data/`.     |
| `make test`    | Run the backend test suite in the container.                                           |
| `make outcomes` | Regenerate `results/outcomes.json` (see below).                                      |

Other management commands run with `docker compose run --rm backend python manage.py ...`. Prefer
`run` to `exec`: `docker compose exec` skips the entrypoint and would run as root.

- `python manage.py ingest FILE...` submits files from the command line through the same pipeline as
  the API.
- `python manage.py createsuperuser` creates a user for the Django admin.

## The results file

```sh
make outcomes
```

The command builds `results/outcomes.json` on a **fresh temporary database**, so it never touches the
dev database. It applies migrations, loads `data/` as shipped, and submits the 12 sample invoices in
filename order with no human review. Then it writes the final state:

- every invoice's status, notes and received lines;
- on-hand stock for all 40 SKUs;
- `qty_received` for all 21 PO lines.

Running it twice gives byte-identical output.

On the samples the run ends with **3 received, 1 duplicate and 8 needing review**:

- **Received:** `inv_01` and `inv_04` (a partial shipment explained exactly by the vendor's backorder),
  and `inv_12` (Lucentara's Italian CSV).
- **Duplicate:** `inv_03` (the CSV copy of `inv_01`).
- **Needs review:** the other 8, each for the reasons written in its notes.

## Using the app

1. **Invoices** (`/`): load a file. A clean invoice is received right away; otherwise the list shows why
   it waits (blocking issues, discrepancies).
2. **Review** (`/invoices/<id>`):
   - The header and every line show the text from the file next to the system's interpretation. Fields a
     person changed are highlighted and can be reverted.
   - Each edit re-runs matching and validation.
   - **Approve** is available once nothing blocks it. If discrepancies remain, the person must tick
     "I accept the discrepancies".
   - **Reject** works for any invoice under review. **Close without receipt** is for MEMO and
     CREDIT_MEMO documents. The reason is optional.
   - The original file and the audit trail are at the bottom of the page.
3. **Inventory** (`/inventory`) and **Purchase orders** (`/purchase-orders`) show on-hand stock, the
   receipt ledger, and ordered, received and open quantities.

Things to try on the samples:

- `inv_06`: choose the SKU for the two unmapped vendor codes, then approve.
- `inv_09`: add the third diamond's certificate number, then approve.
- `inv_10`: review the price and short-shipment discrepancies; approve with acceptance, or reject.

## API

| Method and path                            | Purpose                                                                 |
| ------------------------------------------ | ----------------------------------------------------------------------- |
| `POST /api/invoices/`                      | Upload (multipart field `file`): 201 if new, 200 if the same bytes were already uploaded. |
| `GET /api/invoices/`                       | List, with open issue counts.                                           |
| `GET /api/invoices/{id}/`                  | Everything the review screen shows.                                     |
| `PATCH /api/invoices/{id}/`                | Edit the header interpretation; `revert: [fields]` undoes edits.        |
| `PATCH /api/invoices/{id}/lines/{line_id}/` | Edit a line: type, SKU, quantity in the SKU's unit, amount, certificates. |
| `POST /api/invoices/{id}/approve/`         | `{"accept_discrepancies": bool}`.                                       |
| `POST /api/invoices/{id}/reject/`          | `{"reason": "..."}`; the reason is optional.                            |
| `POST /api/invoices/{id}/close/`           | MEMO and CREDIT_MEMO only.                                              |
| `GET /api/products/`                       | Catalog with on-hand stock.                                             |
| `GET /api/purchase-orders/`                | POs with ordered, received and open quantities per line.                |
| `GET /api/stock-movements/`                | The stock ledger, newest first.                                         |
| `GET /api/vendors/`                        | Vendors.                                                                |
| `GET /api/health`                          | Liveness for the container healthcheck: the frontend starts only once it answers. |

Decimals are exact strings, never floats.

Errors:

- `400`: invalid input or a refused upload.
- `409`: the invoice's state does not allow the action. The response body gives the reason and, for
  approve, the issues that block it.
- `415`: approve, reject and close accept only a JSON body. A JSON request from another website needs
  a CORS preflight, which this API never grants, so such a site cannot make these decisions.

**The API has no authentication.** This is dev-only; every action is recorded as `staff` (see
DECISIONS.md, Security).

## Project layout

```
backend/                  Django 5.2 + DRF, SQLite
  config/                 settings (all from environment variables), urls
  receiving/
    extraction/           Extract: parser registry, one declarative layout per file format
    matching.py           Transform: vendor, SKU, unit conversion, PO line
    validation.py         Validate: every reason an invoice needs a person
    services.py           Use cases: ingest, edit, approve, reject, close
    api/                  DRF serializers and views (HTTP only, no business logic)
    outcomes.py           results/outcomes.json
    tests/
frontend/                 Next.js 16 (App Router, TypeScript), no UI library
data/                     reference data and sample invoices, never modified
results/outcomes.json
```

## Development without Docker

```sh
# Backend (Python 3.13): uses backend/db.sqlite3, data/ and results/ by default
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate && .venv/bin/python manage.py seed_data
DJANGO_DEBUG=1 .venv/bin/python manage.py runserver
.venv/bin/pytest

# Frontend (Node 24): proxies /api to http://localhost:8000 unless BACKEND_URL is set
cd frontend
npm ci && npm run dev
```

Linters run through pre-commit: ruff, django-upgrade, a migrations check, eslint, prettier and tsc.
Enable them once with `backend/.venv/bin/pre-commit install`.
