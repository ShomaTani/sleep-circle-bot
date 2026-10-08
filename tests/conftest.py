import pytest
from nacl import pwhash

from sleepbot import crypto
from sleepbot.db import Database

# テストでは Argon2id を最小パラメータにして速くする
FAST_KDF = crypto.KdfParams(opslimit=pwhash.argon2id.OPSLIMIT_MIN, memlimit=pwhash.argon2id.MEMLIMIT_MIN)
PASSPHRASE = "correct horse battery"


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    yield d
    d.close()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


def make_user(db, discord_id, share_times, passphrase=PASSPHRASE):
    keys = crypto.create_user_keys(passphrase, FAST_KDF)
    db.add_user(discord_id, f"user{discord_id}", keys.public_key, keys.encrypted_private_key, keys.kdf_salt, keys.kdf_params)
    db.set_share_times(discord_id, share_times)
    return db.get_user(discord_id)
