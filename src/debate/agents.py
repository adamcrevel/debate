"""System-prompt templates for every agent in a debate.

This module only builds strings — it defines the persona text that T4's
engine layer will later hand to T2's `omp_client` as the `--system`/`-s`
prompt for each `omp -p` call. Nothing here spawns a process or imports
`subprocess`; see the layering boundary note in the project plan.
"""

from typing import Literal

Side = Literal["FOR", "AGAINST"]
Role = Literal["Lead", "Researcher", "Rebuttal"]

_WORD_LIMIT_INSTRUCTION = (
    "Answer in at most 120 words. Be concise and direct; do not pad your "
    "response to reach the limit."
)

_WEB_SEARCH_INSTRUCTION = (
    "When a claim you are about to make is central to your argument, prefer "
    "a verified web search over an unverified claim: look it up before "
    "asserting it rather than relying on memory alone."
)

_ROLE_DESCRIPTIONS: dict[Role, str] = {
    "Lead": (
        "You are the team's Lead. You deliver the team's opening statement "
        "at the start of the debate and the team's closing statement at the "
        "end, presenting the team's strongest case and tying its arguments "
        "together."
    ),
    "Researcher": (
        "You are the team's Researcher. You produce the team's evidence "
        "brief: a grounded summary of the facts, data, and sources that "
        "support your side's position, for the rest of the team to draw on."
    ),
    "Rebuttal": (
        "You are the team's Rebuttal agent. You argue the live rebuttal "
        "loop, directly responding to and countering the opposing team's "
        "points as the debate goes back and forth."
    ),
}


def build_debater_system_prompt(side: Side, role: Role, topic: str) -> str:
    """Build the system prompt for one debater persona.

    Composes a prompt identifying the agent's side (FOR or AGAINST) and its
    in-team role (Lead, Researcher, or Rebuttal — see `_ROLE_DESCRIPTIONS`
    for what each does, per Requirement 2), plus the two standing
    instructions every agent gets: a 120-word answer cap and a preference
    for verified web search over unverified claims when a claim is central
    to the argument (Requirement 9).

    Args:
        side: Which team the agent is on, ``"FOR"`` or ``"AGAINST"``.
        role: The agent's in-team role, ``"Lead"``, ``"Researcher"``, or
            ``"Rebuttal"``.
        topic: The debate's topic.

    Returns:
        The complete system-prompt text for this (side, role) persona.
    """
    stance = "arguing FOR" if side == "FOR" else "arguing AGAINST"
    role_description = _ROLE_DESCRIPTIONS[role]
    return (
        f"You are a debater on the {side} team, {stance} the motion: "
        f"\"{topic}\".\n\n"
        f"{role_description}\n\n"
        f"{_WORD_LIMIT_INSTRUCTION}\n\n"
        f"{_WEB_SEARCH_INSTRUCTION}"
    )


def build_judge_system_prompt(topic: str) -> str:
    """Build the system prompt for the Judge persona.

    The Judge is not on either team. It reviews the full question transcript
    and produces a verdict naming which side argued the question better, or
    a declared draw, with a short rationale citing specific turns by stage
    (e.g. opening, rebuttal, closing) and side (Requirement 7).

    The response's first line is required to be exactly one of five fixed
    strings (``"FOR wins"``, ``"FOR wins narrowly"``, ``"AGAINST wins"``,
    ``"AGAINST wins narrowly"``, or ``"Draw"``), so a caller can parse the
    winner deterministically instead of re-interpreting free prose (see
    `debate.render`, which depends on this exact format).

    Args:
        topic: The debate's topic.

    Returns:
        The complete system-prompt text for the Judge persona.
    """
    return (
        f"You are the Judge for a debate on the motion: \"{topic}\". You are "
        "not a member of either team and must not advocate for either side.\n\n"
        "You will be given the full transcript of one question's turns, "
        "labeled by stage (opening, rebuttal, closing) and by side (FOR or "
        "AGAINST). Review the transcript carefully and decide which side "
        "argued this question better, or whether it is a draw.\n\n"
        "Your response's first line must be exactly one of these five "
        "strings, with nothing else on that line: \"FOR wins\", \"FOR wins "
        "narrowly\", \"AGAINST wins\", \"AGAINST wins narrowly\", or "
        "\"Draw\" -- declare a draw only if neither side clearly won. Leave "
        "a blank line after it, then give a short rationale for your "
        "verdict that cites specific turns by their stage and side (for "
        "example, \"the FOR rebuttal\" or \"the AGAINST closing\").\n\n"
        f"{_WORD_LIMIT_INSTRUCTION}\n\n"
        f"{_WEB_SEARCH_INSTRUCTION}"
    )


def build_host_system_prompt(topic: str, already_asked: list[str]) -> str:
    """Build the system prompt for the Host persona used in `debate auto`.

    The Host generates the next debate question from the debate's topic. It
    is explicitly instructed to check the question it proposes against every
    question already asked in this debate, so it never repeats one
    (Requirement 4). Every already-asked question is interpolated into the
    prompt so the model has the full list to check against.

    Args:
        topic: The debate's topic.
        already_asked: Every question already asked in this debate, in the
            order they were asked. May be empty for the first question.

    Returns:
        The complete system-prompt text for the Host persona.
    """
    if already_asked:
        numbered = "\n".join(
            f"{i}. {question}" for i, question in enumerate(already_asked, start=1)
        )
        history_section = (
            "Questions already asked in this debate (do not repeat any of "
            f"these, nor ask something that is only a reworded duplicate of "
            f"one of them):\n{numbered}"
        )
    else:
        history_section = (
            "No questions have been asked in this debate yet; propose the "
            "first one."
        )

    return (
        f"You are the Host for a debate on the topic: \"{topic}\". Your job "
        "is to generate the next debate question: a specific, answerable "
        "question that lets the FOR and AGAINST teams argue opposing "
        "positions within the debate's topic.\n\n"
        f"{history_section}\n\n"
        "Check your proposed question against every question listed above "
        "before answering, and make sure it has not already been asked. "
        "Respond with only the new question text, nothing else.\n\n"
        f"{_WORD_LIMIT_INSTRUCTION}\n\n"
        f"{_WEB_SEARCH_INSTRUCTION}"
    )
