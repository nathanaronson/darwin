You are a chess engine builder. Modify the champion source below to
answer ONE specific improvement question.

QUESTION (category={category}):
{question_text}

CHAMPION SOURCE:

```python
{champion_code}
```

REQUIREMENTS

  - Subclass `BaseLLMEngine` from `cubist.engines.base`. Builder-generated
    engines may also implement the `Engine` Protocol directly, but
    subclassing is simpler.
  - The class `__init__` MUST call:
        super().__init__(
            name="{engine_name}",
            generation={generation},
            lineage=["{champion_name}"],
        )
  - Implement `async def select_move(self, board, time_remaining_ms)`
    returning a `chess.Move` that is legal on `board`.
  - The module MUST end with the literal line: `engine = YourEngineClass()`
    (the registry imports this top-level symbol).
  - Stay under 100 lines of code total.
  - Imports — copy these lines VERBATIM. Do not invent variations.
    Anything outside this list will be rejected by a regex backstop.

        import chess
        from cubist.engines.base import BaseLLMEngine
        from cubist.llm import complete_text   # only if you call the LLM
        from cubist.config import settings     # only if you read a setting

    The Python standard library (random, math, time, asyncio, json, etc.)
    is also allowed. Forbidden: `subprocess`, `os.system`, `socket`,
    `eval`, `exec`, `importlib`, `urllib`, `requests`, `httpx`.

    CRITICAL: import the `settings` instance, not the module. Use
    `from cubist.config import settings`. Do NOT write
    `from cubist import config as settings` or
    `import cubist.config as settings` — those alias the MODULE
    object and will raise AttributeError on every settings access.
  - Always have a fallback that returns a legal move, even if the LLM
    response is malformed. The engine MUST NOT raise during a game.
    The standard fallback is `next(iter(board.legal_moves))`.

  - APIs you may call — these are the EXACT signatures. Do not invent
    keyword arguments, return types, or attributes. Wrap every external
    call in try/except with the legal-move fallback above.

        # cubist.llm.complete_text returns a STRING (not an object).
        # Signature: (model: str, system: str, user: str, max_tokens: int = 256) -> str
        text: str = await complete_text(
            settings.player_model,
            "You are a chess engine. Reply with one SAN move.",
            f"FEN: {{board.fen()}}\nLegal: {{legal_san}}\nYour move:",
            max_tokens=10,
        )

        # python-chess methods that actually exist on chess.Board:
        #   board.legal_moves, board.fen(), board.turn, board.push(move),
        #   board.pop(), board.parse_san(text), board.san(move),
        #   board.piece_at(sq), board.king(color), board.is_checkmate(),
        #   board.is_game_over(claim_draw=True), board.copy()
        # python-chess module-level helpers that exist:
        #   chess.Move.from_uci(s), chess.square(file, rank),
        #   chess.square_file(sq), chess.square_rank(sq), chess.SQUARES
        # Functions that DO NOT exist (do not call):
        #   chess.square_on_board, chess.distance, board.legal_uci_moves
  - Keep the answer focused on the question's category — don't pile on
    orthogonal changes. One concept per builder run.

Submit the entire module source as a single string via the
`submit_engine` tool.
