#!/usr/bin/env -S just --justfile

set dotenv-load := true
set positional-arguments := true

# Constants/Preferences

user := "${DEVELOPER}"

# Default command flags

uv_sync := if env_var_or_default("UV_NO_SYNC", "false") == "true" { "--no-sync" } else { "" }

# Get the project name from 'name' in '[project]' in 'pyproject.toml

project_name := `awk '/^\[project\]/ { proj = 1 } proj && /^name = / { gsub(/"/, "", $3); print $3; exit }' pyproject.toml`

# Print system info and available `just` recipes
_default:
    @echo "This is an {{ arch() }} machine with {{ num_cpus() }} cpu(s), on {{ os() }}."
    @echo "Running: {{ just_executable() }}"
    @echo "   with: {{ justfile() }}"
    @echo "     in: {{ invocation_directory_native() }}"
    @echo ""
    @just --list


### Python

# Run a Python command
[group('python')]
py *args='':
    uv run {{ uv_sync }} $UV_FLAGS python {{ args }}


### Environment

# Destroy the Python virtual environment
[group('environment')]
nuke-python:
    rm -rf .venv dist

# Sync the project's Python environment
[group('environment')]
init-python:
    uv sync --all-groups

# Sync the Python environment, allowing package upgrades
[group('environment')]
update-python:
    uv sync --all-groups --upgrade

# Initialise the project's environment and database.
[group('environment')]
init:
    just init-python

# Update the Python environment, and associated lock file
[group('environment')]
update:
    just update-python


### Linting

# Run Ruff linting and fix any auto-fixable issues
[group('lint')]
lint-python:
    @ruff check . --fix

# Format the Justfile (Note: Marked as 'Unstable!')
[group('lint')]
lint-just:
    @just --fmt --unstable

# Run all linting commands across the project
[group('lint')]
lint:
    just lint-python
    just lint-just


### Workflow

# TODO: commands for report generation# TODO: commands for report generation