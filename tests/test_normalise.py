from accumo_canonical.normalise import digits_only, normalise_invoice, normalise_name, normalise_tax_id


def test_invoice_strips_separators():
    assert normalise_invoice("INV/2026/0412") == "INV20260412"
    assert normalise_invoice("INV-2026-412") == "INV2026412"


def test_invoice_is_case_insensitive():
    assert normalise_invoice("inv 2026 0412") == "INV20260412"


def test_invoice_drops_padding_zeros_after_letters():
    assert normalise_invoice("INV000412") == "INV412"


def test_name_strips_indian_and_gulf_suffixes():
    assert normalise_name("ABC Traders Pvt Ltd") == "ABC"
    assert normalise_name("ABC Trading FZE") == "ABC"
    assert normalise_name("Al Noor Establishment") == "AL NOOR"


def test_name_strips_accents():
    assert normalise_name("Café LLC") == "CAFE"


def test_tax_id_normalises_gstin_and_trn():
    assert normalise_tax_id("32AABC S1234 A1Z5") == "32AABCS1234A1Z5"
    assert normalise_tax_id("100123456700003") == "100123456700003"


def test_digits_only_iban():
    assert digits_only("AE07 0331 2345 6789 0123 456") == "070331234567890123456"
