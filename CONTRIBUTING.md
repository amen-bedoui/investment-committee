# Contributing

1. `pip install -e ".[dev]"`
2. Add a test with every behaviour change; keep `python -m pytest -q` and `ruff check .` green.
3. No look-ahead: any new agent must use only `ctx.prices` (history up to the decision date) and `ctx.fundamentals` (as of publication date). The test `test_no_lookahead_in_decisions` must still pass.
4. Never commit real client/employer data or API keys (`.env`, `data/private/` are git-ignored).

New analyst: implement `name` and `analyse(ctx) -> Signal` (score in [-1, 1], confidence in [0, 1], one-line rationale) and add it to `DEFAULT_AGENTS` or pass it via `agents=`.
