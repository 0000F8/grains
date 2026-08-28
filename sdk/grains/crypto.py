"""grains-sdk crypto: identity (secp256k1 did:key) and receipt primitives.

Implements spec/identity.md and spec/receipts.md, matching
spec/tools/generate_vectors.py exactly. Requires the `crypto` extra
(`ecdsa`, `pycryptodome`); imports of those libraries are deferred into the
functions that need them so importing this module never requires them.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Callable

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_DID_PREFIX = "did:key:z"
_MULTICODEC_SECP256K1 = b"\xe7\x01"


def canonical(doc: dict) -> bytes:
    """Canonical signing bytes per spec/identity.md §4 (`sig` field removed)."""
    doc = {k: v for k, v in doc.items() if k != "sig"}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58_ALPHABET[r] + out
    pad = 0
    for b in data:
        if b == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def _b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_ALPHABET.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def pubkey_to_did(compressed: bytes) -> str:
    """secp256k1 compressed pubkey (33 bytes) -> did:key (spec/identity.md §2)."""
    return _DID_PREFIX + _b58encode(_MULTICODEC_SECP256K1 + compressed)


def did_to_pubkey(did: str) -> bytes:
    """did:key -> secp256k1 compressed pubkey (reverse of spec/identity.md §2)."""
    if not did.startswith(_DID_PREFIX):
        raise ValueError(f"not a did:key: {did!r}")
    decoded = _b58decode(did[len(_DID_PREFIX):])
    if decoded[:2] != _MULTICODEC_SECP256K1:
        raise ValueError("not a secp256k1-pub did:key")
    return decoded[2:]


def pubkey_to_evm_address(uncompressed: bytes) -> str:
    """secp256k1 uncompressed pubkey (65 bytes) -> EVM address (spec/identity.md §3)."""
    from Crypto.Hash import keccak

    k = keccak.new(digest_bits=256)
    k.update(uncompressed[1:])
    return "0x" + k.digest()[-20:].hex()


def sign_doc(doc: dict, signer: Callable[[bytes], bytes], did: str) -> dict:
    """Sign `doc` and return its `sig` object per spec/identity.md §5.

    `signer` receives the SHA-256 digest of the canonical bytes and must
    return a 64-byte r||s signature -- this is the shared call shape for
    both local (ecdsa) and KMS signing.
    """
    digest = hashlib.sha256(canonical(doc)).digest()
    raw = signer(digest)
    value = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return {"alg": "ES256K", "kid": did, "value": value}


def _verify_sig(doc: dict) -> "object | None":
    """Verify a document's `sig` against the key named by `sig.kid`.

    Returns the VerifyingKey on success, else None. Enforces strict low-s
    (§5, no signature malleability) and fails closed on any malformed input.
    Does NOT check who kid belongs to -- that binding is the caller's, and
    differs for identity docs (kid == did) vs receipts (kid == payee).
    """
    from ecdsa import BadSignatureError, SECP256k1, VerifyingKey
    from ecdsa.errors import MalformedPointError

    sig = doc.get("sig")
    if not isinstance(sig, dict) or sig.get("alg") != "ES256K":
        return None
    try:
        vk = VerifyingKey.from_string(did_to_pubkey(sig["kid"]), curve=SECP256k1)
        raw = base64.urlsafe_b64decode(sig["value"] + "=" * (-len(sig["value"]) % 4))
        if len(raw) != 64:
            return None
        if int.from_bytes(raw[32:], "big") > SECP256k1.order // 2:
            return None
        if not vk.verify(raw, canonical(doc), hashfunc=hashlib.sha256):
            return None
        return vk
    except (BadSignatureError, MalformedPointError, ValueError, KeyError, TypeError):
        return None


def verify_doc(doc: dict) -> bool:
    """Self-contained identity-document verification per spec/identity.md §7.

    Enforces: valid signature (§5, low-s); sig.kid == doc.did (step 2); and,
    for every rail binding claiming the root key, that the bound address
    re-derives from the signing key (step 3). Fails closed.
    """
    from ecdsa.errors import MalformedPointError

    # §7 step 2: the signer's key MUST be the document's own DID.
    if not isinstance(doc.get("sig"), dict) or doc["sig"].get("kid") != doc.get("did"):
        return False
    vk = _verify_sig(doc)
    if vk is None:
        return False

    # §7 step 3: a rail binding sharing the root key must match a re-derived
    # address, or a valid signature could still direct funds anywhere.
    try:
        expected = pubkey_to_evm_address(b"\x04" + vk.to_string("uncompressed")[-64:])
    except (MalformedPointError, ValueError):
        return False
    for binding in doc.get("bindings", []):
        if isinstance(binding, dict) and binding.get("type") == "rail":
            addr = binding.get("address")
            if isinstance(addr, str) and addr.lower() != expected.lower():
                return False
    return True


def verify_receipt(receipt: dict) -> tuple[bool, str]:
    """Offline verification per spec/receipts.md §2 steps 1-4."""
    payee_identity = receipt.get("payee_identity")
    if not isinstance(payee_identity, dict):
        return False, "missing payee_identity"
    if not verify_doc(payee_identity):
        return False, "payee_identity signature invalid"

    did = payee_identity.get("did")
    sig = receipt.get("sig") or {}
    if not (receipt.get("payee") == did == sig.get("kid")):
        return False, "payee / payee_identity.did / sig.kid mismatch"

    if _verify_sig(receipt) is None:
        return False, "receipt signature invalid"

    amount = receipt.get("amount") or {}
    value = amount.get("value")
    decimals = amount.get("decimals")
    if not isinstance(value, str) or not isinstance(decimals, int):
        return False, "amount malformed"
    whole, sep, frac = value.partition(".")
    if not sep or len(frac) != decimals or not frac.isdigit() or not whole.lstrip("-").isdigit():
        return False, "amount.value malformed for decimals"

    try:
        datetime.fromisoformat(str(receipt.get("issued_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return False, "issued_at malformed"

    if receipt.get("type") != "payment":
        return False, "unknown receipt type"

    return True, "VERIFIED (offline)"
