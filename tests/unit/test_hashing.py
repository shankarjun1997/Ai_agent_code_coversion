def test_hash_password_not_plaintext():
    from core.auth.hashing import hash_password
    assert hash_password("secret") != "secret"

def test_verify_correct_password():
    from core.auth.hashing import hash_password, verify_password
    assert verify_password("correct", hash_password("correct")) is True

def test_verify_wrong_password():
    from core.auth.hashing import hash_password, verify_password
    assert verify_password("wrong", hash_password("correct")) is False
