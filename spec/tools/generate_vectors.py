"""Generate spec test vectors into spec/vectors/.

Deterministic: fixed test key, fixed timestamps/ids, RFC 6979 signatures.
The test key is PUBLIC — never use it for anything real.
"""
import hashlib
import json
from pathlib import Path

from Crypto.Hash import keccak
from ecdsa import SECP256k1, SigningKey
from ecdsa.util import sigencode_string_canonize

VECTORS = Path(__file__).resolve().parent.parent / "vectors"
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Fixed, publicly-known test key: sha256 of a documented phrase.
TEST_PRIV = hashlib.sha256(b"grains spec test vector key 1").digest()
FIXED_TS = "2026-08-23T00:00:00Z"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58_ALPHABET[r] + out
    pad = 0
    for b in data:
        if b == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def canonical(doc: dict) -> bytes:
    doc = {k: v for k, v in doc.items() if k != "sig"}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def make_keys():
    sk = SigningKey.from_string(TEST_PRIV, curve=SECP256k1)
    vk = sk.get_verifying_key()
    compressed = vk.to_string("compressed")
    uncompressed = vk.to_string("uncompressed")
    did = "did:key:z" + b58encode(b"\xe7\x01" + compressed)
    k = keccak.new(digest_bits=256)
    k.update(uncompressed[1:])
    address = "0x" + k.digest()[-20:].hex()
    return sk, compressed, uncompressed, did, address


def sign(sk: SigningKey, doc: dict, did: str) -> dict:
    sig = sk.sign_deterministic(
        canonical(doc), hashfunc=hashlib.sha256, sigencode=sigencode_string_canonize
    )
    import base64
    return {"alg": "ES256K", "kid": did, "value": base64.urlsafe_b64encode(sig).rstrip(b"=").decode()}


def main():
    VECTORS.mkdir(parents=True, exist_ok=True)
    sk, compressed, uncompressed, did, address = make_keys()

    keys = {
        "comment": "PUBLIC test key - sha256(b'grains spec test vector key 1'). Never use for real funds or identity.",
        "private_key_hex": TEST_PRIV.hex(),
        "public_key_compressed_hex": compressed.hex(),
        "public_key_uncompressed_hex": uncompressed.hex(),
        "did": did,
        "evm_address": address,
    }

    identity = {
        "spec": "grains-identity/0.1",
        "did": did,
        "version": 1,
        "created_at": FIXED_TS,
        "bindings": [
            {"type": "rail", "rail": "evm:base-sepolia", "address": address},
            {"type": "venue", "venue": "grains", "endpoint": "agents.grains.run/example"},
        ],
    }
    identity["sig"] = sign(sk, identity, did)

    receipt = {
        "spec": "grains-receipt/0.1",
        "type": "payment",
        "id": "018f3c1e-0000-7000-8000-000000000001",
        "issued_at": FIXED_TS,
        "payee": did,
        "payer": None,
        "agent": "agents.grains.run/example",
        "task_id": "task_0001",
        "amount": {"value": "1.500000", "currency": "USDC", "decimals": 6},
        "fee": {"value": "0.075000", "recipient": "0x0000000000000000000000000000000000000fee"},
        "rail": "x402:evm:base-sepolia",
        "tx": {"chain_id": 84532, "hash": "0x" + "ab" * 32},
        "payee_identity": identity,
    }
    receipt["sig"] = sign(sk, receipt, did)

    for name, doc in [("keys.json", keys), ("identity_doc.json", identity), ("payment_receipt.json", receipt)]:
        (VECTORS / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {VECTORS / name}")


if __name__ == "__main__":
    main()
