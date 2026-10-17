"""Configuration for a single debate run."""

from dataclasses import dataclass


@dataclass
class DebateConfig:
    """Settings that control how one debate is run.

    Attributes:
        topic: The debate's topic. Must be non-empty and non-whitespace-only;
            validated in ``__post_init__``.
        model: The model name to pass to `omp`'s `--model` flag, or ``None``
            (the default) to let `omp` fall back to its own configured
            default model, never a model name hardcoded in this engine.
        max_rebuttal_rounds: Maximum number of rebuttal rounds (one round is
            one turn from each side) before the rebuttal loop stops.
        max_minutes: Wall-clock budget, in minutes, for the rebuttal loop.
        judge_enabled: Whether a Judge agent produces a verdict after
            closings.
    """

    topic: str
    model: str | None = None
    max_rebuttal_rounds: int = 2
    max_minutes: float = 10
    judge_enabled: bool = True

    def __post_init__(self) -> None:
        """Validate the topic is non-empty and non-whitespace-only.

        Raises:
            ValueError: If `topic` is empty or consists only of whitespace.
        """
        if not self.topic or not self.topic.strip():
            raise ValueError("topic must be a non-empty, non-whitespace string")
