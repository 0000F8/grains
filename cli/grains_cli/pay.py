"""`grains pay` -- payer-side x402 test client.

Submits a task to a (possibly priced) agent. If the agent charges and the
server responds 402, signs an EIP-3009 TransferWithAuthorization with a local
private key matching the challenge's payTo/amount/asset and resubmits with the
X-PAYMENT header. This is the payer half of M4a's offline x402 core -- the
harness a human/agent uses to pay a priced Grains agent (and the fixture M4b's
live test drives).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx
from eth_account import Account

_TRANSFER_WITH_AUTHORIZATION_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ],
}


def _domain_for(accepts: dict) -> dict:
    # network is a CAIP-2 id, e.g. "eip155:84532".
    chain_id = int(accepts["network"].split(":")[-1])
    return {
        "name": "USD Coin",
        "version": "2",
        "chainId": chain_id,
        "verifyingContract": accepts["asset"],
    }


def build_payment_header(challenge: dict, private_key: str) -> str:
    """Sign an EIP-3009 TransferWithAuthorization matching `challenge` and
    return the JSON string to send as the X-PAYMENT header.
    """
    accepts = challenge["accepts"][0]
    account = Account.from_key(private_key)
    now = int(time.time())
    auth = {
        "from": account.address,
        "to": accepts["payTo"],
        "value": accepts["amount"],
        "validAfter": "0",
        "validBefore": str(now + int(accepts.get("maxTimeoutSeconds", 60))),
        "nonce": "0x" + os.urandom(32).hex(),
    }
    full_message = {
        "types": _TRANSFER_WITH_AUTHORIZATION_TYPES,
        "primaryType": "TransferWithAuthorization",
        "domain": _domain_for(accepts),
        "message": {
            "from": auth["from"],
            "to": auth["to"],
            "value": int(auth["value"]),
            "validAfter": int(auth["validAfter"]),
            "validBefore": int(auth["validBefore"]),
            "nonce": auth["nonce"],
        },
    }
    signed = Account.sign_typed_data(private_key, full_message=full_message)
    payment_payload = {
        "x402Version": challenge.get("x402Version", 2),
        "accepted": accepts,
        "payload": {
            "signature": "0x" + signed.signature.hex().removeprefix("0x"),
            "authorization": auth,
        },
    }
    return json.dumps(payment_payload)


def run_pay(
    api_url: str,
    agent: str,
    private_key: str,
    text: str,
    *,
    caller_token: str | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Submit a task, paying via x402 if the server challenges. Returns
    {"task_id": ...} on success, {"error": ..., "status_code": ...} otherwise.

    `client` is any httpx.Client-compatible object (real httpx.Client, or a
    FastAPI TestClient for in-process testing); when omitted a real
    httpx.Client is created against `api_url`.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(base_url=api_url)
    try:
        path = f"/agents/{agent}/tasks"
        headers = {}
        if caller_token:
            headers["Authorization"] = f"Bearer {caller_token}"

        resp = client.post(path, json={"text": text}, headers=headers)
        if resp.status_code == 402:
            challenge = resp.json()
            headers = dict(headers)
            headers["X-PAYMENT"] = build_payment_header(challenge, private_key)
            resp = client.post(path, json={"text": text}, headers=headers)

        if resp.status_code == 202:
            return {"task_id": resp.json()["task_id"]}
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        return {"error": detail, "status_code": resp.status_code}
    finally:
        if owns_client:
            client.close()


def cmd_pay(args: argparse.Namespace) -> int:
    key = args.key or os.environ.get("GRAINS_PAYER_KEY")
    if not key:
        print("error: provide --key or set GRAINS_PAYER_KEY", file=sys.stderr)
        return 2
    result = run_pay(
        args.api_url,
        args.agent,
        key,
        args.text,
        caller_token=args.caller_token,
    )
    if "task_id" in result:
        print(result["task_id"])
        return 0
    print(f"error ({result.get('status_code')}): {result['error']}", file=sys.stderr)
    return 1
