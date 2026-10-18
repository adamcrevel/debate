"""Publishing a rendered transcript to a GitHub gist via the `gh` CLI.

This is the only module in `src/debate` allowed to shell out to `gh` --
parallel to `omp_client.py` being the only one allowed to shell out to
`omp` -- see the layering boundary standing check in the project plan.
"""

import subprocess
import tempfile
from pathlib import Path


class GistPublishError(RuntimeError):
    """Raised when `gh gist create` is not usable or fails."""


def publish_gist(markdown: str, *, filename: str, public: bool = False) -> str:
    """Create a GitHub gist containing `markdown` and return its URL.

    Writes `markdown` to a temporary file and runs `gh gist create` against
    it -- secret by default (`gh`'s own default), `public=True` passes
    `gh`'s `--public` flag instead -- then returns the URL `gh` prints to
    stdout on success.

    Args:
        markdown: The full Markdown document to publish.
        filename: The filename `gh` gives the gist's one file (controls its
            syntax highlighting and download name on GitHub).
        public: Create a public gist instead of the default secret one.

    Returns:
        The new gist's URL, exactly as `gh gist create` printed it
        (trailing whitespace stripped).

    Raises:
        GistPublishError: If `gh` is not on `PATH`, is not authenticated,
            or exits non-zero for any other reason -- `gh`'s own stderr is
            included in the message rather than a bare traceback.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / filename
        path.write_text(markdown)
        argv = ["gh", "gist", "create", str(path)]
        if public:
            argv.append("--public")

        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as exc:
            raise GistPublishError(
                "gh is not installed or not on PATH -- install the GitHub CLI "
                "and run `gh auth login` before using --publish."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GistPublishError("gh gist create timed out after 60 seconds.") from exc

    if result.returncode != 0:
        raise GistPublishError(
            f"gh gist create failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()
