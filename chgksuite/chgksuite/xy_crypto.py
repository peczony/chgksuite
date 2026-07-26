"""Client-side crypto for xy boards (https://xy.pecheny.me).

A faithful Python port of xy's ``crypto.js`` envelope + board-key lifecycle, so
chgksuite can decrypt an xy board's ciphertext fields locally with the board
passphrase (and encrypt on upload). xy is end-to-end encrypted: its
Trello-compatible API returns every text field as a base64 ciphertext envelope
plus the per-board key-derivation material (``keymeta``); the server never sees
plaintext or the passphrase.

Envelope (bytes, base64 over the wire):
    magic "xy1" (3) | alg (1) = 1 (AES-256-GCM) | nonce (12) | ciphertext+tag

Key lifecycle:
    KEK = scrypt(passphrase NFKC, kdf_salt, kdf_params)        # wraps DK only
    DK  = AES-GCM-open(KEK, wrapped_key)                       # 32-byte data key
    verify_token = AES-GCM-seal(DK, "xy-verify-v1")            # passphrase check
    field plaintext = AES-GCM-open(DK, field_envelope)
"""

import base64
import hashlib
import json
import os
import unicodedata

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"xy1"
ALG_AES_GCM = 1
NONCE_LEN = 12
HEADER_LEN = len(MAGIC) + 1 + NONCE_LEN  # 16
VERIFY_PLAINTEXT = "xy-verify-v1"


class WrongPassphrase(Exception):
    """Raised when the board passphrase fails to unwrap/verify the data key."""


def _b64d(s):
    return base64.b64decode(s)


def _b64e(b):
    return base64.b64encode(b).decode("ascii")


def _derive_kek(passphrase, salt, params):
    pw = unicodedata.normalize("NFKC", passphrase).encode("utf-8")
    n = int(params.get("N", 32768))
    r = int(params.get("r", 8))
    p = int(params.get("p", 1))
    dklen = int(params.get("dkLen", 32))
    # scrypt needs 128*r*N bytes; give headroom so OpenSSL's maxmem check passes.
    maxmem = 128 * r * n * 2
    return hashlib.scrypt(pw, salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=maxmem)


def _open(key, envelope):
    if len(envelope) < HEADER_LEN:
        raise ValueError("envelope too short")
    if envelope[: len(MAGIC)] != MAGIC:
        raise ValueError("bad envelope magic")
    if envelope[len(MAGIC)] != ALG_AES_GCM:
        raise ValueError("unknown envelope alg")
    nonce = envelope[len(MAGIC) + 1 : HEADER_LEN]
    ct = envelope[HEADER_LEN:]
    return AESGCM(key).decrypt(nonce, ct, None)


def _seal(key, plaintext, nonce=None):
    if nonce is None:
        nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return MAGIC + bytes([ALG_AES_GCM]) + nonce + ct


def derive_dk(passphrase, keymeta):
    """Derive and verify the 32-byte data key from a passphrase + keymeta dict.

    keymeta keys: kdf_salt, kdf_params (JSON string), wrapped_key, verify_token
    (all base64). Raises WrongPassphrase on a bad passphrase.
    """
    params = json.loads(keymeta["kdf_params"])
    salt = _b64d(keymeta["kdf_salt"])
    kek = _derive_kek(passphrase, salt, params)
    try:
        dk_raw = _open(kek, _b64d(keymeta["wrapped_key"]))
    except Exception as e:
        raise WrongPassphrase("Неверный пароль доски") from e
    try:
        verify = _open(dk_raw, _b64d(keymeta["verify_token"]))
        if verify.decode("utf-8") != VERIFY_PLAINTEXT:
            raise ValueError("verify mismatch")
    except WrongPassphrase:
        raise
    except Exception as e:
        raise WrongPassphrase("Неверный пароль доски") from e
    return dk_raw


def decrypt_field(dk_raw, b64_envelope):
    """Decrypt a base64 ciphertext envelope to a string. Empty input → ""."""
    if not b64_envelope:
        return ""
    return _open(dk_raw, _b64d(b64_envelope)).decode("utf-8")


def encrypt_field(dk_raw, text):
    """Encrypt a string into a base64 ciphertext envelope."""
    return _b64e(_seal(dk_raw, (text or "").encode("utf-8")))
