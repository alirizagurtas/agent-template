"""Tests for the project structure synchronization script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import yaml

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "sync_project_structure.py"


def create_project(tmp_path: Path) -> Path:
    """Create a minimal project configured for synchronization."""
    configuration = """version: 1
package: sample
paths:
  source: source/sample
  unit_tests: tests/unit
  integration_tests: tests/integration
domains: {}
"""
    (tmp_path / "source" / "sample").mkdir(parents=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "integration").mkdir(parents=True)
    (tmp_path / "project_structure.yaml").write_text(configuration, encoding="utf-8")
    return tmp_path


def run_script(project_root: Path, option: str) -> subprocess.CompletedProcess[str]:
    """Run the synchronization script as a separate process."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), option],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
    )


def load_domains(project_root: Path) -> dict[str, object]:
    """Read the serialized domains mapping."""
    loaded = cast(
        object,
        yaml.safe_load((project_root / "project_structure.yaml").read_text(encoding="utf-8")),
    )
    configuration = cast(dict[object, object], loaded)
    domains = configuration["domains"]
    assert isinstance(domains, dict)
    return cast(dict[str, object], domains)


def write_source(project_root: Path, relative_path: str, contents: str = "") -> None:
    """Write one source fixture file."""
    path = project_root / "source" / "sample" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_empty_source_root_writes_empty_domains(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)

    result = run_script(project_root, "--write")

    assert result.returncode == 0
    assert load_domains(project_root) == {}


def test_discovers_domain_without_init_file(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py")

    result = run_script(project_root, "--write")

    assert result.returncode == 0
    assert load_domains(project_root)["orders"] == {
        "source": "source/sample/orders",
        "unit_tests": [],
        "integration_tests": [],
        "depends_on": [],
    }


def test_ignores_empty_directory(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    (project_root / "source" / "sample" / "empty").mkdir()

    run_script(project_root, "--write")

    assert load_domains(project_root) == {}


def test_ignores_hidden_directory(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, ".hidden/service.py")

    run_script(project_root, "--write")

    assert load_domains(project_root) == {}


def test_ignores_cache_only_directory(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "cache/__pycache__/service.py")

    run_script(project_root, "--write")

    assert load_domains(project_root) == {}


def test_ignores_bytecode_only_directory(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    bytecode = project_root / "source" / "sample" / "compiled" / "service.pyc"
    bytecode.parent.mkdir(parents=True)
    bytecode.write_bytes(b"bytecode")

    run_script(project_root, "--write")

    assert load_domains(project_root) == {}


def test_indexes_unit_and_integration_tests(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py")
    unit_test = project_root / "tests" / "unit" / "orders" / "nested" / "test_service.py"
    integration_test = project_root / "tests" / "integration" / "orders" / "test_api.py"
    unit_test.parent.mkdir(parents=True)
    integration_test.parent.mkdir(parents=True)
    unit_test.write_text("", encoding="utf-8")
    integration_test.write_text("", encoding="utf-8")

    run_script(project_root, "--write")

    domain = cast(dict[str, object], load_domains(project_root)["orders"])
    assert domain["unit_tests"] == ["tests/unit/orders/nested/test_service.py"]
    assert domain["integration_tests"] == ["tests/integration/orders/test_api.py"]


def test_writes_empty_test_lists_when_tests_are_absent(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py")

    run_script(project_root, "--write")

    domain = cast(dict[str, object], load_domains(project_root)["orders"])
    assert domain["unit_tests"] == []
    assert domain["integration_tests"] == []


def test_detects_absolute_inter_domain_import(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py", "import sample.payments.client\n")
    write_source(project_root, "payments/client.py")

    run_script(project_root, "--write")

    orders = cast(dict[str, object], load_domains(project_root)["orders"])
    assert orders["depends_on"] == ["payments"]


def test_detects_relative_inter_domain_import(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py", "from ..payments import client\n")
    write_source(project_root, "payments/client.py")

    run_script(project_root, "--write")

    orders = cast(dict[str, object], load_domains(project_root)["orders"])
    assert orders["depends_on"] == ["payments"]


def test_ignores_self_and_external_imports(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(
        project_root,
        "orders/service.py",
        "import json\nfrom sample.orders import helpers\nfrom sample import utility\n",
    )

    run_script(project_root, "--write")

    orders = cast(dict[str, object], load_domains(project_root)["orders"])
    assert orders["depends_on"] == []


def test_check_fails_without_modifying_outdated_index(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py")
    configuration_path = project_root / "project_structure.yaml"
    original = configuration_path.read_text(encoding="utf-8")

    result = run_script(project_root, "--check")

    assert result.returncode == 1
    assert configuration_path.read_text(encoding="utf-8") == original


def test_write_updates_outdated_index(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py")

    result = run_script(project_root, "--write")

    assert result.returncode == 0
    assert "orders:" in (project_root / "project_structure.yaml").read_text(encoding="utf-8")


def test_write_does_not_modify_current_index(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "orders/service.py")
    run_script(project_root, "--write")
    configuration_path = project_root / "project_structure.yaml"
    before = configuration_path.stat().st_mtime_ns

    result = run_script(project_root, "--write")

    assert result.returncode == 0
    assert configuration_path.stat().st_mtime_ns == before


def test_writes_domains_and_dependencies_in_alphabetical_order(tmp_path: Path) -> None:
    project_root = create_project(tmp_path)
    write_source(project_root, "zebra/service.py", "import sample.beta\nimport sample.alpha\n")
    write_source(project_root, "beta/service.py")
    write_source(project_root, "alpha/service.py")

    run_script(project_root, "--write")

    domains = load_domains(project_root)
    assert list(domains) == ["alpha", "beta", "zebra"]
    zebra = cast(dict[str, object], domains["zebra"])
    assert zebra["depends_on"] == ["alpha", "beta"]
