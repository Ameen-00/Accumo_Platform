from accumo_ingest.mapping import suggest_all
from accumo_ingest.parse import parse_csv_bytes
from accumo_ingest.validate import needs_date_format, validate


def test_payment_file_suggests_and_validates_with_dmy():
    raw = b"Supplier Name,Paid,Date\nABC Traders,\"1,200.00\",03/07/2026\n"
    headers, rows = parse_csv_bytes(raw)
    mapping = suggest_all(headers, "payment")
    assert mapping["Supplier Name"] == "vendor.name"
    assert mapping["Paid"] == "payment.amount"
    assert mapping["Date"] == "payment.payment_date"
    assert needs_date_format(rows, mapping) is True
    assert validate(rows, mapping, "payment", None)
    assert validate(rows, mapping, "payment", "dmy") == []


def test_caps_errors_at_twenty_and_never_loads_half():
    lines = ["Invoice,Amount"] + [f",x{i}" for i in range(30)]
    raw = ("\n".join(lines)).encode()
    _headers, rows = parse_csv_bytes(raw)
    mapping = {"Invoice": "invoice.invoice_number", "Amount": "invoice.gross_amount"}
    errors = validate(rows, mapping, "invoice", "ymd")
    assert len(errors) == 20
