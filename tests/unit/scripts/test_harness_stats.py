"""Tests for harness JSONL summaries and terminal reporting."""

import csv
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/harness_stats.py")
SUMMARY_HEADERS = (
    "run,run_status,duration_seconds,codex_exit_code,post_check_exit_code,event_count,"
    "turn_started_count,turn_completed_count,agent_message_count,command_execution_count,"
    "failed_command_count,unfinished_command_count,file_change_count,"
    "agent_validation_invocation_count,usage_available,input_tokens,cached_input_tokens,"
    "cache_write_input_tokens,uncached_input_tokens,output_tokens,reasoning_output_tokens\n"
)


def run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the harness stats CLI using the test environment interpreter."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *arguments],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


def write_summary_header(path: Path) -> None:
    """Initialize a canonical harness summary CSV fixture."""
    path.write_text(SUMMARY_HEADERS, encoding="utf-8")


def summarize_run(
    tmp_path: Path,
    event_text: str,
    *,
    codex_exit_code: str = "0",
    post_check_exit_code: str = "0",
    setup_failed: str = "false",
) -> tuple[dict[str, str], str, Path]:
    """Run the new one-pass summary CLI and return its CSV row and output."""
    jsonl_log = tmp_path / "events.jsonl"
    summary_csv = tmp_path / "summary.csv"
    commands_csv = tmp_path / "commands.csv"
    jsonl_log.write_text(event_text, encoding="utf-8")
    write_summary_header(summary_csv)
    result = run_script(
        "summarize-run",
        "1",
        "5",
        str(jsonl_log),
        "12",
        codex_exit_code,
        post_check_exit_code,
        setup_failed,
        str(summary_csv),
        str(commands_csv),
    )
    with summary_csv.open(encoding="utf-8", newline="") as csv_file:
        row = next(csv.DictReader(csv_file))
    return row, result.stdout, commands_csv


def test_count_tool_calls_deduplicates_item_ids_and_ignores_invalid_jsonl(tmp_path: Path) -> None:
    jsonl_log = tmp_path / "events.jsonl"
    jsonl_log.write_text(
        "\n".join(
            (
                '{"type":"item.started","item":{"id":"item-1","type":"command_execution","command":"pwd"}}',
                '{"type":"item.completed","item":{"id":"item-1","type":"command_execution","exit_code":0}}',
                '{"type":"item.started","item":{"id":"item-2","type":"command_execution","command":"git status"}}',
                '{"type":"item.completed","item":{"id":"item-3","type":"command_execution","command":"git diff","exit_code":0}}',
                '{"type":"item.completed","item":{"id":"item-4","type":"file_change"}}',
                "{invalid",
            )
        ),
        encoding="utf-8",
    )

    result = run_script("count-tool-calls", str(jsonl_log))

    assert result.stdout == "3\n"


def test_usage_csv_keeps_legacy_shape_and_sums_usage(tmp_path: Path) -> None:
    jsonl_log = tmp_path / "events.jsonl"
    jsonl_log.write_text(
        "\n".join(
            (
                '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":25,"cache_write_input_tokens":3,"output_tokens":40,"reasoning_output_tokens":10}}',
                '{"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":5,"output_tokens":20,"reasoning_output_tokens":7}}',
            )
        ),
        encoding="utf-8",
    )

    result = run_script("usage-csv", str(jsonl_log))

    assert result.stdout == "150,30,120,60,17\n"


def test_write_command_csv_keeps_legacy_columns_and_blank_unfinished_exit_code(
    tmp_path: Path,
) -> None:
    jsonl_log = tmp_path / "events.jsonl"
    output_csv = tmp_path / "commands.csv"
    jsonl_log.write_text(
        "\n".join(
            (
                '{"type":"item.started","item":{"id":"item-1","type":"command_execution","command":"pwd"}}',
                '{"type":"item.completed","item":{"id":"item-1","type":"command_execution","exit_code":0,"aggregated_output":"/workspace\\n"}}',
                '{"type":"item.started","item":{"id":"item-2","type":"command_execution","command":"git status"}}',
            )
        ),
        encoding="utf-8",
    )

    run_script("write-command-csv", str(jsonl_log), str(output_csv))

    with output_csv.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows == [
        {
            "command_index": "1",
            "item_id": "item-1",
            "command": "pwd",
            "exit_code": "0",
            "output_line_count": "1",
            "output_character_count": "11",
        },
        {
            "command_index": "2",
            "item_id": "item-2",
            "command": "git status",
            "exit_code": "",
            "output_line_count": "0",
            "output_character_count": "0",
        },
    ]


def test_summary_counts_metrics_validations_and_negative_uncached_input(tmp_path: Path) -> None:
    row, output, commands_csv = summarize_run(
        tmp_path,
        "\n".join(
            (
                '{"type":"turn.started"}',
                '{"type":"item.started","item":{"id":"command-1","type":"command_execution","command":"uv run poe test-target tests && uv run poe check-project-map"}}',
                '{"type":"item.completed","item":{"id":"command-1","type":"command_execution","exit_code":1}}',
                '{"type":"item.started","item":{"id":"command-2","type":"command_execution","command":"/bin/bash -lc \'uv run --locked poe test-target tests && uv run --locked poe check\'"}}',
                '{"type":"item.completed","item":{"id":"command-2","type":"command_execution"}}',
                '{"type":"item.completed","item":{"id":"message-1","type":"agent_message"}}',
                '{"type":"item.completed","item":{"id":"message-1","type":"agent_message"}}',
                '{"type":"item.completed","item":{"id":"file-1","type":"file_change"}}',
                '{"type":"item.completed","item":{"id":"file-1","type":"file_change"}}',
                '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":20,"cache_write_input_tokens":3,"output_tokens":4,"reasoning_output_tokens":2}}',
                '{"type":"turn.completed","usage":{"input_tokens":5,"cached_input_tokens":0,"output_tokens":6,"reasoning_output_tokens":1}}',
                "{invalid",
            )
        ),
    )

    assert row["event_count"] == "11"
    assert row["turn_started_count"] == "1"
    assert row["turn_completed_count"] == "2"
    assert row["agent_message_count"] == "1"
    assert row["command_execution_count"] == "2"
    assert row["failed_command_count"] == "1"
    assert row["unfinished_command_count"] == "1"
    assert row["file_change_count"] == "1"
    assert row["agent_validation_invocation_count"] == "4"
    assert row["usage_available"] == "true"
    assert row["input_tokens"] == "15"
    assert row["cached_input_tokens"] == "20"
    assert row["cache_write_input_tokens"] == "3"
    assert row["uncached_input_tokens"] == "0"
    assert row["output_tokens"] == "10"
    assert row["reasoning_output_tokens"] == "3"
    assert "Run 1/5" in output
    assert "Validation calls" in output
    assert "15" in output
    assert commands_csv.exists()


def test_summary_marks_completed_command_without_exit_code_as_unfinished(tmp_path: Path) -> None:
    row, _, _ = summarize_run(
        tmp_path,
        "\n".join(
            (
                '{"type":"item.started","item":{"id":"command-1","type":"command_execution","command":"uv run poe check"}}',
                '{"type":"item.completed","item":{"id":"command-1","type":"command_execution"}}',
                '{"type":"turn.completed"}',
            )
        ),
    )

    assert row["unfinished_command_count"] == "1"


def test_summary_leaves_token_csv_cells_blank_without_usage(tmp_path: Path) -> None:
    row, output, _ = summarize_run(tmp_path, '{"type":"turn.completed"}\n')

    assert row["usage_available"] == "false"
    assert all(row[field_name] == "" for field_name in SUMMARY_HEADERS.rstrip().split(",")[15:])
    assert "Input tokens" in output
    assert "—" in output


def test_summary_classifies_all_statuses(tmp_path: Path) -> None:
    cases = (
        ("incomplete", "", "0", "0", "false"),
        ("codex_failed", '{"type":"turn.completed"}', "7", "0", "false"),
        ("post_check_failed", '{"type":"turn.completed"}', "0", "3", "false"),
        ("setup_failed", '{"type":"turn.completed"}', "0", "0", "true"),
        ("passed", '{"type":"turn.completed"}', "0", "0", "false"),
    )

    for index, (expected_status, events, codex_exit, post_check_exit, setup_failed) in enumerate(
        cases
    ):
        case_path = tmp_path / str(index)
        case_path.mkdir()
        row, _, _ = summarize_run(
            case_path,
            events,
            codex_exit_code=codex_exit,
            post_check_exit_code=post_check_exit,
            setup_failed=setup_failed,
        )
        assert row["run_status"] == expected_status


def test_batch_rich_tables_include_all_runs_without_ansi_dependency(tmp_path: Path) -> None:
    summary_csv = tmp_path / "summary.csv"
    write_summary_header(summary_csv)
    for run, status in ((1, "passed"), (2, "incomplete")):
        jsonl_log = tmp_path / f"events-{run}.jsonl"
        commands_csv = tmp_path / f"commands-{run}.csv"
        jsonl_log.write_text(
            '{"type":"turn.started"}\n{"type":"turn.completed"}\n'
            if status == "passed"
            else '{"type":"turn.started"}\n',
            encoding="utf-8",
        )
        run_script(
            "summarize-run",
            str(run),
            "2",
            str(jsonl_log),
            "1",
            "0",
            "0",
            "false",
            str(summary_csv),
            str(commands_csv),
        )

    result = run_script("render-batch", str(summary_csv))

    assert "Execution Summary" in result.stdout
    assert "Token Summary" in result.stdout
    assert "Run 1" in result.stdout
    assert "Run 2" in result.stdout
    assert "passed" in result.stdout
    assert "incomplete" in result.stdout
    assert "Turns started/completed" in result.stdout
    assert "1/1" in result.stdout
    assert "1/0" in result.stdout
    assert "Cache write" in result.stdout
    assert "Total input" in result.stdout
    assert "Cached input" in result.stdout
    assert "Uncached input" in result.stdout
    assert "\n│ Input" not in result.stdout
