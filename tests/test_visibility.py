from sleepbot.privacy import Audience, Field, visible_fields
from tests.conftest import make_user


def test_private_user_hides_times_publicly(db):
    u = make_user(db, 1, share_times=False)
    assert visible_fields(u, Audience.PUBLIC) == {Field.DURATION}
    assert visible_fields(u, Audience.SELF) == {Field.DURATION, Field.TIMES}


def test_public_user_shows_times(db):
    u = make_user(db, 2, share_times=True)
    assert visible_fields(u, Audience.PUBLIC) == {Field.DURATION, Field.TIMES}


def test_default_is_duration_only(db):
    from sleepbot import crypto
    from tests.conftest import FAST_KDF

    k = crypto.create_user_keys("passphrase!", FAST_KDF)
    db.add_user(9, "x", k.public_key, k.encrypted_private_key, k.kdf_salt, k.kdf_params)
    assert db.get_user(9).share_times is False
