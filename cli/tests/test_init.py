import tomllib

import pytest
from grains_cli.init import cmd_init, detect_framework
from grains_cli.main import build_parser
from grains_cli.templates import render_app

FRAMEWORKS = ["crewai", "langgraph", "langchain", "none"]


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


@pytest.mark.parametrize(
    ("dep_file", "content", "expected"),
    [
        ("requirements.txt", "crewai==0.80.0\n", "crewai"),
        ("requirements.txt", "langgraph>=0.2\n", "langgraph"),
        ("requirements.txt", "langchain\n", "langchain"),
        ("requirements.txt", "requests==2.31.0\n", "none"),
    ],
)
def test_detect_framework_from_requirements(tmp_path, dep_file, content, expected):
    (tmp_path / dep_file).write_text(content)
    assert detect_framework(tmp_path) == expected


def test_detect_framework_priority_crewai_over_langgraph_and_langchain(tmp_path):
    (tmp_path / "requirements.txt").write_text("langchain\nlanggraph\ncrewai\n")
    assert detect_framework(tmp_path) == "crewai"


def test_detect_framework_priority_langgraph_over_langchain(tmp_path):
    (tmp_path / "requirements.txt").write_text("langchain\nlanggraph\n")
    assert detect_framework(tmp_path) == "langgraph"


def test_detect_framework_from_pyproject_dependencies(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["crewai>=1.0"]\n'
    )
    assert detect_framework(tmp_path) == "crewai"


def test_detect_framework_none_with_no_dep_files(tmp_path):
    assert detect_framework(tmp_path) == "none"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_init_generates_parseable_files_for_each_template(tmp_path, framework):
    project = tmp_path / framework
    project.mkdir()
    rc = _run_init(project, template=framework)
    assert rc == 0

    app_path = project / "grains_app.py"
    toml_path = project / "grains.toml"
    assert app_path.exists()
    assert toml_path.exists()

    compile(app_path.read_text(), str(app_path), "exec")

    config = tomllib.loads(toml_path.read_text())
    assert config["agent"]["entrypoint"] == "grains_app:handle"
    assert config["agent"]["runtime"] == "python3.12"
    assert config["agent"]["public"] is False
    assert config["secrets"]["names"] == []
    assert config["egress"]["allow"] == []


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_generated_wrapper_is_at_most_25_lines(framework):
    assert len(render_app(framework).splitlines()) <= 25


def test_init_refuses_to_overwrite_without_force(tmp_path):
    rc = _run_init(tmp_path)
    assert rc == 0
    rc = _run_init(tmp_path)
    assert rc == 1
    # original content untouched
    assert "echo" in (tmp_path / "grains_app.py").read_text()


def test_init_force_overwrites(tmp_path):
    _run_init(tmp_path, template="none")
    _run_init(tmp_path, template="crewai", force=True)
    assert "kickoff" in (tmp_path / "grains_app.py").read_text()


def test_init_sanitizes_agent_name(tmp_path):
    project = tmp_path / "My Cool_Agent!!"
    project.mkdir()
    _run_init(project)
    config = tomllib.loads((project / "grains.toml").read_text())
    assert config["agent"]["name"] == "my-cool-agent"


def test_init_creates_target_directory(tmp_path):
    project = tmp_path / "nested" / "dir"
    rc = _run_init(project)
    assert rc == 0
    assert (project / "grains_app.py").exists()
