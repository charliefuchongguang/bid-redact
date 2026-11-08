from __future__ import annotations

from app.rules.checks import gb11643_valid, luhn_valid, verify


def test_gb11643_valid_examples():
    assert gb11643_valid("11010519491231002X")
    assert gb11643_valid("110105194912310021") is False


def test_gb11643_rejects_bad_length_and_letters():
    assert not gb11643_valid("123")
    assert not gb11643_valid("ABCDEFGHIJKLMNOPQR")


def test_luhn_valid_known_numbers():
    assert luhn_valid("4111111111111111")
    assert luhn_valid("4111 1111 1111 1111")
    assert not luhn_valid("4111111111111112")


def test_not_gb11643_rejects_id_numbers():
    assert verify("not_gb11643", "11010519491231002X") is False
    assert verify("not_gb11643", "42050164660800000249") is True