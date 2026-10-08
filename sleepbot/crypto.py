"""入眠・起床時刻の暗号化。

- ユーザーごとに X25519 の鍵ペアを作る
- 秘密鍵はパスフレーズから Argon2id で導出した鍵（SecretBox）で暗号化して保存する
- 時刻は公開鍵で SealedBox 暗号化する。書き込みにパスフレーズは要らず、読むときだけ要る

パスフレーズ・秘密鍵・復号結果は例外メッセージにも含めない。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from nacl import pwhash, secret, utils
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox


class WrongPassphrase(Exception):
    """パスフレーズが違う（または暗号文が壊れている）。理由の詳細は持たない。"""

    def __init__(self) -> None:
        super().__init__("passphrase rejected")


class DecryptionFailed(Exception):
    def __init__(self) -> None:
        super().__init__("decryption failed")


@dataclass(frozen=True)
class KdfParams:
    opslimit: int
    memlimit: int
    alg: str = "argon2id13"

    def to_json(self) -> str:
        return json.dumps({"alg": self.alg, "opslimit": self.opslimit, "memlimit": self.memlimit})

    @classmethod
    def from_json(cls, raw: str) -> KdfParams:
        d = json.loads(raw)
        if d.get("alg") != "argon2id13":
            raise ValueError("unsupported kdf")
        return cls(opslimit=int(d["opslimit"]), memlimit=int(d["memlimit"]))


# 64MiB / ops=3。小さめのサーバー（Railway 等）でも動く範囲で重くしている
DEFAULT_KDF = KdfParams(
    opslimit=pwhash.argon2id.OPSLIMIT_MODERATE,
    memlimit=pwhash.argon2id.MEMLIMIT_INTERACTIVE,
)

MIN_PASSPHRASE_LENGTH = 8


@dataclass(frozen=True)
class UserKeys:
    public_key: bytes
    encrypted_private_key: bytes
    kdf_salt: bytes
    kdf_params: str


def _normalize(passphrase: str) -> bytes:
    # 全角・半角や合成文字の揺れで復号できなくなるのを防ぐ
    return unicodedata.normalize("NFKC", passphrase).encode("utf-8")


def _derive_key(passphrase: str, salt: bytes, params: KdfParams) -> bytes:
    return pwhash.argon2id.kdf(
        secret.SecretBox.KEY_SIZE,
        _normalize(passphrase),
        salt,
        opslimit=params.opslimit,
        memlimit=params.memlimit,
    )


def create_user_keys(passphrase: str, params: KdfParams = DEFAULT_KDF) -> UserKeys:
    """鍵ペアを作り、秘密鍵をパスフレーズで包んで返す。重いのでスレッドで呼ぶこと。"""
    private_key = PrivateKey.generate()
    salt = utils.random(pwhash.argon2id.SALTBYTES)
    box = secret.SecretBox(_derive_key(passphrase, salt, params))
    return UserKeys(
        public_key=bytes(private_key.public_key),
        encrypted_private_key=bytes(box.encrypt(bytes(private_key))),
        kdf_salt=salt,
        kdf_params=params.to_json(),
    )


def unlock_private_key(
    passphrase: str, encrypted_private_key: bytes, kdf_salt: bytes, kdf_params: str
) -> PrivateKey:
    """パスフレーズで秘密鍵を取り出す。違えば WrongPassphrase。重いのでスレッドで呼ぶこと。"""
    params = KdfParams.from_json(kdf_params)
    box = secret.SecretBox(_derive_key(passphrase, kdf_salt, params))
    try:
        raw = box.decrypt(encrypted_private_key)
    except CryptoError:
        raise WrongPassphrase() from None
    return PrivateKey(raw)


def _to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(timezone.utc).isoformat()


def seal_times(public_key: bytes, bedtime_utc: datetime, waketime_utc: datetime) -> bytes:
    payload = json.dumps({"bed": _to_utc_iso(bedtime_utc), "wake": _to_utc_iso(waketime_utc)})
    return bytes(SealedBox(PublicKey(public_key)).encrypt(payload.encode()))


def open_times(private_key: PrivateKey, blob: bytes) -> tuple[datetime, datetime]:
    try:
        payload = json.loads(SealedBox(private_key).decrypt(blob))
    except CryptoError:
        raise DecryptionFailed() from None
    return datetime.fromisoformat(payload["bed"]), datetime.fromisoformat(payload["wake"])
