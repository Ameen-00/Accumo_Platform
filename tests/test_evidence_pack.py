"""Evidence pack — spec §11. Limitations are not optional."""

from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from accumo_pulse.pack import (
    DispositionView,
    ExceptionView,
    PackInput,
    RuleApplied,
    SourceFileInfo,
    build_pack,
    limitations_for,
    render_html,
    render_pdf,
    render_zip,
)


def _exc(**kw) -> ExceptionView:
    return ExceptionView(
        id=kw.get("id") or uuid4(),
        rule_code=kw.get("rule_code", "DUP_EXACT"),
        status=kw.get("status", "new"),
        title=kw.get("title", "Exact duplicate payment — Southern Steels"),
        amount=Decimal(kw.get("amount", "240000")),
        currency=kw.get("currency", "INR"),
        confidence=Decimal(kw.get("confidence", "0.950")),
        explanation=kw.get(
            "explanation",
            {"rule": "DUP_EXACT", "why": "Same invoice paid twice."},
        ),
        evidence=kw.get("evidence", {}),
    )


def _src(**kw) -> PackInput:
    run_id = kw.get("run_id") or uuid4()
    return PackInput(
        organisation_name=kw.get("organisation_name", "Dev tenant"),
        country_code=kw.get("country_code", "IN"),
        currency=kw.get("currency", "INR"),
        period_start=kw.get("period_start", date(2025, 4, 1)),
        period_end=kw.get("period_end", date(2026, 3, 31)),
        run_id=run_id,
        generated_at=kw.get("generated_at", datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)),
        generated_by=kw.get("generated_by", "Pulse admin"),
        files=kw.get(
            "files",
            [
                SourceFileInfo("payment", "payments.csv", "abc123", 1200),
                SourceFileInfo("invoice", "invoices.csv", "def456", 980),
            ],
        ),
        row_counts=kw.get("row_counts", {"payment": 1200, "invoice": 980, "vendor": 40}),
        rules=kw.get(
            "rules",
            [
                RuleApplied("DUP_EXACT", "Exact duplicate payment", 1, {"window_days": 365}),
                RuleApplied("DUP_FUZZY", "Probable duplicate", 1, {"window_days": 90, "min_similarity": 85}),
                RuleApplied("BANK_CHANGE_PAY", "Bank detail changed, then paid", 1, {"window_days": 30}),
            ],
        ),
        exceptions=kw.get("exceptions", []),
        events=kw.get("events", []),
        bank_change_assessable=kw.get("bank_change_assessable", False),
        has_change_log=kw.get("has_change_log", False),
    )


def test_pack_leads_with_this_drop_not_limitations():
    pack = build_pack(
        _src(
            row_counts={"invoice": 49, "payment": 109},
            stats={"invoices": 49, "payments": 109, "open_bank": 7},
            exceptions=[_exc(status="confirmed", title="real duplicate", amount="38000")],
        )
    )
    html = render_html(pack)
    assert "49 bills in this drop" in html
    assert html.index("What you confirmed") < html.index("7. Limitations")
    assert "No WhatsApp export" in " ".join(pack.limitations)


def test_cover_has_the_three_money_figures():
    confirmed_id = uuid4()
    pack = build_pack(
        _src(
            exceptions=[
                _exc(amount="240000", status="new"),
                _exc(id=confirmed_id, amount="180000", status="confirmed"),
                _exc(amount="50000", status="recovered"),
            ],
            events=[
                DispositionView(
                    exception_id=confirmed_id,
                    rule_code="DUP_EXACT",
                    title="x",
                    actor="Reviewer",
                    from_status="confirmed",
                    to_status="recovered",
                    reason=None,
                    recovered_amount=Decimal("40000"),
                    at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                )
            ],
        )
    )
    assert pack.headline == (
        "INR 470,000.00 identified · INR 230,000.00 confirmed · INR 40,000.00 recovered"
    )
    assert str(pack.run_id) in render_html(pack)


def test_findings_are_confirmed_or_recovered_only():
    keep = uuid4()
    pack = build_pack(
        _src(
            exceptions=[
                _exc(status="new", title="still in queue"),
                _exc(status="dismissed", title="false positive"),
                _exc(id=keep, status="confirmed", title="real duplicate", amount="99000"),
                _exc(status="recovered", title="already clawed back", amount="10000"),
            ]
        )
    )
    titles = [f.title for f in pack.findings]
    assert titles[0] == "real duplicate"
    assert "already clawed back" in titles
    assert "still in queue" not in titles
    assert "false positive" not in titles


def test_dispositions_include_every_decision():
    a, b = uuid4(), uuid4()
    pack = build_pack(
        _src(
            exceptions=[_exc(id=a, status="dismissed"), _exc(id=b, status="confirmed")],
            events=[
                DispositionView(a, "DUP_EXACT", "x", "A", "new", "dismissed", "instalment", None, None),
                DispositionView(b, "DUP_EXACT", "x", "B", "in_review", "confirmed", None, None, None),
            ],
        )
    )
    assert len(pack.dispositions) == 2
    assert pack.dispositions[0].reason == "instalment"


def test_limitations_required_when_r4_not_assessable():
    lines = limitations_for(bank_change_assessable=False, applied=["DUP_EXACT"])
    blob = " ".join(lines)
    assert "not assessable" in blob
    assert "BANK_CHANGE_PAY" in blob
    assert "Rules not applied" in blob
    assert "NO_PO" in blob


def test_limitations_still_present_when_r4_ran():
    pack = build_pack(_src(bank_change_assessable=True, has_change_log=False))
    blob = " ".join(pack.limitations)
    assert "BANK_CHANGE_PAY" in blob
    assert "change log was not supplied" in blob
    html = render_html(pack)
    assert "7. Limitations" in html
    pdf = render_pdf(pack)
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert b"Limitations" in pdf


def test_zip_contains_seven_sections():
    pack = build_pack(
        _src(
            exceptions=[_exc(status="confirmed", amount="12000")],
            events=[
                DispositionView(
                    uuid4(), "DUP_EXACT", "x", "Reviewer", "in_review", "confirmed", None, None, None
                )
            ],
        )
    )
    names = set(ZipFile(BytesIO(render_zip(pack))).namelist())
    assert names == {
        "report.pdf",
        "report.html",
        "scope.csv",
        "rules.csv",
        "summary.csv",
        "findings.csv",
        "dispositions.csv",
        "limitations.csv",
    }
    raw = ZipFile(BytesIO(render_zip(pack))).read("limitations.csv").decode("utf-8")
    assert "BANK_CHANGE_PAY" in raw
    assert "not assessable" in raw


def test_unconfirmed_rows_do_not_appear_in_findings_csv():
    pack = build_pack(
        _src(
            exceptions=[
                _exc(status="new", title="queue only"),
                _exc(status="confirmed", title="attach this"),
            ]
        )
    )
    csv_text = ZipFile(BytesIO(render_zip(pack))).read("findings.csv").decode("utf-8")
    assert "attach this" in csv_text
    assert "queue only" not in csv_text


def test_completeness_findings_never_inflate_the_money_figures():
    """Regression: the pack once told the first real user INR 5.27 crore was
    confirmed when the money that had gone wrong was INR 9.4 lakh.

    An unmatched bank summary carries the whole outflow it could not explain,
    and an open-invoice summary carries the whole receivable. Both are coverage
    questions. Adding them to duplicate payments produced a number that scaled
    with the size of the ledger rather than with anything being wrong.
    """
    pack = build_pack(
        _src(
            exceptions=[
                # Real money: a duplicate and an unclaimed credit.
                _exc(rule_code="DUP_DOC", status="confirmed", amount="778218"),
                _exc(rule_code="CREDIT_UNAPPLIED", status="confirmed", amount="162285"),
                # Coverage questions. Large, and not losses.
                _exc(rule_code="OPEN_BANK", status="confirmed", amount="34591856"),
                _exc(rule_code="OPEN_INVOICE", status="confirmed", amount="16695337"),
                _exc(rule_code="COMP_2B_ORPHAN", status="confirmed", amount="519343"),
                _exc(rule_code="MATCH_SUGGEST", status="new", amount="4347848"),
            ]
        )
    )

    assert pack.confirmed == Decimal("940503")
    assert pack.identified == Decimal("940503")

    # Still counted, still shown, just never added to the money.
    assert pack.unexplained_count == 4
    assert pack.unexplained_amount == Decimal("56154384")

    # Everything a person agreed with stays in section 2, both families.
    assert len(pack.findings) == 5

    html = render_html(pack)
    assert "940,503" in html
    assert "not money at risk" in html.lower()
    # The conflated total must not appear anywhere in the document.
    assert "52,747,039" not in html
