"""Tests for `debate.gist_publish`.

`subprocess.run` is always patched so no test ever shells out to a real
`gh` or creates a real gist.
"""

import subprocess

import pytest

import debate.gist_publish as gist_publish_module
from debate.gist_publish import GistPublishError, publish_gist


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_secret_by_default_omits_public_flag(monkeypatch):
    """Without `public=True`, the argv passed to subprocess.run has no --public flag."""
    captured = []

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _FakeCompletedProcess(0, stdout="https://gist.github.com/x\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    url = publish_gist("content", filename="t.md")

    assert url == "https://gist.github.com/x"
    assert "--public" not in captured[0]
    assert captured[0][:3] == ["gh", "gist", "create"]


def test_public_true_adds_public_flag(monkeypatch):
    """`public=True` adds --public to the gh argv."""
    captured = []

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _FakeCompletedProcess(0, stdout="https://gist.github.com/y\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    publish_gist("content", filename="t.md", public=True)

    assert "--public" in captured[0]


def test_filename_is_used_for_the_written_file(monkeypatch):
    """The argv's file argument ends with the given filename."""
    captured = []

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _FakeCompletedProcess(0, stdout="https://gist/x\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    publish_gist("content", filename="debate-7-transcript.md")

    file_arg = captured[0][3]
    assert file_arg.endswith("debate-7-transcript.md")


def test_content_is_actually_written_to_the_file_gh_is_pointed_at(monkeypatch):
    """The file gh is pointed at actually contains the given markdown."""
    written = {}

    def fake_run(argv, **kwargs):
        from pathlib import Path

        written["text"] = Path(argv[3]).read_text()
        return _FakeCompletedProcess(0, stdout="https://gist/x\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    publish_gist("# My Markdown\n\nBody.", filename="t.md")

    assert written["text"] == "# My Markdown\n\nBody."


def test_nonzero_exit_raises_gist_publish_error_with_stderr(monkeypatch):
    """A non-zero gh exit raises GistPublishError including gh's own stderr."""

    def fake_run(argv, **kwargs):
        return _FakeCompletedProcess(1, stdout="", stderr="error: not authenticated")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GistPublishError, match="not authenticated"):
        publish_gist("content", filename="t.md")


def test_gh_not_found_raises_gist_publish_error_naming_the_problem(monkeypatch):
    """gh missing from PATH raises GistPublishError, not a bare FileNotFoundError."""

    def fake_run(argv, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GistPublishError, match="gh is not installed"):
        publish_gist("content", filename="t.md")


def test_timeout_raises_gist_publish_error(monkeypatch):
    """A gh call that hangs past the timeout raises GistPublishError, not a bare timeout."""

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=60)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GistPublishError, match="timed out"):
        publish_gist("content", filename="t.md")


def test_url_is_stripped_of_trailing_whitespace(monkeypatch):
    """The returned URL has no trailing newline from gh's own stdout."""

    def fake_run(argv, **kwargs):
        return _FakeCompletedProcess(0, stdout="https://gist.github.com/z\n\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert publish_gist("content", filename="t.md") == "https://gist.github.com/z"


def test_only_this_module_is_allowed_to_import_subprocess():
    """Smoke-check the module itself actually imports subprocess (sanity for
    the layering-boundary standing check, which greps the whole package)."""
    assert hasattr(gist_publish_module, "subprocess")
