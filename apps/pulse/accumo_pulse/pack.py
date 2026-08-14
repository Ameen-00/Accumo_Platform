"""Evidence pack — spec §11.

A partner attaches this, not a screenshot. The HTML is the print source.
The PDF is a text rendering so Windows and CI do not need WeasyPrint/GTK.
Linux deploys can later swap HTML→PDF via WeasyPrint without touching the
document model.

Section 7 (limitations) is not optional. A pack that does not say what it
could not test is not audit evidence.
"""

from __future__ import annotations

import csv
import html
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from accumo_pulse.catalogue import RULES

CATALOGUE = tuple(code for code, *_ in RULES)
CONFIRMED_STATUSES = frozenset({"confirmed", "recovered"})


def money(currency: str, amount: Decimal) -> str:
    return f"{currency} {Decimal(amount).quantize(Decimal('0.01')):,.2f}"


@dataclass(frozen=True)
class SourceFileInfo:
    entity: str
    filename: str
    sha256: str
    row_count: int | None


@dataclass(frozen=True)
class RuleApplied:
    code: str
    name: str
    version: int
    params: dict


@dataclass(frozen=True)
class ExceptionView:
    id: UUID
    rule_code: str
    status: str
    title: str
    amount: Decimal
    currency: str
    confidence: Decimal
    explanation: dict
    evidence: dict


@dataclass(frozen=True)
class DispositionView:
    exception_id: UUID
    rule_code: str
    title: str
    actor: str
    from_status: str | None
    to_status: str
    reason: str | None
    recovered_amount: Decimal | None
    at: datetime | None


@dataclass
class PackInput:
    organisation_name: str
    country_code: str
    currency: str
    period_start: date | None
    period_end: date | None
    run_id: UUID
    generated_at: datetime
    generated_by: str
    files: list[SourceFileInfo]
    row_counts: dict
    rules: list[RuleApplied]
    exceptions: list[ExceptionView]
    events: list[DispositionView]
    bank_change_assessable: bool
    has_change_log: bool = False
    catalogue: tuple[str, ...] = CATALOGUE


@dataclass(frozen=True)
class RuleSummary:
    code: str
    identified_count: int
    identified_amount: Decimal
    confirmed_count: int
    confirmed_amount: Decimal
    recovered_count: int
    recovered_amount: Decimal


@dataclass
class EvidencePack:
    organisation_name: str
    country_code: str
    currency: str
    period_label: str
    run_id: UUID
    generated_at: datetime
    generated_by: str
    identified: Decimal
    confirmed: Decimal
    recovered: Decimal
    files: list[SourceFileInfo]
    row_counts: dict
    rules: list[RuleApplied]
    by_rule: list[RuleSummary]
    findings: list[ExceptionView]
    dispositions: list[DispositionView]
    limitations: list[str] = field(default_factory=list)

    @property
    def headline(self) -> str:
        ccy = self.currency
        return (
            f"{money(ccy, self.identified)} identified · "
            f"{money(ccy, self.confirmed)} confirmed · "
            f"{money(ccy, self.recovered)} recovered"
        )


def limitations_for(
    *,
    bank_change_assessable: bool,
    applied: list[str],
    catalogue: tuple[str, ...] = CATALOGUE,
    has_change_log: bool = False,
) -> list[str]:
    """Section 7. Always returns a non-empty list. Always mentions R4."""
    lines = [
        "This pack lists exceptions raised by the rules that ran. "
        "It is not an audit opinion and it is not a statement that unlisted payments are clean.",
    ]
    missing = [code for code in catalogue if code not in applied]
    if missing:
        lines.append(
            "Rules not applied in this run: "
            + ", ".join(missing)
            + ". Absence from findings is not a test of those risks."
        )
    if not bank_change_assessable:
        lines.append(
            "BANK_CHANGE_PAY (rule 4) was not assessable. The import has no vendor "
            "bank-account change history — a first CSV with one account per supplier, "
            "and no ERP change log, cannot prove a change. A silent empty result would "
            "look like a clean book. It is not. This rule did not run as a test."
        )
    elif not has_change_log:
        lines.append(
            "BANK_CHANGE_PAY (rule 4) ran on accounts observed inside this import only. "
            "A full ERP vendor-master change log was not supplied, so earlier changes "
            "can be missed. Silence on older accounts is not a clean result."
        )
    else:
        lines.append(
            "BANK_CHANGE_PAY (rule 4) ran on the change history supplied with this import. "
            "Accounts that never appeared in the file were not tested."
        )
    lines.append(
        "Amounts are as loaded from the source files. They have not been agreed to bank statements."
    )
    lines.append(
        "Identity resolution may have merged or split suppliers. "
        "Review the pending-identity queue before treating vendor names as final."
    )
    return lines


def build_pack(src: PackInput) -> EvidencePack:
    recovered = sum(
        (e.recovered_amount or Decimal("0") for e in src.events if e.to_status == "recovered"),
        start=Decimal("0"),
    )
    identified = sum((x.amount for x in src.exceptions), start=Decimal("0"))
    confirmed_rows = [x for x in src.exceptions if x.status in CONFIRMED_STATUSES]
    confirmed = sum((x.amount for x in confirmed_rows), start=Decimal("0"))

    applied_codes = [r.code for r in src.rules]
    codes = list(dict.fromkeys(applied_codes + [x.rule_code for x in src.exceptions]))
    by_rule: list[RuleSummary] = []
    for code in codes:
        rows = [x for x in src.exceptions if x.rule_code == code]
        conf = [x for x in rows if x.status in CONFIRMED_STATUSES]
        rec_amt = sum(
            (
                e.recovered_amount or Decimal("0")
                for e in src.events
                if e.to_status == "recovered" and e.rule_code == code
            ),
            start=Decimal("0"),
        )
        rec_n = sum(1 for e in src.events if e.to_status == "recovered" and e.rule_code == code)
        by_rule.append(
            RuleSummary(
                code=code,
                identified_count=len(rows),
                identified_amount=sum((x.amount for x in rows), start=Decimal("0")),
                confirmed_count=len(conf),
                confirmed_amount=sum((x.amount for x in conf), start=Decimal("0")),
                recovered_count=rec_n,
                recovered_amount=rec_amt,
            )
        )

    start = src.period_start.isoformat() if src.period_start else "unspecified"
    end = src.period_end.isoformat() if src.period_end else "unspecified"
    pack = EvidencePack(
        organisation_name=src.organisation_name,
        country_code=src.country_code,
        currency=src.currency,
        period_label=f"{start} to {end}",
        run_id=src.run_id,
        generated_at=src.generated_at if src.generated_at.tzinfo else src.generated_at.replace(tzinfo=timezone.utc),
        generated_by=src.generated_by,
        identified=identified,
        confirmed=confirmed,
        recovered=recovered,
        files=list(src.files),
        row_counts=dict(src.row_counts or {}),
        rules=list(src.rules),
        by_rule=by_rule,
        findings=sorted(confirmed_rows, key=lambda x: x.amount, reverse=True),
        dispositions=list(src.events),
        limitations=limitations_for(
            bank_change_assessable=src.bank_change_assessable,
            applied=applied_codes,
            catalogue=src.catalogue,
            has_change_log=src.has_change_log,
        ),
    )
    if not pack.limitations:
        raise RuntimeError("evidence pack refused: limitations section is empty")
    if not any("BANK_CHANGE_PAY" in line or "rule 4" in line.lower() for line in pack.limitations):
        raise RuntimeError("evidence pack refused: rule 4 limitation missing")
    return pack


def _why(explanation: dict) -> str:
    if not explanation:
        return ""
    if explanation.get("why"):
        return str(explanation["why"])
    parts = []
    for key, value in explanation.items():
        if key in {"rule"}:
            continue
        parts.append(f"{key}: {value}")
    return "; ".join(parts)


def render_html(pack: EvidencePack) -> str:
    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    files = "".join(
        f"<tr><td>{esc(f.entity)}</td><td>{esc(f.filename)}</td>"
        f"<td>{esc(f.row_count if f.row_count is not None else '')}</td>"
        f"<td class='mono'>{esc(f.sha256)}</td></tr>"
        for f in pack.files
    ) or "<tr><td colspan='4'>No source files recorded.</td></tr>"
    counts = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in pack.row_counts.items()
    )
    rules = "".join(
        f"<tr><td>{esc(r.code)}</td><td>{esc(r.name)}</td>"
        f"<td>{esc(r.version)}</td><td class='mono'>{esc(r.params)}</td></tr>"
        for r in pack.rules
    ) or "<tr><td colspan='4'>No rules recorded on this run.</td></tr>"
    summary = "".join(
        f"<tr><td>{esc(s.code)}</td>"
        f"<td>{s.identified_count} / {esc(money(pack.currency, s.identified_amount))}</td>"
        f"<td>{s.confirmed_count} / {esc(money(pack.currency, s.confirmed_amount))}</td>"
        f"<td>{s.recovered_count} / {esc(money(pack.currency, s.recovered_amount))}</td></tr>"
        for s in pack.by_rule
    ) or "<tr><td colspan='4'>No exceptions in this run.</td></tr>"
    findings = []
    if not pack.findings:
        findings.append(
            "<p>No exceptions were confirmed in this run. Identified items remain in the review queue.</p>"
        )
    for item in pack.findings:
        findings.append(
            "<article class='finding'>"
            f"<h3>{esc(item.title)}</h3>"
            f"<p class='meta'>{esc(item.rule_code)} · {esc(item.status)} · "
            f"{esc(money(item.currency, item.amount))} · confidence {esc(item.confidence)}</p>"
            f"<p>{esc(_why(item.explanation))}</p>"
            "</article>"
        )
    disp = "".join(
        f"<tr><td>{esc(d.at.isoformat() if d.at else '')}</td>"
        f"<td>{esc(d.actor)}</td><td>{esc(d.rule_code)}</td>"
        f"<td>{esc(d.from_status or '—')} → {esc(d.to_status)}</td>"
        f"<td>{esc(d.reason or '')}</td>"
        f"<td>{esc(money(pack.currency, d.recovered_amount) if d.recovered_amount is not None else '')}</td></tr>"
        for d in pack.dispositions
    ) or "<tr><td colspan='6'>No dispositions recorded.</td></tr>"
    limits = "".join(f"<li>{esc(line)}</li>" for line in pack.limitations)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Pulse evidence pack · {esc(pack.organisation_name)}</title>
  <style>
    body {{ font: 12px/1.45 Georgia, serif; color: #111; margin: 32px 40px; max-width: 880px; }}
    h1 {{ font-size: 22px; margin-bottom: 4px; }}
    h2 {{ font-size: 15px; border-bottom: 1px solid #222; padding-bottom: 4px; margin-top: 28px; }}
    .headline {{ font-size: 16px; font-weight: 700; margin: 16px 0; }}
    .meta, .mono {{ font-family: Consolas, "Courier New", monospace; font-size: 11px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 8px 0 16px; }}
    th, td {{ border: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f3f3; }}
    .limits {{ background: #fff8e6; border: 1px solid #c9a227; padding: 12px 16px; }}
    .finding {{ margin: 12px 0 20px; }}
  </style>
</head>
<body>
  <h1>Pulse evidence pack</h1>
  <p class="meta">{esc(pack.organisation_name)} · {esc(pack.country_code)} · run {esc(pack.run_id)}</p>
  <p class="headline">{esc(pack.headline)}</p>
  <p>Period {esc(pack.period_label)}. Generated {esc(pack.generated_at.isoformat())} by {esc(pack.generated_by)}.</p>

  <h2>2. Scope</h2>
  <p>What was loaded for this run. Hashes are SHA-256 of the files as received.</p>
  <table>
    <tr><th>Entity</th><th>File</th><th>Rows</th><th>SHA-256</th></tr>
    {files}
  </table>
  <table>
    <tr><th>Loaded as</th><th>Count</th></tr>
    {counts}
  </table>

  <h2>3. Rules applied</h2>
  <table>
    <tr><th>Code</th><th>Name</th><th>Version</th><th>Parameters</th></tr>
    {rules}
  </table>

  <h2>4. Summary</h2>
  <table>
    <tr><th>Rule</th><th>Identified</th><th>Confirmed</th><th>Recovered</th></tr>
    {summary}
  </table>

  <h2>5. Findings (confirmed)</h2>
  {''.join(findings)}

  <h2>6. Dispositions</h2>
  <table>
    <tr><th>When</th><th>Who</th><th>Rule</th><th>Decision</th><th>Reason</th><th>Recovered</th></tr>
    {disp}
  </table>

  <h2>7. Limitations — what this pack could not test</h2>
  <div class="limits">
    <ul>{limits}</ul>
  </div>
</body>
</html>
"""


def _pdf_escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int = 92) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if len(trial) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class _Pdf:
    """Minimal PDF 1.4 text writer. Good enough to attach; not a layout engine."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.y = 800

    def _page(self) -> None:
        self.pages.append([])
        self.y = 800

    def _need(self, height: int = 16) -> None:
        if self.y - height < 50:
            self._page()

    def heading(self, text: str, size: int = 16) -> None:
        self._need(size + 14)
        self.pages[-1].append(
            f"BT /F1 {size} Tf 48 {self.y} Td ({_pdf_escape(text)}) Tj ET"
        )
        self.y -= size + 10

    def text(self, text: str, size: int = 10) -> None:
        for line in _wrap(text, 96 if size <= 10 else 80):
            self._need(14)
            self.pages[-1].append(
                f"BT /F1 {size} Tf 48 {self.y} Td ({_pdf_escape(line)}) Tj ET"
            )
            self.y -= 13 if size <= 10 else 16

    def gap(self, n: int = 8) -> None:
        self.y -= n
        if self.y < 50:
            self._page()

    def dumps(self) -> bytes:
        objects: list[bytes] = []

        def add(body: str) -> int:
            objects.append(body.encode("latin-1"))
            return len(objects)

        font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        content_ids: list[int] = []
        page_ids: list[int] = []
        # placeholders; we fill after kids exist — build contents first
        content_bodies = []
        for ops in self.pages:
            stream = "\n".join(ops).encode("latin-1")
            content_bodies.append(
                f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
                + stream
                + b"\nendstream"
            )
        for body in content_bodies:
            objects.append(body)
            content_ids.append(len(objects))

        pages_obj_id = len(objects) + len(self.pages) + 1
        for cid in content_ids:
            add(
                f"<< /Type /Page /Parent {pages_obj_id} 0 R "
                f"/MediaBox [0 0 595 842] /Contents {cid} 0 R "
                f"/Resources << /Font << /F1 {font} 0 R >> >> >>"
            )
            page_ids.append(len(objects))
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>")
        catalog = add(f"<< /Type /Catalog /Pages {pages_obj_id} 0 R >>")

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("ascii"))
            out.extend(body)
            out.extend(b"\nendobj\n")
        xref = len(out)
        out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            f"trailer << /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(out)


def render_pdf(pack: EvidencePack) -> bytes:
    doc = _Pdf()
    doc.heading("Pulse evidence pack")
    doc.text(f"{pack.organisation_name}  ·  {pack.country_code}  ·  run {pack.run_id}", 10)
    doc.gap(6)
    doc.text(pack.headline, 12)
    doc.gap(4)
    doc.text(f"Period {pack.period_label}")
    doc.text(f"Generated {pack.generated_at.isoformat()} by {pack.generated_by}")

    doc.gap(10)
    doc.heading("2. Scope", 13)
    doc.text("What was loaded for this run. Hashes are SHA-256 of the files as received.")
    if not pack.files:
        doc.text("No source files recorded.")
    for info in pack.files:
        doc.text(
            f"{info.entity}  {info.filename}  rows={info.row_count}  sha256={info.sha256}"
        )
    for key, value in pack.row_counts.items():
        doc.text(f"loaded {key}: {value}")

    doc.gap(8)
    doc.heading("3. Rules applied", 13)
    if not pack.rules:
        doc.text("No rules recorded on this run.")
    for rule in pack.rules:
        doc.text(f"{rule.code}  v{rule.version}  {rule.name}  params={rule.params}")

    doc.gap(8)
    doc.heading("4. Summary", 13)
    doc.text("identified / confirmed / recovered, by rule")
    if not pack.by_rule:
        doc.text("No exceptions in this run.")
    for row in pack.by_rule:
        doc.text(
            f"{row.code}: identified {row.identified_count} {money(pack.currency, row.identified_amount)}; "
            f"confirmed {row.confirmed_count} {money(pack.currency, row.confirmed_amount)}; "
            f"recovered {row.recovered_count} {money(pack.currency, row.recovered_amount)}"
        )

    doc.gap(8)
    doc.heading("5. Findings (confirmed)", 13)
    if not pack.findings:
        doc.text("No exceptions were confirmed in this run. Identified items remain in the review queue.")
    for item in pack.findings:
        doc.gap(4)
        doc.text(item.title, 11)
        doc.text(
            f"{item.rule_code} · {item.status} · {money(item.currency, item.amount)} · confidence {item.confidence}"
        )
        why = _why(item.explanation)
        if why:
            doc.text(why)

    doc.gap(8)
    doc.heading("6. Dispositions", 13)
    if not pack.dispositions:
        doc.text("No dispositions recorded.")
    for event in pack.dispositions:
        when = event.at.isoformat() if event.at else ""
        rec = money(pack.currency, event.recovered_amount) if event.recovered_amount is not None else ""
        doc.text(
            f"{when}  {event.actor}  {event.rule_code}  "
            f"{event.from_status or '—'} -> {event.to_status}  {event.reason or ''}  {rec}"
        )

    doc.gap(8)
    doc.heading("7. Limitations — what this pack could not test", 13)
    for line in pack.limitations:
        doc.text(f"• {line}")
        doc.gap(4)
    return doc.dumps()


def _csv(headers: list[str], rows: list[list[object]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    return buf.getvalue()


def render_zip(pack: EvidencePack) -> bytes:
    """PDF + HTML + one CSV per supporting section. Cover lives in the PDF."""
    pdf = render_pdf(pack)
    page = render_html(pack)
    files = {
        "report.pdf": pdf,
        "report.html": page.encode("utf-8"),
        "scope.csv": _csv(
            ["entity", "filename", "row_count", "sha256"],
            [[f.entity, f.filename, f.row_count, f.sha256] for f in pack.files],
        ).encode("utf-8"),
        "rules.csv": _csv(
            ["code", "name", "version", "params"],
            [[r.code, r.name, r.version, r.params] for r in pack.rules],
        ).encode("utf-8"),
        "summary.csv": _csv(
            [
                "rule",
                "identified_count",
                "identified_amount",
                "confirmed_count",
                "confirmed_amount",
                "recovered_count",
                "recovered_amount",
            ],
            [
                [
                    s.code,
                    s.identified_count,
                    s.identified_amount,
                    s.confirmed_count,
                    s.confirmed_amount,
                    s.recovered_count,
                    s.recovered_amount,
                ]
                for s in pack.by_rule
            ],
        ).encode("utf-8"),
        "findings.csv": _csv(
            ["id", "rule", "status", "title", "amount", "currency", "confidence", "why"],
            [
                [
                    item.id,
                    item.rule_code,
                    item.status,
                    item.title,
                    item.amount,
                    item.currency,
                    item.confidence,
                    _why(item.explanation),
                ]
                for item in pack.findings
            ],
        ).encode("utf-8"),
        "dispositions.csv": _csv(
            ["when", "who", "rule", "from", "to", "reason", "recovered_amount", "exception_id"],
            [
                [
                    d.at.isoformat() if d.at else "",
                    d.actor,
                    d.rule_code,
                    d.from_status,
                    d.to_status,
                    d.reason,
                    d.recovered_amount,
                    d.exception_id,
                ]
                for d in pack.dispositions
            ],
        ).encode("utf-8"),
        "limitations.csv": _csv(
            ["n", "limitation"],
            [[i + 1, line] for i, line in enumerate(pack.limitations)],
        ).encode("utf-8"),
    }
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return blob.getvalue()


def filename_for(pack: EvidencePack) -> str:
    stamp = pack.generated_at.strftime("%Y%m%d")
    return f"pulse-evidence-{str(pack.run_id)[:8]}-{stamp}.zip"
