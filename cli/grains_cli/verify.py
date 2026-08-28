"""`grains verify <receipt.json>` — offline payment-receipt verification.

Uses the SDK's self-contained verifier (spec/receipts.md §2). Prints the
verdict and exits non-zero on failure so it is scriptable. No network: the
receipt embeds the payee identity document and its trust anchor is the
payee's root did:key.
"""
from __future__ import annotations

import argparse
import json
import sys


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        receipt = json.loads(open(args.path, encoding="utf-8").read())
    except FileNotFoundError:
        print(f"error: no such file: {args.path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: {args.path} is not valid JSON ({e})", file=sys.stderr)
        return 2

    from grains.crypto import verify_receipt

    ok, reason = verify_receipt(receipt)
    if ok:
        amt = receipt.get("amount", {})
        print(
            f"VERIFIED (offline): {amt.get('value')} {amt.get('currency')} "
            f"to {receipt.get('payee', '')[:24]}… via {receipt.get('rail')}"
        )
        return 0
    print(f"FAILED: {reason}", file=sys.stderr)
    return 1
