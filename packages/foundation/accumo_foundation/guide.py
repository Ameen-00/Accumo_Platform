"""What to do next. Deterministic. Never books. Never marks money saved."""

from __future__ import annotations

from typing import Any

NEXT_ACTION: dict[str, str] = {
    "DUP_DOC": "Open both files. If they are the same bill, confirm. If they are two different bills, dismiss and say why.",
    "DUP_REVISED": "Same supplier, same rupees, two documents. If the second is a revised estimate for the same job and both were paid, confirm. If they are two real jobs, dismiss.",
    "DUP_EXACT": "Same vendor, same invoice, paid twice. Confirm only if the second payment really went out.",
    "DUP_FUZZY": "Almost the same invoice number. Confirm it is a second payment, or dismiss if it is only a spelling change.",
    "DUP_VENDOR": "Two names, one tax id. Confirm they are the same supplier, or dismiss if they are not.",
    "CREDIT_UNAPPLIED": "Look in the books. If this credit was already taken off a later bill, dismiss. If it is still sitting unused, confirm.",
    "MATCH_SUGGEST": "A bank line looks like it settles this bill. Confirm only if you can see they are the same. Pulse will not mark it paid for you.",
    "OPEN_INVOICE": "If the title says other period, dismiss with “other month”. If it is the same month as the bank file, confirm unpaid or other account.",
    "OPEN_BANK": "These outflows have no bill in this drop. Confirm missing bills, or dismiss if they are salary, tax, or another period.",
    "COMP_2B_MISSING": "If the title says other period, dismiss. If the bill and the GST file are the same months, confirm the credit may be at risk.",
    "COMP_2B_ORPHAN": "If the title says other period, dismiss. If it is the same months as your bills, confirm the bill is missing or upload it.",
    "AMT_2B": "Same invoice number, two rupee figures. Confirm which one you will pay. Do not average them.",
    "BANK_CHANGE_PAY": "The supplier account changed and a payment followed. Confirm only if someone approved the new account.",
    "NO_PO": "Paid without a purchase order. Confirm if that broke your process, or dismiss if this vendor does not need a PO.",
    "THRESHOLD": "Several payments just under a limit. Confirm if they were split on purpose, or dismiss if they are normal.",
    "VENDOR_IS_EMPLOYEE": "A vendor is paid into a staff account. Confirm only if that is not an approved reimbursement.",
}


def next_action(rule: str, explanation: dict[str, Any] | None = None) -> str:
    other = bool(explanation and explanation.get("other_period"))
    if other and rule in {"OPEN_INVOICE", "COMP_2B_MISSING", "COMP_2B_ORPHAN"}:
        return "This is another month, not a missing payment. Dismiss with “other month” unless you know it is still open."
    return NEXT_ACTION.get(rule, "Confirm if this is real. Dismiss if it is not a problem. Pulse does not book.")


def spoken_line(stats: dict[str, Any]) -> str:
    """One sentence Arjun can say out loud. Not a GST lecture."""
    bills = int(stats.get("invoices") or 0)
    pays = int(stats.get("payments") or 0)
    no_bill = int(stats.get("open_bank") or 0)
    open_inv = int(stats.get("open_invoices") or 0)
    parts = [f"{bills} bills in this drop", f"{pays} payments"]
    if no_bill:
        parts.append(f"{no_bill} bank payments with no bill in this drop")
    elif open_inv:
        parts.append(f"{open_inv} bills not in this bank file")
    banks = int(stats.get("bank_files") or 0)
    if banks <= 1:
        parts.append("one bank file — other accounts and cash were not tested")
    else:
        parts.append(f"{banks} bank files — cash was not tested")
    return " · ".join(parts) + "."


def briefing(stats: dict[str, Any]) -> dict[str, Any]:
    dups = int(stats.get("dup_docs") or 0) + int(stats.get("dup_revised") or 0)
    credits = int(stats.get("credits") or 0)
    suggested = int(stats.get("suggested") or 0)
    open_inv = int(stats.get("open_invoices") or 0)
    orphans = int(stats.get("two_b_gaps") or 0)
    invoices = int(stats.get("invoices") or 0)
    payments = int(stats.get("payments") or 0)
    two_b = int(stats.get("two_b") or 0)
    ledger = int(stats.get("ledger") or 0)

    mistakes = dups + credits
    steps: list[str] = []
    if mistakes:
        steps.append(
            f"Start with Possible mistakes — {dups} possible second bills and {credits} credit notes. "
            "These are the ones most likely to be real."
        )
    else:
        steps.append("No obvious duplicates or unused credits in this drop. That is not a clean book yet.")
    paid_no_bill = int(stats.get("open_bank_count") or 0)
    steps.insert(
        1,
        f"This drop: {invoices} bills · {payments} payments"
        + (f" · {two_b} GST portal rows" if two_b else "")
        + ". Other month is not unpaid.",
    )
    if suggested:
        steps.append(
            f"Then Confirm a payment — {suggested} bank lines look related to a bill. "
            "Only you can say they are the same."
        )
    if open_inv or orphans or paid_no_bill:
        steps.append(
            "Leave Missing / other month for last. Other month is not unpaid and is not lost ITC."
        )
    steps.append("Confirm = this is real. Dismiss = this is not a problem. Pulse never books a rupee.")

    read_bits = [f"{invoices} bills"]
    if ledger:
        read_bits.append(f"{ledger} ledger lines")
    read_bits.append(f"{payments} payments")
    if two_b:
        read_bits.append(f"{two_b} GST portal rows")

    start = (
        f"Pulse read {', '.join(read_bits)}. "
        + (
            f"Open Possible mistakes first ({mistakes} questions)."
            if mistakes
            else "Nothing jumped out as a duplicate. Walk the other queues."
        )
    )
    return {
        "start": start,
        "spoken": spoken_line(stats),
        "steps": steps,
        "guardrail": "A finding is a question. Silence is not a clean book. Pulse does not become the accounting system.",
    }
