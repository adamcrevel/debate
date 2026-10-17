"""Tests for `debate.omp_client`.

All subprocess calls are mocked via a fake `asyncio.create_subprocess_exec`
replacement -- no real `omp` invocation happens here. Async coroutines under
test are driven with `asyncio.run` from plain (sync) test functions, so no
extra pytest-asyncio dependency is needed.
"""

import asyncio

import pytest

from debate.omp_client import OmpTimeoutError, run_omp_turn


class _FakeProcess:
    """A stand-in for the object `asyncio.create_subprocess_exec` returns."""

    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
    ) -> None:
        """Store the canned stdout/stderr/returncode this fake process returns.

        Args:
            stdout: Bytes `communicate()` should return as stdout.
            stderr: Bytes `communicate()` should return as stderr.
            returncode: Exit code to report after `communicate()` resolves.
            hang: When True, `communicate()` never resolves (used to exercise
                the timeout path).
        """
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return the canned (stdout, stderr) pair, or hang forever if `hang`."""
        if self._hang:
            await asyncio.sleep(10_000)
        return self._stdout, self._stderr

    def kill(self) -> None:
        """Record that the process was killed."""
        self.killed = True

    async def wait(self) -> int:
        """Record that `wait()` was awaited after `kill()`, returning returncode."""
        self.waited = True
        return self.returncode


def _patch_exec(monkeypatch: pytest.MonkeyPatch, fake_process: _FakeProcess) -> list:
    """Patch `asyncio.create_subprocess_exec` to return `fake_process`.

    Returns:
        A list that the fake exec call appends its received argv to, so
        tests can assert on exactly what argv was constructed.
    """
    captured_argv: list = []

    async def _fake_exec(*argv: str, **kwargs: object) -> _FakeProcess:
        captured_argv.append(list(argv))
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return captured_argv


def test_builds_argv_without_model_or_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """When model and tools are None, argv omits --model and --tools entirely."""
    fake = _FakeProcess(stdout=b"hello world")
    captured = _patch_exec(monkeypatch, fake)

    result = asyncio.run(run_omp_turn("be concise", "what is 2+2?"))

    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == "omp"
    assert "-p" in argv
    assert argv[argv.index("-p") + 1 :][:2] == ["--mode", "text"]
    assert "--model" not in argv
    assert not any(a.startswith("--tools=") for a in argv)
    assert "--no-tools" not in argv
    assert "--thinking" in argv
    assert argv[argv.index("--thinking") + 1] == "off"
    # the combined prompt is the final argv element
    assert "be concise" in argv[-1]
    assert result.model_used is None
    assert "what is 2+2?" in argv[-1]


def test_builds_argv_with_model_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """When model and tools are given, argv includes --model and --tools=<value>."""
    fake = _FakeProcess(stdout=b"ok")
    captured = _patch_exec(monkeypatch, fake)

    result = asyncio.run(
        run_omp_turn(
            "sys",
            "user",
            model="anthropic/claude-haiku-4-5",
            tools="web_search",
        )
    )

    argv = captured[0]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "anthropic/claude-haiku-4-5"
    assert "--tools=web_search" in argv
    assert "--no-tools" not in argv
    assert result.model_used == "anthropic/claude-haiku-4-5"


def test_no_tools_flag_overrides_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """no_tools=True passes --no-tools and suppresses any --tools= flag."""
    fake = _FakeProcess(stdout=b"ok")
    captured = _patch_exec(monkeypatch, fake)

    asyncio.run(run_omp_turn("sys", "user", tools="web_search", no_tools=True))

    argv = captured[0]
    assert "--no-tools" in argv
    assert not any(a.startswith("--tools=") for a in argv)


def test_stdout_captured_stderr_not_mixed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The result text comes from stdout only; stderr content never leaks in."""
    fake = _FakeProcess(stdout=b"the real answer", stderr=b"Working...\nnoise")
    _patch_exec(monkeypatch, fake)

    result = asyncio.run(run_omp_turn("sys", "user"))

    assert result.text == "the real answer"
    assert "Working" not in result.text
    assert "noise" not in result.text


def test_no_truncation_at_exactly_200_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly 200 words is not truncated."""
    text = " ".join(f"w{i}" for i in range(200))
    fake = _FakeProcess(stdout=text.encode())
    _patch_exec(monkeypatch, fake)

    result = asyncio.run(run_omp_turn("sys", "user"))

    assert result.truncated is False
    assert result.text == text
    assert len(result.text.split()) == 200


def test_truncation_fires_above_200_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """201+ words is truncated to exactly the first 200, flagged truncated=True."""
    text = " ".join(f"w{i}" for i in range(250))
    fake = _FakeProcess(stdout=text.encode())
    _patch_exec(monkeypatch, fake)

    result = asyncio.run(run_omp_turn("sys", "user"))

    assert result.truncated is True
    assert len(result.text.split()) == 200
    assert result.text.split() == [f"w{i}" for i in range(200)]


def test_timeout_raises_omp_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process that never completes within `timeout` raises OmpTimeoutError."""
    fake = _FakeProcess(hang=True)
    _patch_exec(monkeypatch, fake)

    with pytest.raises(OmpTimeoutError):
        asyncio.run(run_omp_turn("sys", "user", timeout=0.01))

    assert fake.killed is True
    assert fake.waited is True


def test_nonzero_returncode_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A nonzero omp exit code raises RuntimeError rather than returning a result."""
    fake = _FakeProcess(stdout=b"", stderr=b"omp: error", returncode=1)
    _patch_exec(monkeypatch, fake)

    with pytest.raises(RuntimeError):
        asyncio.run(run_omp_turn("sys", "user"))
