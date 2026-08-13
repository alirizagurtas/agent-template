#!/usr/bin/env python3
"""Summarize structured events emitted by the Codex harness."""

import csv
import json
import shlex
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.table import Table

EXPECTED_ARGUMENT_COUNT = 3
EXPECTED_COMMAND_CSV_ARGUMENT_COUNT = 4
EXPECTED_SUMMARIZE_RUN_ARGUMENT_COUNT = 11
EXPECTED_RENDER_BATCH_ARGUMENT_COUNT = 3
USAGE_FIELD_NAMES: tuple[str, ...] = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
LEGACY_USAGE_FIELD_NAMES: tuple[str, ...] = (
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
COMMAND_CSV_FIELD_NAMES: tuple[str, ...] = (
    "command_index",
    "item_id",
    "command",
    "exit_code",
    "output_line_count",
    "output_character_count",
)
SUMMARY_CSV_FIELD_NAMES: tuple[str, ...] = (
    "run",
    "run_status",
    "duration_seconds",
    "codex_exit_code",
    "post_check_exit_code",
    "event_count",
    "turn_started_count",
    "turn_completed_count",
    "agent_message_count",
    "command_execution_count",
    "failed_command_count",
    "unfinished_command_count",
    "file_change_count",
    "agent_validation_invocation_count",
    "usage_available",
    *USAGE_FIELD_NAMES,
)
VALIDATION_TASK_NAMES = frozenset(
    {
        "test-target",
        "test-unit",
        "test-integration",
        "test-failed",
        "lint",
        "format",
        "typecheck",
        "check",
        "check-dependencies",
        "check-project-map",
        "vault-check-links",
        "vault-check-decisions",
    }
)


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Token usage accumulated from completed turns."""

    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


@dataclass(frozen=True, slots=True)
class CommandSummary:
    """A deduplicated command execution item."""

    item_id: str
    command: str
    exit_code: int | None
    output: str
    started: bool
    completed: bool


@dataclass(frozen=True, slots=True)
class RunSummary:
    """All metrics and outcome details for one harness run."""

    run: int
    run_status: str
    duration_seconds: int
    codex_exit_code: int | None
    post_check_exit_code: int | None
    event_count: int
    turn_started_count: int
    turn_completed_count: int
    agent_message_count: int
    command_execution_count: int
    failed_command_count: int
    unfinished_command_count: int
    file_change_count: int
    agent_validation_invocation_count: int
    usage: UsageSummary | None
    commands: tuple[CommandSummary, ...]


def is_json_object(value: object) -> bool:
    """Return whether a parsed JSON value is an object."""
    return isinstance(value, dict)


def json_objects(events: Iterable[str]) -> Iterable[dict[str, object]]:
    """Yield valid JSON objects, ignoring blank or malformed JSONL lines."""
    for event_line in events:
        if not event_line.strip():
            continue
        try:
            value = cast(object, json.loads(event_line))
        except json.JSONDecodeError:
            continue
        if is_json_object(value):
            yield cast(dict[str, object], value)


def token_count(value: object) -> int:
    """Return a non-negative integer token count from an event field."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def item_from_event(event: dict[str, object]) -> dict[str, object] | None:
    """Return the event item when it has the expected JSON object shape."""
    item = event.get("item")
    return cast(dict[str, object], item) if is_json_object(item) else None


def item_key(item: dict[str, object], anonymous_index: int) -> tuple[str, int]:
    """Return a stable item key, assigning unique keys to anonymous items."""
    item_id = item.get("id")
    if isinstance(item_id, str):
        return item_id, anonymous_index
    next_index = anonymous_index + 1
    return f"anonymous-{next_index}", next_index


def usage_from_events(events: Sequence[dict[str, object]]) -> UsageSummary | None:
    """Sum valid usage objects from completed turn events."""
    totals = dict.fromkeys(USAGE_FIELD_NAMES, 0)
    usage_available = False
    for event in events:
        usage = event.get("usage")
        if event.get("type") != "turn.completed" or not is_json_object(usage):
            continue
        usage_available = True
        usage_object = cast(dict[str, object], usage)
        for field_name in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ):
            totals[field_name] += token_count(usage_object.get(field_name))
    if not usage_available:
        return None
    totals["uncached_input_tokens"] = max(0, totals["input_tokens"] - totals["cached_input_tokens"])
    return UsageSummary(**totals)


def validation_invocation_count(command: str) -> int:
    """Count exact Poe validation task invocations in one shell command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return 0
    return poe_task_count(tokens) + sum(
        validation_invocation_count(payload) for payload in shell_command_payloads(tokens)
    )


def poe_task_count(tokens: Sequence[str]) -> int:
    """Count exact Poe task pairs in parsed command tokens."""
    return sum(
        token in {"poe", "poe.exe"} and tokens[token_index + 1] in VALIDATION_TASK_NAMES
        for token_index, token in enumerate(tokens[:-1])
    )


def shell_command_payloads(tokens: Sequence[str]) -> Iterable[str]:
    """Yield command payloads passed through supported shell wrappers."""
    shell_names = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
    if not tokens or Path(tokens[0]).name not in shell_names:
        return
    for token_index, token in enumerate(tokens[:-1]):
        if token.startswith("-") and "c" in token[1:]:
            yield tokens[token_index + 1]


def summarize_events(
    event_lines: Iterable[str],
    *,
    run: int,
    duration_seconds: int,
    codex_exit_code: int | None,
    post_check_exit_code: int | None,
    setup_failed: bool,
) -> RunSummary:
    """Build one run summary from a JSONL event stream read exactly once."""
    events = list(json_objects(event_lines))
    commands_by_item_id: dict[str, dict[str, object]] = {}
    command_order: list[str] = []
    seen_agent_message_ids: set[str] = set()
    seen_file_change_ids: set[str] = set()
    anonymous_index = 0

    for event in events:
        item = item_from_event(event)
        if item is None:
            continue
        item_type = item.get("type")
        item_id, anonymous_index = item_key(item, anonymous_index)
        if item_type == "agent_message":
            seen_agent_message_ids.add(item_id)
        elif item_type == "file_change":
            seen_file_change_ids.add(item_id)
        elif item_type == "command_execution":
            if item_id not in commands_by_item_id:
                commands_by_item_id[item_id] = {
                    "item_id": item_id,
                    "command": "",
                    "exit_code": None,
                    "output": "",
                    "started": False,
                    "completed": False,
                }
                command_order.append(item_id)
            command_data = commands_by_item_id[item_id]
            command = item.get("command")
            if isinstance(command, str):
                command_data["command"] = command
            exit_code = item.get("exit_code")
            if isinstance(exit_code, int) and not isinstance(exit_code, bool):
                command_data["exit_code"] = exit_code
                command_data["completed"] = True
            output = item.get("aggregated_output")
            if isinstance(output, str):
                command_data["output"] = output
            event_type = event.get("type")
            if event_type == "item.started":
                command_data["started"] = True
            if event_type == "item.completed":
                command_data["completed"] = True

    commands = tuple(
        CommandSummary(
            item_id=item_id,
            command=cast(str, commands_by_item_id[item_id]["command"]),
            exit_code=cast(int | None, commands_by_item_id[item_id]["exit_code"]),
            output=cast(str, commands_by_item_id[item_id]["output"]),
            started=cast(bool, commands_by_item_id[item_id]["started"]),
            completed=cast(bool, commands_by_item_id[item_id]["completed"]),
        )
        for item_id in command_order
    )
    turn_started_count = sum(event.get("type") == "turn.started" for event in events)
    turn_completed_count = sum(event.get("type") == "turn.completed" for event in events)
    run_status = classify_run_status(
        setup_failed=setup_failed,
        turn_completed_count=turn_completed_count,
        codex_exit_code=codex_exit_code,
        post_check_exit_code=post_check_exit_code,
    )
    return RunSummary(
        run=run,
        run_status=run_status,
        duration_seconds=duration_seconds,
        codex_exit_code=codex_exit_code,
        post_check_exit_code=post_check_exit_code,
        event_count=len(events),
        turn_started_count=turn_started_count,
        turn_completed_count=turn_completed_count,
        agent_message_count=len(seen_agent_message_ids),
        command_execution_count=len(commands),
        failed_command_count=sum(command.exit_code not in {None, 0} for command in commands),
        unfinished_command_count=sum(
            command.started and command.exit_code is None for command in commands
        ),
        file_change_count=len(seen_file_change_ids),
        agent_validation_invocation_count=sum(
            validation_invocation_count(command.command) for command in commands
        ),
        usage=usage_from_events(events),
        commands=commands,
    )


def classify_run_status(
    *,
    setup_failed: bool,
    turn_completed_count: int,
    codex_exit_code: int | None,
    post_check_exit_code: int | None,
) -> str:
    """Classify a run using the harness status precedence contract."""
    if setup_failed:
        return "setup_failed"
    if turn_completed_count == 0:
        return "incomplete"
    if codex_exit_code != 0:
        return "codex_failed"
    if post_check_exit_code != 0:
        return "post_check_failed"
    return "passed"


def count_command_executions(events: Iterable[str]) -> int:
    """Return the number of deduplicated command_execution items."""
    return len(
        summarize_events(
            events,
            run=0,
            duration_seconds=0,
            codex_exit_code=0,
            post_check_exit_code=0,
            setup_failed=False,
        ).commands
    )


def summarize_usage(events: Iterable[str]) -> dict[str, int]:
    """Return legacy zero-filled usage totals from JSONL events."""
    usage = usage_from_events(list(json_objects(events)))
    if usage is None:
        return dict.fromkeys(LEGACY_USAGE_FIELD_NAMES, 0)
    return {field_name: getattr(usage, field_name) for field_name in LEGACY_USAGE_FIELD_NAMES}


def command_execution_rows(events: Iterable[str]) -> list[dict[str, object]]:
    """Return one command CSV row per deduplicated command item."""
    summary = summarize_events(
        events,
        run=0,
        duration_seconds=0,
        codex_exit_code=0,
        post_check_exit_code=0,
        setup_failed=False,
    )
    return command_rows(summary.commands)


def command_rows(commands: Sequence[CommandSummary]) -> list[dict[str, object]]:
    """Format command summaries as command CSV rows."""
    return [
        {
            "command_index": command_index,
            "item_id": command.item_id,
            "command": command.command,
            "exit_code": "" if command.exit_code is None else command.exit_code,
            "output_line_count": len(command.output.splitlines()),
            "output_character_count": len(command.output),
        }
        for command_index, command in enumerate(commands, start=1)
    ]


def write_command_csv_from_commands(commands: Sequence[CommandSummary], output_path: Path) -> None:
    """Write command execution measurements to a CSV file."""
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=COMMAND_CSV_FIELD_NAMES)
        writer.writeheader()
        writer.writerows(command_rows(commands))


def write_command_csv(events: Iterable[str], output_path: Path) -> None:
    """Write command execution measurements to a CSV file."""
    write_command_csv_from_commands(
        summarize_events(
            events,
            run=0,
            duration_seconds=0,
            codex_exit_code=0,
            post_check_exit_code=0,
            setup_failed=False,
        ).commands,
        output_path,
    )


def summary_row(summary: RunSummary) -> dict[str, str | int]:
    """Format a run summary for the canonical summary CSV."""
    row: dict[str, str | int] = {
        "run": summary.run,
        "run_status": summary.run_status,
        "duration_seconds": summary.duration_seconds,
        "codex_exit_code": "" if summary.codex_exit_code is None else summary.codex_exit_code,
        "post_check_exit_code": (
            "" if summary.post_check_exit_code is None else summary.post_check_exit_code
        ),
        "event_count": summary.event_count,
        "turn_started_count": summary.turn_started_count,
        "turn_completed_count": summary.turn_completed_count,
        "agent_message_count": summary.agent_message_count,
        "command_execution_count": summary.command_execution_count,
        "failed_command_count": summary.failed_command_count,
        "unfinished_command_count": summary.unfinished_command_count,
        "file_change_count": summary.file_change_count,
        "agent_validation_invocation_count": summary.agent_validation_invocation_count,
        "usage_available": str(summary.usage is not None).lower(),
    }
    for field_name in USAGE_FIELD_NAMES:
        row[field_name] = "" if summary.usage is None else getattr(summary.usage, field_name)
    return row


def append_summary_csv(summary: RunSummary, output_path: Path) -> None:
    """Append one run summary to an already initialized canonical CSV."""
    with output_path.open("a", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=SUMMARY_CSV_FIELD_NAMES)
        writer.writerow(summary_row(summary))


def format_number(value: int | None) -> str:
    """Format a metric for terminal display."""
    return "—" if value is None else f"{value:,}"


def status_markup(status: str) -> str:
    """Return a readable status value with an optional Rich color."""
    style = {
        "passed": "green",
        "incomplete": "yellow",
        "codex_failed": "red",
        "post_check_failed": "red",
        "setup_failed": "red",
    }[status]
    return f"[{style}]{status}[/{style}]"


def render_run_summary(summary: RunSummary, total_runs: int, console: Console) -> None:
    """Render one vertical Rich run summary table."""
    table = Table(title=f"Run {summary.run}/{total_runs}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    usage = summary.usage
    rows: tuple[tuple[str, str], ...] = (
        ("Status", status_markup(summary.run_status)),
        ("Duration", f"{summary.duration_seconds}s"),
        ("Codex exit", format_number(summary.codex_exit_code)),
        ("Post-check exit", format_number(summary.post_check_exit_code)),
        ("Events", format_number(summary.event_count)),
        ("Turns started", format_number(summary.turn_started_count)),
        ("Turns completed", format_number(summary.turn_completed_count)),
        ("Agent messages", format_number(summary.agent_message_count)),
        ("Commands", format_number(summary.command_execution_count)),
        ("Failed commands", format_number(summary.failed_command_count)),
        ("Unfinished commands", format_number(summary.unfinished_command_count)),
        ("File changes", format_number(summary.file_change_count)),
        ("Validation calls", format_number(summary.agent_validation_invocation_count)),
        ("Input tokens", format_number(None if usage is None else usage.input_tokens)),
        ("Cached input", format_number(None if usage is None else usage.cached_input_tokens)),
        (
            "Cache-write input",
            format_number(None if usage is None else usage.cache_write_input_tokens),
        ),
        ("Uncached input", format_number(None if usage is None else usage.uncached_input_tokens)),
        ("Output tokens", format_number(None if usage is None else usage.output_tokens)),
        (
            "Reasoning tokens",
            format_number(None if usage is None else usage.reasoning_output_tokens),
        ),
    )
    for metric, value in rows:
        table.add_row(metric, value)
    console.print(table)


def render_batch_summaries(summaries: Sequence[RunSummary], console: Console) -> None:
    """Render narrow-terminal-safe, transposed batch comparison tables."""
    execution_table = Table(title="Execution Summary", collapse_padding=True)
    token_table = Table(title="Token Summary", collapse_padding=True)
    for table in (execution_table, token_table):
        table.add_column("Metric")
        for summary in summaries:
            table.add_column(f"Run {summary.run}", justify="right", overflow="fold")

    execution_metrics: tuple[tuple[str, Callable[[RunSummary], str]], ...] = (
        ("Status", lambda summary: status_markup(summary.run_status)),
        ("Duration", lambda summary: f"{summary.duration_seconds}s"),
        ("Codex", lambda summary: format_number(summary.codex_exit_code)),
        ("Post-check", lambda summary: format_number(summary.post_check_exit_code)),
        (
            "Turns started/completed",
            lambda summary: f"{summary.turn_started_count}/{summary.turn_completed_count}",
        ),
        ("Messages", lambda summary: format_number(summary.agent_message_count)),
        ("Commands", lambda summary: format_number(summary.command_execution_count)),
        ("Failed", lambda summary: format_number(summary.failed_command_count)),
        ("Unfinished", lambda summary: format_number(summary.unfinished_command_count)),
        ("Validations", lambda summary: format_number(summary.agent_validation_invocation_count)),
    )
    for metric, value in execution_metrics:
        execution_table.add_row(metric, *(value(summary) for summary in summaries))

    token_metrics: tuple[tuple[str, Callable[[UsageSummary | None], str]], ...] = (
        ("Total input", lambda usage: format_number(None if usage is None else usage.input_tokens)),
        (
            "Cached input",
            lambda usage: format_number(None if usage is None else usage.cached_input_tokens),
        ),
        (
            "Cache write",
            lambda usage: format_number(None if usage is None else usage.cache_write_input_tokens),
        ),
        (
            "Uncached input",
            lambda usage: format_number(None if usage is None else usage.uncached_input_tokens),
        ),
        ("Output", lambda usage: format_number(None if usage is None else usage.output_tokens)),
        (
            "Reasoning",
            lambda usage: format_number(None if usage is None else usage.reasoning_output_tokens),
        ),
    )
    for metric, value in token_metrics:
        token_table.add_row(metric, *(value(summary.usage) for summary in summaries))
    console.print(execution_table)
    console.print(token_table)


def parse_optional_exit_code(value: str) -> int | None:
    """Parse the shell's optional exit-code argument."""
    return None if value == "-" else int(value)


def read_summary_csv(input_path: Path) -> list[RunSummary]:
    """Read canonical summary CSV rows back into the render model."""
    summaries: list[RunSummary] = []
    with input_path.open(encoding="utf-8", newline="") as input_file:
        for row in csv.DictReader(input_file):
            usage = None
            if row["usage_available"] == "true":
                usage = UsageSummary(
                    **{field_name: int(row[field_name]) for field_name in USAGE_FIELD_NAMES}
                )
            summaries.append(
                RunSummary(
                    run=int(row["run"]),
                    run_status=row["run_status"],
                    duration_seconds=int(row["duration_seconds"]),
                    codex_exit_code=(
                        int(row["codex_exit_code"]) if row["codex_exit_code"] else None
                    ),
                    post_check_exit_code=(
                        int(row["post_check_exit_code"]) if row["post_check_exit_code"] else None
                    ),
                    event_count=int(row["event_count"]),
                    turn_started_count=int(row["turn_started_count"]),
                    turn_completed_count=int(row["turn_completed_count"]),
                    agent_message_count=int(row["agent_message_count"]),
                    command_execution_count=int(row["command_execution_count"]),
                    failed_command_count=int(row["failed_command_count"]),
                    unfinished_command_count=int(row["unfinished_command_count"]),
                    file_change_count=int(row["file_change_count"]),
                    agent_validation_invocation_count=int(row["agent_validation_invocation_count"]),
                    usage=usage,
                    commands=(),
                )
            )
    return summaries


def main() -> int:
    if len(sys.argv) == EXPECTED_ARGUMENT_COUNT and sys.argv[1] == "count-tool-calls":
        with Path(sys.argv[2]).open(encoding="utf-8") as events:
            print(count_command_executions(events))
        return 0
    if len(sys.argv) == EXPECTED_ARGUMENT_COUNT and sys.argv[1] == "usage-csv":
        with Path(sys.argv[2]).open(encoding="utf-8") as events:
            usage_totals = summarize_usage(events)
        print(",".join(str(usage_totals[field_name]) for field_name in LEGACY_USAGE_FIELD_NAMES))
        return 0
    if len(sys.argv) == EXPECTED_COMMAND_CSV_ARGUMENT_COUNT and sys.argv[1] == "write-command-csv":
        with Path(sys.argv[2]).open(encoding="utf-8") as events:
            write_command_csv(events, Path(sys.argv[3]))
        return 0
    if len(sys.argv) == EXPECTED_SUMMARIZE_RUN_ARGUMENT_COUNT and sys.argv[1] == "summarize-run":
        run = int(sys.argv[2])
        total_runs = int(sys.argv[3])
        jsonl_path = Path(sys.argv[4])
        duration_seconds = int(sys.argv[5])
        codex_exit_code = parse_optional_exit_code(sys.argv[6])
        post_check_exit_code = parse_optional_exit_code(sys.argv[7])
        setup_failed = sys.argv[8] == "true"
        summary_csv_path = Path(sys.argv[9])
        if setup_failed:
            summary = summarize_events(
                (),
                run=run,
                duration_seconds=duration_seconds,
                codex_exit_code=codex_exit_code,
                post_check_exit_code=post_check_exit_code,
                setup_failed=setup_failed,
            )
        else:
            with jsonl_path.open(encoding="utf-8") as event_lines:
                summary = summarize_events(
                    event_lines,
                    run=run,
                    duration_seconds=duration_seconds,
                    codex_exit_code=codex_exit_code,
                    post_check_exit_code=post_check_exit_code,
                    setup_failed=setup_failed,
                )
        append_summary_csv(summary, summary_csv_path)
        if not setup_failed:
            write_command_csv_from_commands(summary.commands, Path(sys.argv[10]))
        render_run_summary(summary, total_runs, Console())
        return 0
    if len(sys.argv) == EXPECTED_RENDER_BATCH_ARGUMENT_COUNT and sys.argv[1] == "render-batch":
        render_batch_summaries(read_summary_csv(Path(sys.argv[2])), Console())
        return 0

    print(
        "usage: harness_stats.py {count-tool-calls|usage-csv} <jsonl_log> "
        "or harness_stats.py write-command-csv <jsonl_log> <output_csv> "
        "or harness_stats.py summarize-run <run> <total_runs> <jsonl_log> <duration> "
        "<codex_exit_code|-> <post_check_exit_code|-> <setup_failed> <summary_csv> "
        "[command_csv] or harness_stats.py render-batch <summary_csv>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
