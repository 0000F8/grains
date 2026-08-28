"""Spec conformance tests: vectors reproduce, verify, and fail on tamper."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from Crypto.Hash import keccak
from ecdsa import BadSignatureError, SECP256k1, VerifyingKey

VECTORS = Path(__file__).resolve().parent.parent / "vectors"


def load(name):
    return json.loads((VECTORS / name).read_text())


def canonical(doc: dict) -> bytes:
    doc = {k: v for k, v in doc.items() if k != "sig"}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def b58decode(s: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for ch in s:
        n = n * 58 + alphabet.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def did_to_pubkey(did: str) -> bytes:
    assert did.startswith("did:key:z")
    decoded = b58decode(did[len("did:key:z"):])
    assert decoded[:2] == b"\xe7\x01", "not a secp256k1-pub did:key"
    return decoded[2:]


def verify_sig(doc: dict) -> bool:
    sig = doc["sig"]
    assert sig["alg"] == "ES256K"
    pub = did_to_pubkey(sig["kid"])
    vk = VerifyingKey.from_string(pub, curve=SECP256k1)
    raw = base64.urlsafe_b64decode(sig["value"] + "=" * (-len(sig["value"]) % 4))
    assert len(raw) == 64
    try:
        return vk.verify(raw, canonical(doc), hashfunc=hashlib.sha256)
    except BadSignatureError:
        return False


def test_key_derivations():
    keys = load("keys.json")
    priv = hashlib.sha256(b"grains spec test vector key 1").digest()
    assert keys["private_key_hex"] == priv.hex()
    pub = did_to_pubkey(keys["did"])
    assert pub.hex() == keys["public_key_compressed_hex"]
    unc = bytes.fromhex(keys["public_key_uncompressed_hex"])
    k = keccak.new(digest_bits=256)
    k.update(unc[1:])
    assert keys["evm_address"] == "0x" + k.digest()[-20:].hex()
    assert keys["did"].startswith("did:key:zQ3s")


def test_identity_doc_verifies():
    identity = load("identity_doc.json")
    assert identity["spec"] == "grains-identity/0.1"
    assert identity["sig"]["kid"] == identity["did"]
    assert verify_sig(identity)
    rail = [b for b in identity["bindings"] if b["type"] == "rail"][0]
    assert rail["address"] == load("keys.json")["evm_address"]


def test_receipt_verifies_offline():
    receipt = load("payment_receipt.json")
    assert receipt["spec"] == "grains-receipt/0.1" and receipt["type"] == "payment"
    # spec/receipts.md §2 steps 1-4
    assert verify_sig(receipt["payee_identity"])
    assert receipt["payee"] == receipt["payee_identity"]["did"] == receipt["sig"]["kid"]
    assert verify_sig(receipt)
    amt = receipt["amount"]
    _whole, frac = amt["value"].split(".")
    assert len(frac) == amt["decimals"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["amount"].__setitem__("value", "9.999999"),
        lambda r: r["tx"].__setitem__("hash", "0x" + "cd" * 32),
        lambda r: r.__setitem__("payee", r["payee"][:-2] + "aa"),
        lambda r: r["sig"].__setitem__("value", r["sig"]["value"][:-2] + "AA"),
        lambda r: r["payee_identity"]["sig"].__setitem__(
            "value", r["payee_identity"]["sig"]["value"][:-2] + "AA"
        ),
    ],
)
def test_tamper_fails(mutate):
    receipt = copy.deepcopy(load("payment_receipt.json"))
    mutate(receipt)
    ok = True
    try:
        ok = (
            verify_sig(receipt["payee_identity"])
            and receipt["payee"] == receipt["payee_identity"]["did"] == receipt["sig"]["kid"]
            and verify_sig(receipt)
        )
    except Exception:
        ok = False
    assert not ok
