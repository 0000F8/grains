"""`grains pay` -- 402 -> sign -> resubmit flow, driven in-process against the
control app's FastAPI TestClient (no network, no chain).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from eth_account import Account
from fastapi.testclient import TestClient
from grains_cli.pay import run_pay
from grains_control.app import create_app
from grains_control.config import Settings
from grains_control.models import agents as agents_t
from grains_control.models import payments as payments_t
from grains_control.models import users as users_t
from grains_control.services.keys import LocalKeyService

PAY_TO = "0x" + "55" * 20


def _make_client(tmp_path, *, x402_enabled=True):
    config = Settings(
        database_url=f"sqlite:///{tmp_path}/grains-test.db",
        session_secret="test-session-secret",
        github_client_id="x",
        github_client_secret="x",
        local_keys_dir=str(tmp_path / "keys"),
        artifact_dir=str(tmp_path / "artifacts"),
        x402_enabled=x402_enabled,
        x402_pay_to=PAY_TO,
    )
    keysvc = LocalKeyService(config.local_keys_dir)
    app = create_app(config=config, keysvc=keysvc)
    return TestClient(app, base_url="https://testserver")


def _insert_public_agent(client, name: str, price_value: str | None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with client.app.state.engine.begin() as conn:
        user_id = str(uuid.uuid4())
        conn.execute(
            sa.insert(users_t).values(
                id=user_id,
                github_id=hash(name) % 1_000_000,
                github_login=name,
                created_at=now,
            )
        )
        conn.execute(
            sa.insert(agents_t).values(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=name,
                did="did:key:ztest",
                identity_doc={},
                key_ref="test-key-ref",
                public=True,
                price_value=price_value,
                price_currency="USDC",
                tier="zip",
                status="active",
                created_at=now,
            )
        )


def test_pay_signs_and_resubmits_after_402(tmp_path):
    client = _make_client(tmp_path)
    _insert_public_agent(client, "priced-agent", price_value="1.50")
    payer_key = Account.create().key

    result = run_pay(
        "https://testserver", "priced-agent", payer_key, "hello", client=client
    )

    assert "task_id" in result, result
    with client.app.state.engine.begin() as conn:
        rows = conn.execute(sa.select(payments_t)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["status"] == "authorized"
    assert rows[0]["amount_atomic"] == "1500000"
    assert rows[0]["payer_address"] == Account.from_key(payer_key).address.lower()


def test_pay_free_agent_needs_no_payment(tmp_path):
    client = _make_client(tmp_path)
    _insert_public_agent(client, "free-agent", price_value=None)
    payer_key = Account.create().key

    result = run_pay("https://testserver", "free-agent", payer_key, "hello", client=client)

    assert "task_id" in result, result
    with client.app.state.engine.begin() as conn:
        count = conn.execute(sa.select(sa.func.count()).select_from(payments_t)).scalar_one()
    assert count == 0


def test_pay_reports_error_on_unknown_agent(tmp_path):
    client = _make_client(tmp_path)
    payer_key = Account.create().key

    result = run_pay("https://testserver", "nope", payer_key, "hello", client=client)

    assert "error" in result
    assert result["status_code"] == 404


def test_cmd_pay_prints_task_id(tmp_path, capsys, monkeypatch):
    client = _make_client(tmp_path)
    _insert_public_agent(client, "priced-agent-2", price_value="0.50")
    payer_key = Account.create().key

    import grains_cli.pay as pay_module

    monkeypatch.setattr(pay_module, "run_pay", lambda *a, **kw: {"task_id": "abc123"})

    from grains_cli.main import main

    rc = main(
        [
            "pay",
            "https://testserver",
            "priced-agent-2",
            "--key",
            payer_key.hex(),
            "--text",
            "hello",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "abc123"
