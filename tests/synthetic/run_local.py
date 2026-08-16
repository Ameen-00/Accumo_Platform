"""Run the Pulse engine on synthetic books and write an evidence pack.

No Docker, no Postgres, no customer file. Output lands in .data/demo/
(gitignored). This is how we prove the factory works on this laptop.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

from accumo_canonical.identity import VendorSnap, propose
from accumo_canonical.normalise import normalise_invoice, normalise_name
from accumo_pulse.pack import (
    DispositionView,
    ExceptionView,
    PackInput,
    RuleApplied,
    SourceFileInfo,
    build_pack,
    filename_for,
    render_html,
    render_zip,
)
from accumo_pulse.rules.bank_change import BankChangePay, is_assessable
from accumo_pulse.rules.dup_exact import DupExact
from accumo_pulse.rules.dup_fuzzy import DupFuzzy
from accumo_rules.context import AllocatedPayment, PaymentToBank
from tests.synthetic.generate import generate, write_csv

ROOT = Path(__file__).resolve().parents[2]
SYNTH = ROOT / ".data" / "synth"
DEMO = ROOT / ".data" / "demo"


def _uuid(kind: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"accumo-demo/{kind}/{key}")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def run(rows: int = 2000, country: str = "IN") -> Path:
    pack = generate(rows, country, seed=42)
    SYNTH.mkdir(parents=True, exist_ok=True)
    write_csv(SYNTH / "vendors.csv", pack["vendors"], list(pack["vendors"][0].keys()))
    write_csv(SYNTH / "invoices.csv", pack["invoices"], list(pack["invoices"][0].keys()))
    write_csv(SYNTH / "payments.csv", pack["payments"], list(pack["payments"][0].keys()))
    (SYNTH / "planted.json").write_text(json.dumps(pack["meta"], indent=2), encoding="utf-8")

    vendors = _read(SYNTH / "vendors.csv")
    invoices = {r["source_ref"]: r for r in _read(SYNTH / "invoices.csv")}
    payments = _read(SYNTH / "payments.csv")

    snaps = [
        VendorSnap(
            id=_uuid("vendor", v["source_ref"]),
            name=v["name"],
            name_normalised=normalise_name(v["name"]),
            tax_id=v.get("tax_id") or None,
            registration_id=v.get("registration_id") or None,
            account_norms=[v["bank"]] if v.get("bank") else [],
        )
        for v in vendors
    ]
    proposals = propose(snaps)
    vendor_to_ident: dict[UUID, tuple[UUID, str]] = {}
    for prop in proposals:
        for vid in prop.member_ids:
            vendor_to_ident[vid] = (prop.member_ids[0], prop.canonical_name)

    allocated: list[AllocatedPayment] = []
    bank_pays: list[PaymentToBank] = []
    for p in payments:
        inv = invoices.get(p["invoice_ref"])
        if not inv:
            continue
        vendor_id = _uuid("vendor", p["vendor_ref"])
        ident, ident_name = vendor_to_ident.get(vendor_id, (vendor_id, p["vendor_ref"]))
        pay_id = _uuid("pay", p["source_ref"])
        inv_id = _uuid("inv", inv["source_ref"])
        amount = Decimal(p["amount"])
        day = date.fromisoformat(p["payment_date"])
        allocated.append(
            AllocatedPayment(
                payment_id=pay_id,
                invoice_id=inv_id,
                invoice_norm=inv.get("invoice_norm") or normalise_invoice(inv["invoice_number"]),
                invoice_number=inv["invoice_number"],
                amount=amount,
                currency=p["currency"],
                payment_date=day,
                vendor_identity_id=ident,
                vendor_name=ident_name,
            )
        )
        if p.get("bank"):
            bank_pays.append(
                PaymentToBank(
                    payment_id=pay_id,
                    vendor_id=vendor_id,
                    vendor_identity_id=ident,
                    vendor_name=ident_name,
                    account_norm=p["bank"],
                    payment_date=day,
                    amount=amount,
                    currency=p["currency"],
                )
            )

    findings = {
        "DUP_EXACT": list(DupExact().run(allocated)),
        "DUP_FUZZY": list(DupFuzzy().run(allocated)),
        "BANK_CHANGE_PAY": list(BankChangePay().run(bank_pays, [])),
    }
    assessable = is_assessable([], bank_pays)

    def _is_planted(code: str, f) -> bool:
        why = f.explanation or {}
        if code == "DUP_EXACT":
            return why.get("invoice") == "INV/2025/1044"
        if code == "DUP_FUZZY":
            invs = set(why.get("invoices") or [])
            return invs == {"INV/2025/0412", "INV-2025-412"}
        if code == "BANK_CHANGE_PAY":
            return "Paid after vendor bank account changed" in f.title
        return False

    exceptions: list[ExceptionView] = []
    events: list[DispositionView] = []
    now = datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc)
    for code, rows_f in findings.items():
        for i, f in enumerate(rows_f):
            exc_id = _uuid("exc", f"{code}:{i}:{f.title}")
            planted = _is_planted(code, f)
            recovered = None
            status = "new"
            if planted and code == "DUP_EXACT":
                status = "recovered"
                recovered = (f.amount_at_risk / 2).quantize(Decimal("0.01"))
            elif planted:
                status = "confirmed"
            exceptions.append(
                ExceptionView(
                    id=exc_id,
                    rule_code=code,
                    status=status,
                    title=f.title,
                    amount=f.amount_at_risk,
                    currency=f.currency,
                    confidence=f.confidence,
                    explanation=f.explanation,
                    evidence=f.evidence,
                )
            )
            if not planted:
                continue
            events.append(
                DispositionView(
                    exception_id=exc_id,
                    rule_code=code,
                    title=f.title,
                    actor="Pulse admin (local demo)",
                    from_status="new",
                    to_status="in_review",
                    reason=None,
                    recovered_amount=None,
                    at=now,
                )
            )
            events.append(
                DispositionView(
                    exception_id=exc_id,
                    rule_code=code,
                    title=f.title,
                    actor="Pulse admin (local demo)",
                    from_status="in_review",
                    to_status="confirmed",
                    reason=None,
                    recovered_amount=None,
                    at=now,
                )
            )
            if recovered is not None:
                events.append(
                    DispositionView(
                        exception_id=exc_id,
                        rule_code=code,
                        title=f.title,
                        actor="Pulse admin (local demo)",
                        from_status="confirmed",
                        to_status="recovered",
                        reason="Customer agreed half was a true duplicate",
                        recovered_amount=recovered,
                        at=now,
                    )
                )

    evidence = build_pack(
        PackInput(
            organisation_name="Demo tenant (synthetic books)",
            country_code=country,
            currency=pack["meta"]["currency"],
            period_start=date(2024, 4, 1),
            period_end=date(2026, 3, 31),
            run_id=_uuid("run", f"{country}:{rows}"),
            generated_at=now,
            generated_by="Pulse admin (local demo)",
            files=[
                SourceFileInfo("vendor", "vendors.csv", "synth", len(vendors)),
                SourceFileInfo("invoice", "invoices.csv", "synth", len(invoices)),
                SourceFileInfo("payment", "payments.csv", "synth", len(payments)),
            ],
            row_counts={
                "vendor": len(vendors),
                "invoice": len(invoices),
                "payment": len(payments),
                "identities_auto": sum(1 for p in proposals if not p.needs_review),
                "identities_pending": sum(1 for p in proposals if p.needs_review),
            },
            rules=[
                RuleApplied("DUP_EXACT", "Exact duplicate payment", 1, {"window_days": 365}),
                RuleApplied("DUP_FUZZY", "Probable duplicate", 1, {"window_days": 90, "min_similarity": 85}),
                RuleApplied("BANK_CHANGE_PAY", "Bank detail changed, then paid", 1, {"window_days": 30}),
            ],
            exceptions=exceptions,
            events=events,
            bank_change_assessable=assessable,
            has_change_log=False,
        )
    )

    DEMO.mkdir(parents=True, exist_ok=True)
    zip_path = DEMO / filename_for(evidence)
    zip_path.write_bytes(render_zip(evidence))
    html_path = DEMO / "report.html"
    html_path.write_text(render_html(evidence), encoding="utf-8")
    summary = {
        "headline": evidence.headline,
        "findings": len(evidence.findings),
        "by_rule": {s.code: s.identified_count for s in evidence.by_rule},
        "bank_change_assessable": assessable,
        "zip": str(zip_path),
        "html": str(html_path),
        "planted": pack["meta"]["planted"],
    }
    (DEMO / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return zip_path


if __name__ == "__main__":
    run()
