#!/usr/bin/env bash
# Bootstrap a project from agent-template.

set -euo pipefail

DEFAULT_DESTINATION="agent-project"
DEFAULT_PACKAGE="agent_project"
REPOSITORY="alirizagurtas/agent-template"
TEMPLATE_ARCHIVE_URL="${TEMPLATE_ARCHIVE_URL:-https://github.com/${REPOSITORY}/archive/refs/heads/main.tar.gz}"

prompt_value() {
    local variable_name="$1"
    local question="$2"
    local default_value="$3"
    local positional_value="${4:-}"
    local selected_value=""

    if [[ -n "$positional_value" ]]; then
        selected_value="$positional_value"
    elif [[ -r /dev/tty ]]; then
        read -r -p "${question} [${default_value}]: " selected_value < /dev/tty
    fi
    printf -v "$variable_name" '%s' "${selected_value:-$default_value}"
}

validate_package() {
    local package_name="$1"
    if [[ ! "$package_name" =~ ^[a-z_][a-z0-9_]*$ ]]; then
        echo "error: package name must be a lowercase Python identifier: $package_name" >&2
        exit 1
    fi
}

replace_placeholders() {
    local package_name="$1"
    local project_name="$2"
    sed -i.bak \
        -e "s/your-project-name/${project_name}/g" \
        -e "s/your_package/${package_name}/g" \
        pyproject.toml project_structure.yaml
    rm -f pyproject.toml.bak project_structure.yaml.bak
}

destination=""
package_name=""
project_name=""
prompt_value destination "Destination directory" "$DEFAULT_DESTINATION" "${DEST:-${1:-}}"
if [[ -e "$destination" ]]; then
    echo "error: destination already exists: $destination" >&2
    exit 1
fi
prompt_value package_name "Python package name" "$DEFAULT_PACKAGE" "${PACKAGE:-${2:-}}"
validate_package "$package_name"
prompt_value project_name "Project name" "${package_name//_/-}" "${PROJECT_NAME:-${3:-}}"

temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT
curl -fsSL "$TEMPLATE_ARCHIVE_URL" | tar -xz -C "$temporary_directory"
template_directory="$(find "$temporary_directory" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
mkdir -p "$(dirname "$destination")"
mv "$template_directory" "$destination"
cd "$destination"
rm -rf .git
replace_placeholders "$package_name" "$project_name"
mkdir -p "src/$package_name" tests/unit
touch "src/$package_name/__init__.py"
git init --quiet
git add .
git commit --quiet -m "Initial commit from agent-template"
if command -v uv >/dev/null 2>&1; then
    uv sync
    uv run --locked poe sync-project-structure
fi
