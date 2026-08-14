from accumo_ingest.parse import parse_csv_bytes


def test_strips_bom_and_blank_trailing_rows():
    raw = b"\xef\xbb\xbfSupplier Name,Amount,Date\nABC,100,2026-01-01\n\n\n"
    headers, rows = parse_csv_bytes(raw)
    assert headers == ["Supplier Name", "Amount", "Date"]
    assert len(rows) == 1
    assert rows[0]["Supplier Name"] == "ABC"


def test_skips_title_row_above_real_headers():
    raw = b"Company export\n\nVendor,Paid,Date\nX,10,2026-02-01\n"
    headers, rows = parse_csv_bytes(raw)
    assert headers == ["Vendor", "Paid", "Date"]
    assert len(rows) == 1
