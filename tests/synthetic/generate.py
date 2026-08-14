"""Synthetic organisation with planted exceptions.

Week 1 requirement: generate 500k rows and know exactly which
exceptions must be found. Recall tests against this, not against hope.

Usage (from repo root):
  python -m tests.synthetic.generate --rows 5000 --out /tmp/synth
  python -m tests.synthetic.generate --rows 500000 --country AE --out /tmp/synth-ae
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from accumo_canonical.normalise import normalise_invoice, normalise_name, normalise_tax_id

CURRENCIES = {"IN": "INR", "AE": "AED"}


def daterange(rng: random.Random, start: date, days: int) -> date:
    return start + timedelta(days=rng.randint(0, days))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def generate(rows: int, country: str, seed: int) -> dict:
    rng = random.Random(seed)
    currency = CURRENCIES[country]
    n_vendors = max(40, rows // 80)
    start = date(2024, 4, 1)

    vendors = []
    for i in range(n_vendors):
        name = f"Vendor {i:04d} Pvt Ltd" if country == "IN" else f"Vendor {i:04d} FZE"
        tax = f"{32 + (i % 5):02d}AABCV{i:04d}A1Z{i % 9}" if country == "IN" else f"100{i:07d}"
        vendors.append(
            {
                "source_ref": f"V-{i:04d}",
                "name": name,
                "name_normalised": normalise_name(name),
                "tax_id": normalise_tax_id(tax),
                "registration_id": f"PAN{i:06d}" if country == "IN" else f"CR{i:06d}",
                "country_code": country,
                "bank": f"{100000000000 + i}",
                "ifsc_swift": f"HDFC0{i:06d}" if country == "IN" else f"AE07033{i:011d}",
            }
        )

    # Plant R3: two codes, one tax id
    twin = dict(vendors[3])
    twin["source_ref"] = "V-0003B"
    twin["name"] = "Vendor 0003 Trading LLC" if country == "AE" else "Vendor 0003 Traders"
    twin["name_normalised"] = normalise_name(twin["name"])
    vendors.append(twin)

    invoices: list[dict] = []
    payments: list[dict] = []
    allocations: list[dict] = []
    credits: list[dict] = []
    planted: list[dict] = []

    inv_n = 0
    pay_n = 0

    def add_invoice(vendor, number, amount, day):
        nonlocal inv_n
        inv_n += 1
        rec = {
            "source_ref": f"I-{inv_n:07d}",
            "vendor_ref": vendor["source_ref"],
            "invoice_number": number,
            "invoice_norm": normalise_invoice(number),
            "invoice_date": day.isoformat(),
            "gross_amount": f"{amount:.4f}",
            "currency": currency,
        }
        invoices.append(rec)
        return rec

    def add_payment(vendor, amount, day, invoice, bank=None):
        nonlocal pay_n
        pay_n += 1
        rec = {
            "source_ref": f"P-{pay_n:07d}",
            "vendor_ref": vendor["source_ref"],
            "payment_date": day.isoformat(),
            "amount": f"{amount:.4f}",
            "currency": currency,
            "invoice_ref": invoice["source_ref"],
            "bank": bank or vendor["bank"],
        }
        payments.append(rec)
        allocations.append(
            {
                "payment_ref": rec["source_ref"],
                "invoice_ref": invoice["source_ref"],
                "amount": rec["amount"],
            }
        )
        return rec

    target = max(0, rows - 20)
    while len(payments) < target:
        v = vendors[rng.randint(0, n_vendors - 1)]
        amt = rng.choice([12500, 34800, 76000, 118000, 186000, 240000]) + rng.randint(0, 99)
        day = daterange(rng, start, 600)
        number = f"INV/{day.year}/{rng.randint(1000, 9999)}"
        inv = add_invoice(v, number, amt, day)
        add_payment(v, amt, day + timedelta(days=rng.randint(1, 20)), inv)

    # R1 exact duplicate
    v = vendors[1]
    day = date(2025, 6, 2)
    inv = add_invoice(v, "INV/2025/1044", 240000, day)
    add_payment(v, 240000, day + timedelta(days=3), inv)
    add_payment(v, 240000, day + timedelta(days=5), inv)
    planted.append({"rule": "DUP_EXACT", "invoice": "INV/2025/1044", "amount": 240000})

    # R2 fuzzy invoice
    v = vendors[2]
    day = date(2025, 7, 10)
    inv_a = add_invoice(v, "INV/2025/0412", 88500, day)
    inv_b = add_invoice(v, "INV-2025-412", 88500, day + timedelta(days=4))
    add_payment(v, 88500, day + timedelta(days=2), inv_a)
    add_payment(v, 88500, day + timedelta(days=6), inv_b)
    planted.append({"rule": "DUP_FUZZY", "invoices": ["INV/2025/0412", "INV-2025-412"], "amount": 88500})

    # R3 already planted as twin vendor
    planted.append({"rule": "DUP_VENDOR", "vendor_refs": ["V-0003", "V-0003B"]})

    # R4 bank change then pay
    v = vendors[5]
    old_bank = v["bank"]
    new_bank = "999888777666"
    day = date(2025, 8, 1)
    inv_old = add_invoice(v, "INV/2025/5001", 72000, day)
    add_payment(v, 72000, day + timedelta(days=2), inv_old, bank=old_bank)
    inv_new = add_invoice(v, "INV/2025/5058", 480000, day + timedelta(days=10))
    add_payment(v, 480000, day + timedelta(days=12), inv_new, bank=new_bank)
    planted.append({"rule": "BANK_CHANGE_PAY", "vendor_ref": v["source_ref"], "new_bank_last4": "7666"})

    # R8 unapplied credit
    v = vendors[6]
    day = date(2025, 3, 1)
    inv = add_invoice(v, "INV/2025/8801", 156000, day)
    add_payment(v, 156000, day + timedelta(days=10), inv)
    credits.append(
        {
            "source_ref": "CN-19",
            "vendor_ref": v["source_ref"],
            "invoice_ref": inv["source_ref"],
            "note_date": (day + timedelta(days=20)).isoformat(),
            "amount": "45000.0000",
            "currency": currency,
            "applied": "false",
        }
    )
    planted.append({"rule": "CREDIT_UNAPPLIED", "credit": "CN-19", "amount": 45000})

    vendor_rows = [
        {
            "source_ref": v["source_ref"],
            "name": v["name"],
            "tax_id": v["tax_id"],
            "registration_id": v["registration_id"],
            "country_code": v["country_code"],
            "bank": v["bank"],
            "ifsc_swift": v["ifsc_swift"],
        }
        for v in vendors
    ]

    return {
        "meta": {
            "country_code": country,
            "currency": currency,
            "vendors": len(vendor_rows),
            "invoices": len(invoices),
            "payments": len(payments),
            "credits": len(credits),
            "planted": planted,
        },
        "vendors": vendor_rows,
        "invoices": invoices,
        "payments": payments,
        "allocations": allocations,
        "credits": credits,
        "planted": planted,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=5000)
    p.add_argument("--country", choices=("IN", "AE"), default="IN")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, default=Path(".data/synth"))
    args = p.parse_args()
    pack = generate(args.rows, args.country, args.seed)
    out: Path = args.out
    write_csv(out / "vendors.csv", pack["vendors"], list(pack["vendors"][0].keys()))
    write_csv(out / "invoices.csv", pack["invoices"], list(pack["invoices"][0].keys()))
    write_csv(out / "payments.csv", pack["payments"], list(pack["payments"][0].keys()))
    write_csv(out / "allocations.csv", pack["allocations"], list(pack["allocations"][0].keys()))
    write_csv(out / "credits.csv", pack["credits"], list(pack["credits"][0].keys()))
    (out / "planted.json").write_text(json.dumps(pack["meta"], indent=2), encoding="utf-8")
    print(json.dumps(pack["meta"], indent=2))


if __name__ == "__main__":
    main()
