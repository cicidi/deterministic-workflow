# mfangdai-agent

Reference example for the deterministic-ai-agent framework.

**Project moved to:** `/home/cicidi/project/mfangdai-ai-agent/`

## What This Demonstrates

A mortgage lead collection chatbot built on the three-layer deterministic workflow framework:

- **Layer 1**: Intent classification + E→V→T extraction pipeline (hybrid LLM + regex fallback)
- **Layer 2**: 100% deterministic business logic (lead creation, officer matching, rate quoting)
- **Layer 3**: Response generation + knowledge pool Q&A

## Built With

- `skills/implement-interview/SKILL.md` — guided the product interview (4-level time-boxed)
- `skills/auto-tdd/SKILL.md` → `ai-coworker-auto-tdd` — drove the 3-agent TDD development loop

## Test Results

64 tests pass (30 UT + 34 FT), 3 sim LLM tests available (require API key).

## See Also

- [PRD.md](./PRD.md) — full product requirements document
- [deterministic-workflow-framework](../../docs/specs/2026-06-16-deterministic-workflow-framework-design.md)
