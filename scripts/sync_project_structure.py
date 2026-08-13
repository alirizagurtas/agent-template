"""Synchronize domain metadata in project_structure.yaml."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import cast

import yaml

CONFIGURATION_FILENAME = "project_structure.yaml"
EXIT_CODE_SUCCESS = 0
EXIT_CODE_OUTDATED = 1
EXIT_CODE_CONFIGURATION_ERROR = 2
MINIMUM_PACKAGE_SEGMENTS = 1


class ConfigurationError(Exception):
    """Raised when the project structure configuration is unusable."""


def string_keyed_mapping(value: object, *, field_name: str) -> dict[str, object]:
    """Return a mapping with string keys or raise a configuration error."""
    if not isinstance(value, dict):
        message = f"{field_name} must be a YAML mapping."
        raise ConfigurationError(message)
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        message = f"{field_name} must contain only string keys."
        raise ConfigurationError(message)
    return cast(dict[str, object], mapping)


def required_string(mapping: dict[str, object], *, field_name: str) -> str:
    """Return a required non-empty string field."""
    value = mapping.get(field_name)
    if not isinstance(value, str) or not value:
        message = f"{field_name} must be a non-empty string."
        raise ConfigurationError(message)
    return value


def configured_path(project_root: Path, paths: dict[str, object], *, field_name: str) -> Path:
    """Resolve a configured relative path contained by the project root."""
    configured = Path(required_string(paths, field_name=field_name))
    if configured.is_absolute():
        message = f"paths.{field_name} must be a relative path."
        raise ConfigurationError(message)
    resolved_root = project_root.resolve()
    resolved_path = (resolved_root / configured).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        message = f"paths.{field_name} must stay within the project root."
        raise ConfigurationError(message)
    return resolved_path


def load_configuration(configuration_path: Path) -> dict[str, object]:
    """Load and validate the project structure configuration."""
    try:
        contents = configuration_path.read_text(encoding="utf-8")
        loaded = cast(object, yaml.safe_load(contents))
    except (OSError, yaml.YAMLError) as error:
        message = f"Unable to read valid YAML from {configuration_path}: {error}"
        raise ConfigurationError(message) from error
    return string_keyed_mapping(loaded, field_name="project_structure.yaml")


def ignored_path(path: Path, root: Path) -> bool:
    """Report whether a path contains an ignored directory component."""
    return any(
        part.startswith(".") or part == "__pycache__" for part in path.relative_to(root).parts
    )


def python_files(directory: Path) -> list[Path]:
    """Return sorted Python source files below a directory."""
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*.py") if not ignored_path(path, directory))


def domain_directories(source_root: Path) -> list[Path]:
    """Return source-root child directories that contain Python source."""
    return sorted(
        directory
        for directory in source_root.iterdir()
        if directory.is_dir()
        and not directory.name.startswith(".")
        and directory.name != "__pycache__"
        and python_files(directory)
    )


def test_paths(test_root: Path, domain_name: str, project_root: Path) -> list[str]:
    """Return test paths for a domain relative to the project root."""
    domain_root = test_root / domain_name
    return [
        path.relative_to(project_root).as_posix()
        for path in sorted(domain_root.rglob("test_*.py"))
        if path.is_file()
    ]


def module_parts(source_file: Path, source_root: Path, package_parts: list[str]) -> list[str]:
    """Return the import module parts represented by a source file."""
    relative = source_file.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if source_file.name == "__init__.py":
        parts.pop()
    return [*package_parts, *parts]


def imported_domain(parts: list[str], package_parts: list[str], domains: set[str]) -> str | None:
    """Return the domain referenced by package-qualified module parts."""
    package_length = len(package_parts)
    if parts[:package_length] != package_parts or len(parts) <= package_length:
        return None
    candidate = parts[package_length]
    return candidate if candidate in domains else None


def relative_base(node: ast.ImportFrom, current_module: list[str]) -> list[str]:
    """Resolve an ImportFrom target prefix into absolute module parts."""
    parent_count = node.level - 1
    base = current_module[:-parent_count] if parent_count else current_module
    module = node.module.split(".") if node.module else []
    return [*base, *module]


def dependencies_for_file(
    source_file: Path, source_root: Path, package_parts: list[str], domains: set[str]
) -> set[str]:
    """Extract same-package domain imports from one source file."""
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    except OSError, SyntaxError:
        return set()
    current_module = module_parts(source_file, source_root, package_parts)
    if source_file.name != "__init__.py":
        current_module.pop()
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        dependencies.update(dependencies_for_node(node, current_module, package_parts, domains))
    return dependencies


def dependencies_for_node(
    node: ast.AST, current_module: list[str], package_parts: list[str], domains: set[str]
) -> set[str]:
    """Extract domain dependencies from one import AST node."""
    dependency_parts: list[list[str]] = []
    if isinstance(node, ast.Import):
        dependency_parts = [alias.name.split(".") for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        base = (
            relative_base(node, current_module)
            if node.level
            else node.module.split(".")
            if node.module
            else []
        )
        dependency_parts = [base]
        if not node.module:
            dependency_parts.extend([*base, *alias.name.split(".")] for alias in node.names)
    dependencies: set[str] = set()
    for parts in dependency_parts:
        dependency = imported_domain(parts, package_parts, domains)
        if dependency is not None:
            dependencies.add(dependency)
    return dependencies


def build_domains(
    source_root: Path,
    unit_test_root: Path,
    integration_test_root: Path,
    package: str,
    project_root: Path,
) -> dict[str, object]:
    """Build deterministic domain metadata from source and test files."""
    package_parts = package.split(".")
    if len(package_parts) < MINIMUM_PACKAGE_SEGMENTS or not all(
        part.isidentifier() for part in package_parts
    ):
        message = "package must be a dot-separated Python package name."
        raise ConfigurationError(message)
    directories = domain_directories(source_root)
    domain_names = {directory.name for directory in directories}
    domains: dict[str, object] = {}
    for directory in directories:
        dependencies: set[str] = set()
        for source_file in python_files(directory):
            dependencies.update(
                dependencies_for_file(source_file, source_root, package_parts, domain_names)
            )
        dependencies.discard(directory.name)
        domains[directory.name] = {
            "source": directory.relative_to(project_root).as_posix(),
            "unit_tests": test_paths(unit_test_root, directory.name, project_root),
            "integration_tests": test_paths(integration_test_root, directory.name, project_root),
            "depends_on": sorted(dependencies),
        }
    return domains


def rendered_configuration(configuration: dict[str, object], domains: dict[str, object]) -> str:
    """Serialize the configuration with only the domains field recalculated."""
    updated = dict(configuration)
    updated["domains"] = domains
    return yaml.safe_dump(updated, allow_unicode=True, sort_keys=False)


def synchronize(project_root: Path, *, write: bool) -> int:
    """Check or update project structure domains."""
    configuration_path = project_root / CONFIGURATION_FILENAME
    configuration = load_configuration(configuration_path)
    package = required_string(configuration, field_name="package")
    paths = string_keyed_mapping(configuration.get("paths"), field_name="paths")
    source_root = configured_path(project_root, paths, field_name="source")
    unit_test_root = configured_path(project_root, paths, field_name="unit_tests")
    integration_test_root = configured_path(project_root, paths, field_name="integration_tests")
    if not source_root.is_dir():
        message = f"paths.source does not name an existing directory: {source_root}"
        raise ConfigurationError(message)
    expected = rendered_configuration(
        configuration,
        build_domains(source_root, unit_test_root, integration_test_root, package, project_root),
    )
    current = configuration_path.read_text(encoding="utf-8")
    if current == expected:
        return EXIT_CODE_SUCCESS
    if write:
        configuration_path.write_text(expected, encoding="utf-8")
        return EXIT_CODE_SUCCESS
    return EXIT_CODE_OUTDATED


def parse_arguments() -> bool:
    """Parse CLI options and return whether changes should be written."""
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--write", action="store_true", help="update an outdated index")
    options.add_argument("--check", action="store_true", help="check whether the index is current")
    namespace = parser.parse_args()
    return cast(bool, namespace.write)


def main() -> int:
    """Run the command-line script."""
    try:
        return synchronize(Path.cwd(), write=parse_arguments())
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CODE_CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
