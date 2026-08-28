"""crypto.py round-trips against spec/vectors/*.json -- see spec/tools/generate_vectors.py."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from grains import crypto
from grains.crypto import verify_doc

VECTORS = Path(__file__).resolve().parents[2] / "spec" / "vectors"


def load(name):
    return json.loads((VECTORS / name).read_text())


def _local_signer(priv: bytes):
    from ecdsa import SECP256k1, SigningKey
    from ecdsa.util import sigencode_string_canonize

    sk = SigningKey.from_string(priv, curve=SECP256k1)

    def signer(digest: bytes) -> bytes:
        return sk.sign_digest_deterministic(
            digest, hashfunc=hashlib.sha256, sigencode=sigencode_string_canonize
        )

    return signer


def test_key_derivations_match_vector():
    keys = load("keys.json")
    compressed = bytes.fromhex(keys["public_key_compressed_hex"])
    uncompressed = bytes.fromhex(keys["public_key_uncompressed_hex"])
    assert crypto.pubkey_to_did(compressed) == keys["did"]
    assert crypto.did_to_pubkey(keys["did"]) == compressed
    assert crypto.pubkey_to_evm_address(uncompressed) == keys["evm_address"]


def test_sign_doc_matches_vector_exactly():
    keys = load("keys.json")
    priv = bytes.fromhex(keys["private_key_hex"])
    identity = load("identity_doc.json")
    unsigned = {k: v for k, v in identity.items() if k != "sig"}
    signed = crypto.sign_doc(unsigned, _local_signer(priv), keys["did"])
    assert signed == identity["sig"]


def test_identity_doc_verifies():
    identity = load("identity_doc.json")
    assert crypto.verify_doc(identity)
    assert identity["sig"]["kid"] == identity["did"]


def test_receipt_verifies_offline():
    receipt = load("payment_receipt.json")
    ok, reason = crypto.verify_receipt(receipt)
    assert ok, reason
    assert reason == "VERIFIED (offline)"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.__setitem__("did", d["did"][:-2] + "aa"),
        lambda d: d["sig"].__setitem__("value", d["sig"]["value"][:-2] + "AA"),
        lambda d: d["bindings"][0].__setitem__("address", "0x" + "0" * 40),
    ],
)
def test_identity_tamper_fails(mutate):
    identity = copy.deepcopy(load("identity_doc.json"))
    mutate(identity)
    assert not crypto.verify_doc(identity)


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
def test_receipt_tamper_fails(mutate):
    receipt = copy.deepcopy(load("payment_receipt.json"))
    mutate(receipt)
    ok, _reason = crypto.verify_receipt(receipt)
    assert not ok


def test_verify_doc_rejects_missing_sig():
    assert not crypto.verify_doc({"spec": "grains-identity/0.1"})


# --- security regression tests (review findings 2, 6, 7, 8) ---


def test_verify_doc_rejects_kid_did_mismatch():
    # finding 2: sig.kid must equal doc.did
    doc = copy.deepcopy(load("identity_doc.json"))
    doc["sig"]["kid"] = doc["did"][:-4] + "aaaa"
    assert verify_doc(doc) is False


def test_verify_doc_rejects_high_s():
    # finding 6: malleated high-s signature must fail
    from ecdsa import SECP256k1
    doc = copy.deepcopy(load("identity_doc.json"))
    raw = base64.urlsafe_b64decode(doc["sig"]["value"] + "==")
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:], "big")
    mall = r.to_bytes(32, "big") + (SECP256k1.order - s).to_bytes(32, "big")
    doc["sig"]["value"] = base64.urlsafe_b64encode(mall).rstrip(b"=").decode()
    assert verify_doc(doc) is False


def test_verify_doc_fails_closed_on_malformed_did():
    # finding 7: MalformedPointError must be caught -> False, not raise
    doc = copy.deepcopy(load("identity_doc.json"))
    doc["did"] = "did:key:zQ3sNOTAVALIDPOINT"
    doc["sig"]["kid"] = doc["did"]
    assert verify_doc(doc) is False


def test_verify_doc_rejects_bogus_rail_address():
    # finding 8: rail binding address must re-derive from the signing key
    from ecdsa import SECP256k1, SigningKey
    from ecdsa.util import sigencode_string_canonize
    from grains.crypto import sign_doc

    keys = load("keys.json")
    sk = SigningKey.from_string(bytes.fromhex(keys["private_key_hex"]), curve=SECP256k1)
    doc = copy.deepcopy(load("identity_doc.json"))
    for b in doc["bindings"]:
        if b["type"] == "rail":
            b["address"] = "0x000000000000000000000000000000000000dead"
    doc.pop("sig", None)

    def signer(digest):
        return sk.sign_digest_deterministic(
            digest, hashfunc=hashlib.sha256, sigencode=sigencode_string_canonize
        )

    doc["sig"] = sign_doc(doc, signer, keys["did"])
    assert verify_doc(doc) is False


def test_verify_doc_still_accepts_genuine():
    assert verify_doc(load("identity_doc.json")) is True
