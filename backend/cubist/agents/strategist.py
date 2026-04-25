"""Person C — strategist agent.

Step 2 (this commit): hardcoded stubs so Person E can wire orchestration
end-to-end against fakes. Step 3 will replace `propose_questions` with a
real Opus call using a `submit_questions` tool. See plans/person-c-agents.md.
"""

from dataclasses import dataclass

CATEGORIES = ["prompt", "search", "book", "evaluation", "sampling"]


@dataclass
class Question:
    index: int
    category: str
    text: str


async def propose_questions(
    champion_code: str,
    history: list[dict],
) -> list[Question]:
    """Return 5 distinct improvement questions, one per category.

    Stub: returns hardcoded placeholders prefixed ``[STUB]``. Real
    implementation lands in Step 3 — calls the strategist LLM with the
    submit_questions tool, validates that exactly 5 distinct categories come
    back, and surfaces the prose verbatim (Person D shows it to the user).
    """
    del champion_code, history  # unused in stub; consumed in Step 3
    return [
        Question(
            index=i,
            category=cat,
            text=f"[STUB] Try a {cat}-based improvement to the champion.",
        )
        for i, cat in enumerate(CATEGORIES)
    ]
