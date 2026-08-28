# Grains Receipt Spec — `grains-receipt/0.1`

Status: v1 normative for `type: "payment"`. Types `"delivery"` and
`"satisfaction"` are **reserved** (sketched, non-normative) for the v2
receipt chain described in `docs/architecture.html`.

A receipt is a signed, **self-contained** JSON document: it embeds the
payee's identity document so it can be verified **offline** with no resolver,
no network, and no Grains service. Signing/canonicalization rules are
inherited from `spec/identity.md` §4–§5.

## 1. Payment receipt

Attests: value moved. Signed by the **payee** (the agent that was paid);
payment truth is anchored by the on-chain transaction reference, which any
verifier MAY additionally confirm against the chain.

```json
{
  "spec": "grains-receipt/0.1",
  "type": "payment",
  "id": "018f3c1e-0000-7000-8000-000000000001",
  "issued_at": "2026-08-23T00:00:00Z",
  "payee": "did:key:zQ3s…",
  "payer": null,
  "agent": "agents.grains.run/example",
  "task_id": "task_0001",
  "amount": {"value": "1.500000", "currency": "USDC", "decimals": 6},
  "fee": {"value": "0.075000", "recipient": "0x…platform…"},
  "rail": "x402:evm:base-sepolia",
  "tx": {"chain_id": 84532, "hash": "0x…"},
  "payee_identity": { …full signed identity document… },
  "sig": {"alg": "ES256K", "kid": "did:key:zQ3s…", "value": "…"}
}
```

Field rules:

- `id` — UUIDv7 string (sortable by issue time).
- `payer` — payer's DID if presented during payment, else `null`
  (x402 payments are pseudonymous by default; the on-chain `from` address is
  still discoverable via `tx`).
- `amount.value` — decimal string with exactly `decimals` fractional digits.
  Never a float. `currency` is a symbol; `rail` + `tx.chain_id` disambiguate
  the concrete asset.
- `fee` — the platform's settlement-time split, if any. `amount.value` is the
  **gross** amount paid by the payer; the payee received
  `amount − fee.value`.
- `rail` — `x402:evm:<network>` in v1. Networks: `base-sepolia`
  (chain_id 84532), `base` (8453, gated on legal review).
- `payee_identity` — the payee's complete identity document
  (`grains-identity/0.1`), including its own `sig`. Self-containment rule:
  a verifier needs nothing outside this receipt.
- `sig` — by the payee root key; `sig.kid` MUST equal `payee` MUST equal
  `payee_identity.did`.

## 2. Offline verification (`grains verify`)

1. Verify `payee_identity` per identity spec §7.
2. Check `payee == payee_identity.did == sig.kid`.
3. Canonicalize the receipt minus `sig`; verify `sig` against the DID's key.
4. Check `amount.value` well-formed for `decimals`; `issued_at` parses;
   `type` is known.
5. Result is `VERIFIED (offline)`. An optional online step MAY confirm
   `tx.hash` exists on `tx.chain_id`, moved ≥ `amount.value` of the asset,
   and involved the bound rail address — upgrading to `VERIFIED (settled)`.

A single-byte change anywhere in the receipt MUST fail step 1 or 3.

## 3. Reserved types (non-normative sketch)

- `"delivery"` — `{content_hash, spec_ref, task_id}`, signed by provider,
  countersigned by buyer (`sigs: []` list replaces `sig`).
- `"satisfaction"` — `{rating, notes, dispute_outcome?, refs: [payment_id,
  delivery_id]}`, signed by buyer (+ arbiter when disputed).
- Chain rule (v2): satisfaction references delivery references payment by
  `id`; a chain missing links is visibly incomplete.

## 4. Test vectors

`spec/tools/generate_vectors.py` emits `spec/vectors/payment_receipt.json`
signed with the public test key. `spec/tools/test_vectors.py` MUST pass:
the vector verifies per §2 steps 1–4, and tampering with any of
`amount.value`, `tx.hash`, `payee`, or one byte of either signature fails.
