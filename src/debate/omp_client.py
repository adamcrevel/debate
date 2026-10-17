"""Async wrapper around the `omp` CLI -- the only way this engine ever talks to a model.

This is the ONLY module in `src/debate` allowed to import `subprocess` or use
`asyncio.create_subprocess_exec`. Every agent turn (Requirement 8) is exactly
one non-interactive `omp -p` subprocess call, built and awaited here.

Prompt-combination strategy: `omp -p` accepts a single prompt argument, not
separate system/user arguments. `run_omp_turn` combines them into one string
with a `[System instructions]` / `[Task]` header pair, each on its own
labelled block, so the model can still tell an instruction-giving preamble
apart from the actual task even though `omp` only ever sees one string. This
keeps the combination simple and legible in captured transcripts/logs rather
than relying on a more elaborate chat-style markup `omp -p`'s plain-text mode
does not understand anyway.

Requirement 9 backstop: regardless of whether the model honors its own
120-word instruction, `run_omp_turn` always counts words in the returned
text and truncates to the first 200 words if that is exceeded, flagging
`truncated=True` on the result. This backstop is independent of and blind to
the model's own compliance -- it only ever fires at the 200-word line.
"""

import asyncio
import time
from dataclasses import dataclass

_TRUNCATION_WORD_LIMIT = 200


class OmpTimeoutError(TimeoutError):
    """Raised when an `omp -p` subprocess call exceeds its allotted timeout."""


@dataclass(frozen=True)
class OmpResult:
    """The result of one `omp -p` subprocess call.

    Attributes:
        text: The response text, truncated to `_TRUNCATION_WORD_LIMIT` words
            if the model's raw output exceeded that limit.
        truncated: Whether the 200-word truncation backstop fired. This
            reports the backstop only -- it says nothing about whether the
            model itself honored its own (separate) 120-word instruction.
        model_used: Whatever `model` was passed to `run_omp_turn`, echoed
            back unchanged (including `None` when `omp`'s own default model
            answered).
        returncode: The `omp` subprocess's exit code.
        duration_seconds: Wall-clock time the subprocess call took.
    """

    text: str
    truncated: bool
    model_used: str | None
    returncode: int
    duration_seconds: float


def _truncate(text: str) -> tuple[str, bool]:
    """Truncate `text` to `_TRUNCATION_WORD_LIMIT` words if it exceeds that limit.

    Args:
        text: The raw text to check.

    Returns:
        A `(text, truncated)` pair: `text` unchanged and `truncated=False`
        when it has at most `_TRUNCATION_WORD_LIMIT` words, or the first
        `_TRUNCATION_WORD_LIMIT` words rejoined with single spaces and
        `truncated=True` otherwise.
    """
    words = text.split()
    if len(words) <= _TRUNCATION_WORD_LIMIT:
        return text, False
    return " ".join(words[:_TRUNCATION_WORD_LIMIT]), True


def _build_argv(
    combined_prompt: str,
    *,
    model: str | None,
    tools: str | None,
    no_tools: bool,
) -> list[str]:
    """Build the `omp -p` argv for one turn.

    Args:
        combined_prompt: The single prompt string to pass to `omp -p`.
        model: Passed to `--model` if set; omitted entirely when `None` so
            `omp`'s own configured default model answers (Requirement 8).
        tools: Passed as `--tools=<tools>` if set and `no_tools` is False.
        no_tools: When True, passes `--no-tools` instead of any `--tools`
            flag, disabling all tools for this turn.

    Returns:
        The full argv list, ready for `asyncio.create_subprocess_exec`.
    """
    argv = ["omp", "-p", "--mode", "text"]
    if model is not None:
        argv += ["--model", model]
    if no_tools:
        argv.append("--no-tools")
    elif tools is not None:
        argv.append(f"--tools={tools}")
    argv += ["--thinking", "off", combined_prompt]
    return argv


async def run_omp_turn(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    tools: str | None = None,
    no_tools: bool = False,
    timeout: float = 120.0,
) -> OmpResult:
    """Run exactly one agent turn as a single non-interactive `omp -p` call.

    Combines `system_prompt` and `user_prompt` into one prompt string (see
    this module's docstring for the combination strategy), invokes `omp -p
    --mode text` via `asyncio.create_subprocess_exec` (never a shell, so the
    prompt text can never be interpreted by a shell), captures stdout only
    (the response text -- `omp` writes its "Working..." progress to stderr,
    which is captured separately and never mixed into the result), and
    enforces the Requirement 9 200-word truncation backstop on the captured
    text before returning.

    Args:
        system_prompt: The agent's system/instruction text.
        user_prompt: The turn's actual task/question text.
        model: Passed to `omp --model` if set; left `None` by default so
            `omp`'s own configured default model is used (Requirement 8 --
            never hardcode a model in this engine).
        tools: Passed as `omp --tools=<tools>` if set (e.g. `"web_search"`
            for the Judge). Ignored if `no_tools` is True.
        no_tools: When True, passes `omp --no-tools`, disabling every tool
            for this turn.
        timeout: Maximum seconds to wait for `omp` to exit before raising
            `OmpTimeoutError`.

    Returns:
        An `OmpResult` with the (possibly truncated) response text.

    Raises:
        OmpTimeoutError: If `omp` does not exit within `timeout` seconds.
            The subprocess is killed before this is raised.
        RuntimeError: If `omp` exits with a non-zero return code.
    """
    combined_prompt = f"[System instructions]\n{system_prompt}\n\n[Task]\n{user_prompt}"
    argv = _build_argv(combined_prompt, model=model, tools=tools, no_tools=no_tools)

    start = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, _stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise OmpTimeoutError(
            f"omp -p call exceeded {timeout}s timeout (model={model!r})"
        ) from exc
    duration = time.monotonic() - start

    if process.returncode != 0:
        raise RuntimeError(
            f"omp -p exited with code {process.returncode} (model={model!r})"
        )

    raw_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    text, truncated = _truncate(raw_text)

    return OmpResult(
        text=text,
        truncated=truncated,
        model_used=model,
        returncode=process.returncode,
        duration_seconds=duration,
    )
