"""`grains init` -- scaffold grains_app.py + grains.toml for a target project."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from . import templates

_FRAMEWORK_PRIORITY = ("crewai", "langgraph", "langchain")
_DEP_NAME_SPLIT = re.compile(r"[<>=!~\[; ]")


def _dep_names_from_requirements(path: Path) -> set[str]:
    names = set()
    if not path.exists():
        return names
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name = _DEP_NAME_SPLIT.split(line, maxsplit=1)[0].strip().lower()
        if name:
            names.add(name)
    return names


def _dep_names_from_pyproject(path: Path) -> set[str]:
    names = set()
    if not path.exists():
        return names
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return names
    deps = list(data.get("project", {}).get("dependencies", []))
    deps.extend(data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
    for dep in deps:
        name = _DEP_NAME_SPLIT.split(dep, maxsplit=1)[0].strip().lower()
        if name and name != "python":
            names.add(name)
    return names


def detect_framework(target: Path) -> str:
    names = _dep_names_from_requirements(target / "requirements.txt")
    names |= _dep_names_from_pyproject(target / "pyproject.toml")
    for framework in _FRAMEWORK_PRIORITY:
        if framework in names:
            return framework
    if not names and (target / "package.json").exists():
        return "node"
    return "none"


def _sanitize_name(name: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower())
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "agent"


def cmd_init(args) -> int:
    target = Path(args.path).resolve()
    target.mkdir(parents=True, exist_ok=True)

    framework = args.template or detect_framework(target)
    app_filename = "grains_app.mjs" if framework == "node" else "grains_app.py"
    app_path = target / app_filename
    toml_path = target / "grains.toml"

    if not args.force:
        existing = [p.name for p in (app_path, toml_path) if p.exists()]
        if existing:
            print(f"refusing to overwrite existing file(s): {', '.join(existing)} (use --force)")
            return 1

    app_path.write_text(templates.render_app(framework))
    toml_path.write_text(templates.render_toml(_sanitize_name(target.name), framework))

    print(f"detected framework: {framework}")
    print(f"wrote {app_path}")
    print(f"wrote {toml_path}")
    return 0
