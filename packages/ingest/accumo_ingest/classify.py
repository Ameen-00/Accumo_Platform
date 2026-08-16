"""Decide what a dropped file is, then which Pulse mode to run.

Zero books: invoices / bank / WhatsApp photos, no purchase register.
Proper books: Zoho / Tally / mapped CSVs.
The model does not guess a mode silently — the profile is shown to a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileKind:
    filename: str
    kind: str
    reason: str
    skip: bool = False


@dataclass
class Environment:
    mode: str  # zero_books | proper_books | mixed
    summary: str
    files: list[FileKind] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


INVOICE_HINTS = ("inv-", "invoice", "tax invoice", "bill")
BANK_HINTS = ("acct_statement", "account statement", "bank", "statement")
TWO_B_HINTS = ("gstr-2b", "gstr2b", "2b")
BOOKS_HINTS = ("account transactions", "tally", "zoho", "day book", "purchase register")
TRAINING_HINTS = ("pulse_ai_training", "fieldwork")


def classify_name(filename: str) -> FileKind:
    lower = filename.lower().replace("\\", "/")
    base = lower.rsplit("/", 1)[-1]
    if any(h in base for h in TRAINING_HINTS):
        return FileKind(
            filename,
            "training_pack",
            "Training pack — not a customer invoice. Treating it as a bill would create a fake payable.",
            skip=True,
        )
    if base.endswith(".pdf") and (base.startswith("inv-") or base.startswith("invoice") or "invoice" in base):
        return FileKind(filename, "invoice_pdf", "Looks like a supplier tax invoice")
    if base.endswith(".pdf") and any(base.startswith(p) for p in ("899_", "903_", "948_")):
        return FileKind(
            filename,
            "workpaper",
            "This is an ITR / tax computation, not a supplier invoice. "
            "If Pulse treated it as a bill it would invent a fake payable. Left out on purpose.",
            skip=True,
        )
    if "prime guardian cyber" in base and base.endswith(".pdf"):
        return FileKind(
            filename,
            "workpaper",
            "This is a client profile, not a supplier invoice. "
            "If Pulse treated it as a bill it would invent a fake payable. Left out on purpose.",
            skip=True,
        )
    if any(h in base for h in TWO_B_HINTS):
        return FileKind(filename, "gstr2b", "GSTR-2B extract")
    if base.endswith((".xls", ".xlsx")) and any(h in base for h in BANK_HINTS):
        return FileKind(filename, "bank_statement", "Bank account statement")
    if any(h in base for h in BOOKS_HINTS):
        return FileKind(filename, "books_export", "Ledger / ERP transaction export")
    if base.endswith(".pdf") and any(h in base for h in BANK_HINTS):
        return FileKind(filename, "bank_pdf", "Bank statement PDF — parse is best-effort")
    if base.endswith((".csv", ".xlsx", ".xls")):
        return FileKind(filename, "tabular", "Spreadsheet — will try column mapping")
    if base.endswith(".pdf"):
        return FileKind(filename, "document_pdf", "PDF — will try to read as an invoice")
    if base.endswith(".zip"):
        return FileKind(filename, "zip", "Bundle of mixed files")
    return FileKind(
        filename,
        "unknown",
        "Unrecognised file. Pulse will not guess it is an invoice — that would risk a fake bill.",
        skip=True,
    )


def profile(kinds: list[FileKind]) -> Environment:
    usable = [k for k in kinds if not k.skip]
    counts: dict[str, int] = {}
    for k in usable:
        counts[k.kind] = counts.get(k.kind, 0) + 1
    invoices = counts.get("invoice_pdf", 0) + counts.get("document_pdf", 0)
    books = counts.get("books_export", 0) + counts.get("tabular", 0)
    bank = counts.get("bank_statement", 0) + counts.get("bank_pdf", 0)
    two_b = counts.get("gstr2b", 0)

    if invoices and not books:
        mode = "zero_books"
        summary = (
            "No purchase register. Pulse will reconstruct payables from invoices"
            + (", the bank statement" if bank else "")
            + (", and GSTR-2B" if two_b else "")
            + ". Nothing is booked until you confirm."
        )
    elif books and not invoices:
        mode = "proper_books"
        summary = (
            "This looks like a books export (Zoho / Tally / spreadsheet). "
            "Ledger credits become bills and ledger debits become payments. You confirm every finding."
        )
    elif books and invoices:
        mode = "mixed"
        summary = (
            "Both raw invoices and books are present. Pulse will use the documents first "
            "and fill gaps from the ledger. You confirm every finding."
        )
    elif two_b or bank:
        mode = "zero_books"
        summary = "Partial records only. Pulse will show what is missing. This is not a full run."
    else:
        mode = "zero_books"
        summary = "Almost nothing usable yet. Add invoices, a bank statement, or a books export."

    skipped = [k for k in kinds if k.skip]
    limits: list[str] = []
    if skipped:
        limits.append(
            f"{len(skipped)} file(s) were not treated as invoices "
            "(ITR, profile, or training). Counting them as bills would create fake payables."
        )
    if counts.get("books_export"):
        limits.append("Zoho ledger credits were read as bills; debits as payments.")
    if not two_b:
        limits.append("No GSTR-2B file — GST portal completeness was not checked.")
    if not bank:
        limits.append("No bank statement — Pulse cannot say which bills were paid.")
    if not invoices and not counts.get("books_export") and mode == "zero_books":
        limits.append("No invoice documents — reconstruction will be thin.")

    return Environment(mode=mode, summary=summary, files=kinds, counts=counts, limitations=limits)
