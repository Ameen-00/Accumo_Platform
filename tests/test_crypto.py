from accumo_foundation.crypto import account_hmac, decrypt_account, encrypt_account, mask_account


def test_hmac_is_stable_and_not_plaintext():
    a = account_hmac("123456789012")
    b = account_hmac("1234 5678 9012")
    assert a == b
    assert a != "123456789012"
    assert len(a) == 64


def test_encrypt_roundtrip_and_mask():
    token = encrypt_account("123456789012")
    assert token != "123456789012"
    assert decrypt_account(token) == "123456789012"
    assert mask_account("123456789012") == "••••9012"
