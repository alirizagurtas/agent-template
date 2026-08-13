#!/usr/bin/env bash
# N-run test harness for Codex CLI.
#
# Runs the same prompt against a clean repo state N times, using `codex exec`
# (non-interactive mode), and records per-run stats: pass/fail (via your
# check command), wall-clock duration, and raw event count from the JSONL
# stream (a rough proxy for turns until we know the exact schema — see notes
# at the bottom).
#
# Usage:
#   ./run_harness.sh <prompt_file> <baseline_ref> <check_command> [n_runs]
#
# Example:
#   ./run_harness.sh prompt.txt main "uv run poe check" 8
#
# Requirements:
#   - Run from inside the git repo you're testing.
#   - <baseline_ref> is a clean commit/branch to reset to before each run
#     (e.g. "main" or a specific commit sha). All tracked files must be
#     clean before you start (script checks this; untracked files are fine).
#   - <prompt_file> contains the exact prompt text to send each run.
#   - IMPORTANT: this script itself, and your prompt file, must be committed
#     (tracked) before running — otherwise the per-run `git clean -fd` will
#     delete them. Make sure `.gitignore` covers harness_runs/ and that
#     .gitignore change is committed too.

set -euo pipefail

# Run from an immutable copy before Codex can modify the tracked script in the
# working tree. The snapshot process owns its cleanup so an exec replaces this
# original interpreter instead of allowing it to resume parsing the live file.
if [[ "${HARNESS_SNAPSHOT_ACTIVE:-}" == "1" \
    && -n "${HARNESS_SNAPSHOT_PATH:-}" \
    && -f "$HARNESS_SNAPSHOT_PATH" \
    && "$0" -ef "$HARNESS_SNAPSHOT_PATH" ]]; then
    HARNESS_SCRIPT_PATH="${HARNESS_SOURCE_SCRIPT:-$0}"
else
    HARNESS_SCRIPT_PATH="$0"
    SNAPSHOT_PATH="$(mktemp "${TMPDIR:-/tmp}/run_harness.XXXXXX")"
    if ! cp -- "$0" "$SNAPSHOT_PATH"; then
        rm -f -- "$SNAPSHOT_PATH"
        exit 1
    fi
    if ! HARNESS_SNAPSHOT_ACTIVE=1 HARNESS_SNAPSHOT_PATH="$SNAPSHOT_PATH" \
        HARNESS_SOURCE_SCRIPT="$HARNESS_SCRIPT_PATH" exec bash "$SNAPSHOT_PATH" "$@"; then
        rm -f -- "$SNAPSHOT_PATH"
        exit 1
    fi
fi

cleanup_snapshot() {
    rm -f -- "${HARNESS_SNAPSHOT_PATH:?missing snapshot path}" || true
}

trap cleanup_snapshot EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROMPT_FILE="${1:?usage: run_harness.sh <prompt_file> <baseline_ref> <check_command> [n_runs]}"
BASELINE_REF="${2:?missing baseline_ref}"
CHECK_CMD="${3:?missing check_command}"
N_RUNS="${4:-5}"

if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "error: prompt file '$PROMPT_FILE' not found" >&2
    exit 1
fi

# Only block on changes to TRACKED files. Untracked files are fine to have
# lying around UNLESS this script or the prompt file are themselves
# untracked — checked explicitly below, since git clean -fd would otherwise
# delete them mid-run.
TRACKED_CHANGES="$(git status --short | grep -v '^??' || true)"
if [[ -n "$TRACKED_CHANGES" ]]; then
    echo "error: working tree has uncommitted changes to tracked files. Commit or stash first." >&2
    echo "$TRACKED_CHANGES" >&2
    exit 1
fi

# This script and the prompt file MUST be tracked by git, or the per-run
# `git clean -fd` will delete them on the very first iteration.
for f in "$HARNESS_SCRIPT_PATH" "$PROMPT_FILE"; do
    if ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        echo "error: '$f' is not tracked by git. Commit it first (git add '$f' && git commit), or git clean -fd will delete it." >&2
        exit 1
    fi
done

RUN_DIR="harness_runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN_DIR"
echo "Logging to $RUN_DIR/"

PROMPT_TEXT="$(cat "$PROMPT_FILE")"
if [[ -n "${HARNESS_STATS_PYTHON:-}" ]]; then
    read -r -a STATS_PYTHON <<< "$HARNESS_STATS_PYTHON"
else
    STATS_PYTHON=(uv run --locked python)
fi

SUMMARY_CSV="$RUN_DIR/summary.csv"
echo "run,run_status,duration_seconds,codex_exit_code,post_check_exit_code,event_count,turn_started_count,turn_completed_count,agent_message_count,command_execution_count,failed_command_count,unfinished_command_count,file_change_count,agent_validation_invocation_count,usage_available,input_tokens,cached_input_tokens,cache_write_input_tokens,uncached_input_tokens,output_tokens,reasoning_output_tokens" > "$SUMMARY_CSV"
HARNESS_EXIT=0

clean_python_caches() {
    local root
    for root in src tests; do
        if [[ -d "$root" ]]; then
            find "$root" -type d -name __pycache__ -prune -exec rm -rf -- {} +
            find "$root" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
            find "$root" -depth -mindepth 1 -type d -empty -delete
        fi
    done
}

for i in $(seq 1 "$N_RUNS"); do
    echo ""
    echo "=== Run $i/$N_RUNS ==="

    SETUP_FAILED=false
    CODEX_EXIT="-"
    POST_CHECK_EXIT="-"
    DURATION=0

    # Reset to clean baseline before every run. A failed setup is recorded,
    # while later runs still get their own setup attempt.
    if git checkout "$BASELINE_REF" --quiet \
        && git reset --hard "$BASELINE_REF" --quiet \
        && git clean -fd --quiet \
        && clean_python_caches; then
        JSONL_LOG="$RUN_DIR/run_${i}.jsonl"
        FINAL_MSG="$RUN_DIR/run_${i}_final.txt"
        CHECK_LOG="$RUN_DIR/run_${i}_check.log"
        START_TS=$(date +%s)

        # --sandbox workspace-write: allow file writes without approval prompts.
        # --json: stream structured events to stdout (redirected to file here).
        # -o: also capture just the final agent message separately.
        if codex exec --sandbox workspace-write --json -o "$FINAL_MSG" "$PROMPT_TEXT" \
            > "$JSONL_LOG" 2>"$RUN_DIR/run_${i}_stderr.log"; then
            CODEX_EXIT=0
        else
            CODEX_EXIT=$?
        fi

        END_TS=$(date +%s)
        DURATION=$((END_TS - START_TS))

        # Run the post-check even after a failed Codex process. Its complete
        # stdout and stderr remain in the canonical check log.
        if eval "$CHECK_CMD" > "$CHECK_LOG" 2>&1; then
            POST_CHECK_EXIT=0
        else
            POST_CHECK_EXIT=$?
            sed '$ { /Sequence aborted/ d; }' "$CHECK_LOG" >&2
        fi

        # Capture the diff codex produced this run, before we wipe it on the next loop.
        git diff > "$RUN_DIR/run_${i}.diff"
    else
        SETUP_FAILED=true
        echo "error: setup failed for run $i" >&2
    fi

    if ! "${STATS_PYTHON[@]}" scripts/harness_stats.py summarize-run \
        "$i" "$N_RUNS" "$RUN_DIR/run_${i}.jsonl" "$DURATION" "$CODEX_EXIT" \
        "$POST_CHECK_EXIT" "$SETUP_FAILED" "$SUMMARY_CSV" "$RUN_DIR/run_${i}_commands.csv"; then
        HARNESS_EXIT=1
        continue
    fi
    RUN_STATUS=$(tail -n 1 "$SUMMARY_CSV" | cut -d, -f2)
    if [[ "$RUN_STATUS" != "passed" ]]; then
        HARNESS_EXIT=1
    fi
done

# Leave the repo clean at the end.
if ! git checkout "$BASELINE_REF" --quiet \
    || ! git reset --hard "$BASELINE_REF" --quiet \
    || ! git clean -fd --quiet \
    || ! clean_python_caches; then
    HARNESS_EXIT=1
fi

echo ""
echo "=== Done. Summary: $SUMMARY_CSV ==="
if ! "${STATS_PYTHON[@]}" scripts/harness_stats.py render-batch "$SUMMARY_CSV"; then
    HARNESS_EXIT=1
fi

exit "$HARNESS_EXIT"

# ---------------------------------------------------------------------------
# Notes:
#
# 1. --sandbox workspace-write grants workspace writes without per-step
#    confirmation. Only
#    run this against a repo/branch you're fine letting the agent modify
#    freely and reset every iteration.
#
# 2. harness_runs/ must be in .gitignore, and that .gitignore change must be
#    committed, or the per-run `git clean -fd` will wipe your results
#    mid-run.
# ---------------------------------------------------------------------------
