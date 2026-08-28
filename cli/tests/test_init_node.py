"""`grains init --template node` scaffolds a valid grains_app.mjs + grains.toml
for JS/Node agents -- mirrors test_init.py's coverage of the Python templates.
"""
from __future__ import annotations

import shutil
import subprocess
import tomllib

import pytest
from grains_cli.init import cmd_init, detect_framework
from grains_cli.main import build_parser
from grains_cli.templates import render_app


def _parse_init(argv):
    return build_parser().parse_args(["init", *argv])


def _run_init(tmp_path, **extra_argv):
    argv = [str(tmp_path)]
    for flag, value in extra_argv.items():
        if value is True:
            argv.append(f"--{flag}")
        elif value is not None:
            argv.extend([f"--{flag}", str(value)])
    return cmd_init(_parse_init(argv))


def test_node_is_a_valid_template_choice():
    args = _parse_init([".", "--template", "node"])
    assert args.template == "node"


def test_init_generates_node_app_and_toml(tmp_path):
    rc = _run_init(tmp_path, template="node")
    assert rc == 0

    app_path = tmp_path / "grains_app.mjs"
    toml_path = tmp_path / "grains.toml"
    assert app_path.exists()
    assert toml_path.exists()
    assert not (tmp_path / "grains_app.py").exists()

    config = tomllib.loads(toml_path.read_text())
    assert config["agent"]["entrypoint"] == "grains_app:handle"
    assert config["agent"]["runtime"] == "nodejs20.x"
    assert config["agent"]["public"] is False
    assert config["secrets"]["names"] == []
    assert config["egress"]["allow"] == []


def test_node_wrapper_is_at_most_25_lines():
    assert len(render_app("node").splitlines()) <= 25


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_generated_node_app_parses_with_node_check(tmp_path):
    _run_init(tmp_path, template="node")
    app_path = tmp_path / "grains_app.mjs"
    result = subprocess.run(
        ["node", "--check", str(app_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_detect_framework_node_from_package_json_with_no_python_deps(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x"}\n')
    assert detect_framework(tmp_path) == "node"


def test_detect_framework_prefers_python_deps_over_node(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x"}\n')
    (tmp_path / "requirements.txt").write_text("crewai==0.80.0\n")
    assert detect_framework(tmp_path) == "crewai"


def test_detect_framework_none_when_no_package_json_and_no_python_deps(tmp_path):
    assert detect_framework(tmp_path) == "none"


def test_init_force_overwrite_from_python_to_node(tmp_path):
    _run_init(tmp_path, template="none")
    assert (tmp_path / "grains_app.py").exists()
    _run_init(tmp_path, template="node", force=True)
    assert (tmp_path / "grains_app.mjs").exists()
    config = tomllib.loads((tmp_path / "grains.toml").read_text())
    assert config["agent"]["runtime"] == "nodejs20.x"
