from datetime import datetime, timezone

import pytest

from sleepbot import crypto
from tests.conftest import FAST_KDF, PASSPHRASE

BED = datetime(2026, 10, 7, 15, 12, tzinfo=timezone.utc)
WAKE = datetime(2026, 10, 7, 22, 3, tzinfo=timezone.utc)


def test_correct_passphrase_decrypts():
    keys = crypto.create_user_keys(PASSPHRASE, FAST_KDF)
    blob = crypto.seal_times(keys.public_key, BED, WAKE)
    sk = crypto.unlock_private_key(PASSPHRASE, keys.encrypted_private_key, keys.kdf_salt, keys.kdf_params)
    assert crypto.open_times(sk, blob) == (BED, WAKE)


def test_wrong_passphrase_fails():
    keys = crypto.create_user_keys(PASSPHRASE, FAST_KDF)
    with pytest.raises(crypto.WrongPassphrase) as e:
        crypto.unlock_private_key("wrong passphrase", keys.encrypted_private_key, keys.kdf_salt, keys.kdf_params)
    # 例外メッセージに入力値が入らない
    assert "wrong passphrase" not in str(e.value)
    assert e.value.__cause__ is None


def test_other_users_key_cannot_open():
    alice = crypto.create_user_keys(PASSPHRASE, FAST_KDF)
    bob = crypto.create_user_keys(PASSPHRASE, FAST_KDF)
    blob = crypto.seal_times(alice.public_key, BED, WAKE)
    bob_sk = crypto.unlock_private_key(PASSPHRASE, bob.encrypted_private_key, bob.kdf_salt, bob.kdf_params)
    with pytest.raises(crypto.DecryptionFailed):
        crypto.open_times(bob_sk, blob)


def test_fullwidth_and_halfwidth_passphrase_are_same():
    keys = crypto.create_user_keys("ｓｌｅｅｐ１２３４", FAST_KDF)
    crypto.unlock_private_key("sleep1234", keys.encrypted_private_key, keys.kdf_salt, keys.kdf_params)


def test_ciphertext_is_randomized():
    keys = crypto.create_user_keys(PASSPHRASE, FAST_KDF)
    assert crypto.seal_times(keys.public_key, BED, WAKE) != crypto.seal_times(keys.public_key, BED, WAKE)
