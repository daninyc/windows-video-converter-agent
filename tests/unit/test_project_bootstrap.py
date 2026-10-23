import socket
import subprocess
import sys
import tomllib

import pytest

from media_converter.config import AppPaths, application_root

pytestmark = pytest.mark.unit


def test_paths_and_dependency_boundaries(tmp_path):
    assert AppPaths.from_argument().data_dir == application_root() / "data"
    assert AppPaths.from_argument(tmp_path).ensure().data_dir == tmp_path.resolve()
    config = tomllib.loads((application_root() / "pyproject.toml").read_text("utf-8"))
    assert set(config["project"]["optional-dependencies"]) == {"tools", "cpu-rerank", "dev"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import media_converter.__main__,sys; "
            "assert 'torch' not in sys.modules; assert 'mcp' not in sys.modules",
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_cli_rejects_future_commands():
    result = subprocess.run(
        [sys.executable, "-m", "media_converter.devtools", "not-implemented"],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0


def test_online_requests_default_off():
    with pytest.raises(RuntimeError, match="默认禁止"):
        socket.getaddrinfo("api.deepseek.com", 443)


def test_dev_lock_pins_installed_closure_and_cpu_source():
    import importlib.metadata as metadata

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    locked = {}
    for line in (application_root() / "requirements-dev.lock").read_text("utf-8").splitlines():
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line)
        locked[canonicalize_name(requirement.name)] = requirement
        installed = metadata.version(requirement.name)
        if requirement.url:
            assert requirement.name == "torch" and installed.endswith("+cpu")
            assert requirement.url.startswith("https://download-r2.pytorch.org/whl/cpu/")
            assert "#sha256=" in requirement.url
        else:
            assert str(requirement.specifier) == f"=={installed}"
    visited = set()

    def check(name, extras=()):
        key = (canonicalize_name(name), tuple(sorted(extras)))
        if key in visited:
            return
        visited.add(key)
        assert key[0] in locked
        for raw in metadata.distribution(name).requires or ():
            requirement = Requirement(raw)
            if requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra}) for extra in ("", *extras)
            ):
                check(requirement.name, requirement.extras)

    config = tomllib.loads((application_root() / "pyproject.toml").read_text("utf-8"))
    dependencies = config["project"]["dependencies"][:]
    for group in config["project"]["optional-dependencies"].values():
        dependencies += group
    for dependency in dependencies:
        check(Requirement(dependency).name)
