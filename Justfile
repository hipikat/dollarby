#!/usr/bin/env -S just --justfile

set dotenv-load
set positional-arguments

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
    uv run {{ uv_sync }} python {{ args }}

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

# Format the Justfile (Note: Marked as 'Unstable!')
[group('development')]
lint-just:
    just --fmt --unstable

# Run Ruff linting and formatting, and fix any auto-fixable issues
[group('development')]
lint-python:
    uv run --frozen ruff check . --fix
    uv run --frozen ruff format .

# Run all linting commands across the project
[group('development')]
lint:
    just lint-just
    just lint-python

### Workflow

# Run the project's PyTest suite
[group('development')]
test:
    uv run --frozen pytest

# Run pre-commit on modified, staged, and untracked files
[group('development')]
pre-commit:
    #!/usr/bin/env bash
    set -euo pipefail
    files=()
    while IFS= read -r -d '' entry; do
        # Skip deleted files
        case $entry in
            "D  "*|" D "*)
                continue
                ;;
        esac

        # Strip Git's two-character status and following space.
        path=${entry#?? }

        # Skip nonexistent paths, but preserve broken symlinks.
        [ -e "$path" ] || [ -L "$path" ] || continue

        files+=("$path")
    done < <(
        # Get changed and untracked paths as NUL-delimited status records.
        git status --porcelain=v1 -z --untracked-files=all --no-renames
    )
    if ((${#files[@]} == 0)); then
        exec uv run --frozen ty check
    fi
    exec uv run --frozen pre-commit run --files "${files[@]}"

# Perform pre-commit checks and git-check all modified and staged files
[group('development')]
check:
    git diff --cached --check
    git diff --check
    just pre-commit

# Apply auto-fixes and run all preflight checks
[group('development')]
preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    restage=()
    while IFS= read -r -d '' entry; do
        index_status=${entry:0:1}
        worktree_status=${entry:1:1}
        path=${entry:3}

        # Remember files which are staged, but not partially staged.
        if [[ $index_status != ' ' && $worktree_status == ' ' ]]; then
            restage+=("$path")
        fi
    done < <(
        git status --porcelain=v1 -z --untracked-files=no --no-renames
    )
    restage_files() {
        if ((${#restage[@]})); then
            git add -- "${restage[@]}"
        fi
    }
    run_quietly() {
        local label=$1
        local output
        local status
        shift
        if output=$("$@" 2>&1); then
            printf '✓ %s\n' "$label"
            return
        else
            status=$?
            printf '%s\n' "$output" >&2
            return "$status"
        fi
    }
    # Preserve the original staging intent if a later auto-fixing hook exits nonzero.
    trap restage_files EXIT
    just lint
    restage_files
    run_quietly "Checks passed" just check
    trap - EXIT
    run_quietly "Tests passed" just test
