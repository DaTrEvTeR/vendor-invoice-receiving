# Vendor Invoice Receiving: Take-Home Project

Hi, and thanks for spending time on this. Luxe Software builds an all-in-one operating system for independent jewelry stores. This project is a small slice of a real problem our stores have.

## The problem

When a jewelry store buys merchandise, the vendor ships the goods and sends an invoice. Today a staff member types every invoice line into inventory by hand: the item, the quantity, the cost, and for diamonds, the certificate number. It's slow, people make mistakes, and those mistakes corrupt inventory counts and cost of goods.

More and more vendors now send invoices electronically. Most come through an invoicing network as JSON; a few smaller vendors email a CSV export from their own systems. The store wants to load those files and have the system:

- match each invoice line to the store's catalog and its open purchase orders,
- point out anything that looks off,
- let a staff member review, correct, and approve it,
- and then receive the merchandise into inventory.

The owner has one rule that isn't up for debate: **wrong numbers must never silently reach inventory.**

## What should exist when you're done

- **Load invoices.** A way to submit a vendor invoice file (JSON or CSV), through a simple web page, an API, or both.
- **Matching.** Invoice lines are matched against the catalog, the vendor item-code map, and open purchase orders in `data/`.
- **Review.** A screen where staff see the vendor's original invoice data next to how your system interpreted and matched it, and can edit, approve, or reject.
- **Receiving.** Approving an invoice receives the inventory. On-hand quantities and purchase-order state are updated, saved, and visible somewhere.
- **Repeats.** Some sensible handling for an invoice that has already been processed.
- **Tests** for whichever edge cases you decide matter most.
- **One command to run it**, documented, for example `docker compose up` or `make run`.

The UI is only there so we can see the system work. Plain server-rendered HTML is completely fine; we're not grading design.

Your system doesn't need to call any AI model, and no API keys are needed. Using AI tools to *build* it is a different story; see below.

## What's in this folder

Download this folder and use it as the starting point of your own Git repo.

```
data/catalog.csv            the store's products (SKU, unit of measure, serialized or not, cost, on hand)
data/vendors.csv            vendors the store buys from
data/vendor_sku_map.csv     vendor item codes -> store SKUs
data/purchase_orders.json   open purchase orders
data/invoices/              12 invoice files, exactly as they arrived from vendors
scripts/check_data.py       loads and prints the data files, nothing more
```

There's no starter code and no format spec for the invoice files on purpose. Working out the formats from the samples, and how you structure the project, are part of what we'd like to see.

## Stack

The backend must be Python. Django is our stack, so we'd love to see it, but FastAPI or Flask is fine too. Use any frontend you like.

## Timebox

Aim for **4–5 hours**, and please don't go over. You won't get to everything, and that's expected. Prioritize, and tell us what you cut and why. A well-reasoned partial solution beats a rushed complete one.

## AI tools

Please use them: Claude Code, Cursor, whatever you normally work with. We assume most of the code will be AI-written. In the follow-up conversation we'll ask you to walk us through your code and decisions **without** AI tools, so make sure you understand and agree with everything you commit. We especially want to hear where you overrode or rejected what the AI suggested.

## Results file

Start from the data as shipped, submit the 12 sample invoices **in filename order**, and let your system do whatever it does on its own, **with no human review or approval**. Then write the resulting state to `results/outcomes.json`. Whatever your internal storage looks like, this file is the one fixed interface, so we can run every submission the same way.

```json
{
  "invoices": [
    {
      "file": "inv_01.json",
      "status": "string",
      "notes": "string",
      "received_lines": [
        {"sku": "string", "quantity": "decimal-as-string", "unit": "string", "po_number": "string | null"}
      ]
    }
  ],
  "inventory": {"<sku>": "<on_hand as decimal-as-string>"},
  "purchase_orders": {"<po_number>": {"<sku>": "<qty_received as decimal-as-string>"}}
}
```

- `status` and `notes` are yours to define: whatever outcome your system reached for that file (for example, received or needs review), and why.
- `received_lines` lists what your system actually received into inventory for that file without anyone stepping in. An empty list is perfectly fine.
- `inventory` and `purchase_orders` cover every SKU and every PO line in `data/`, as they stand after all 12 files.

## What to send us

1. A link to your repo (GitHub or GitLab).
2. A `DECISIONS.md` in the repo root using the headings below.
3. `results/outcomes.json`, produced as described above, plus the command that regenerates it.
4. Optional: a screen recording of 5 minutes or less.

### `DECISIONS.md` headings

Keep each section short. Bullet points are fine.

1. **Assumptions:** *what you assumed that this brief didn't say.*
2. **Architecture overview:** *components and data flow; a diagram is welcome.*
3. **Data model:** *key entities and why.*
4. **What the system decides vs. what a person decides:** *which checks run automatically, and what sends an invoice or a line to a human.*
5. **Matching strategy:** *how lines map to catalog items and PO lines, and what happens when they don't.*
6. **Failure modes:** *what can go wrong and what the system does about it.*
7. **Security and data safety.**
8. **Testing:** *how you know it works, and what you'd add with more time.*
9. **What I cut and what I'd do next.**
10. **How I used AI tools:** *which tools, and where you corrected or rejected their output.*

Questions while you work? Email us at pavan@luxesoftware.com. We'd much rather hear from you than have you guess. Have fun with it.
