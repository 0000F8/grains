from __future__ import annotations

import json
from pathlib import Path

from grains_cli.main import main

VECTORS = Path(__file__).resolve().parent.parent.parent / "spec" / "vectors"


def test_verify_good_receipt(capsys):
    rc = main(["verify", str(VECTORS / "payment_receipt.json")])
    assert rc == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_verify_tampered_receipt(tmp_path, capsys):
    receipt = json.loads((VECTORS / "payment_receipt.json").read_text())
    receipt["amount"]["value"] = "9.999999"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(receipt))
    rc = main(["verify", str(p)])
    assert rc == 1
    assert "FAILED" in capsys.readouterr().err


def test_verify_missing_file(capsys):
    rc = main(["verify", "/nonexistent/receipt.json"])
    assert rc == 2
