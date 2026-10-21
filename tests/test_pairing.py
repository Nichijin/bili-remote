from desktop.pairing import PairingCode


def test_code_is_not_persisted_and_expired_code_is_rejected(monkeypatch):
    values = iter((123456, 987654))
    monkeypatch.setattr("desktop.pairing.secrets.randbelow", lambda maximum: next(values))
    pairing = PairingCode()
    assert pairing.verify("123456")
    assert not pairing.verify("１２３４５６")
    pairing.deadline = 0
    assert not pairing.verify("123456")
    assert pairing.verify("987654")
