from accumo_ingest.mapping import suggest


def test_suggests_tax_id_from_gstin_or_trn():
    assert suggest("GSTIN") == "vendor.tax_id"
    assert suggest("TRN") == "vendor.tax_id"
    assert suggest("Supplier Name") == "vendor.name"
