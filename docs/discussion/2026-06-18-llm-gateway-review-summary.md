# Contrarian Review Summary — LLM Gateway Spec

- **Date:** 2026-06-18
- **Target:** `docs/specs/2026-06-17-llm-gateway.md` (v0.3.0 → v0.3.1)
- **Review Skill:** `ai-coworker-contrarian-review`
- **Agents:** 4 (Agent 1: Web-Searching Contrarian, Agent 2: MiniMax Cross-Model, Agent 3: Debate Coordinator, Agent 4: Judge)

## Statistics

| Metric | Count |
|--------|-------|
| Issues raised (Agent 1) | 18 |
| Issues raised (Agent 2) | 18 |
| Total unique issues | 36 |
| Unanimous bug fixes applied | 14 |
| Design conflicts resolved by Judge | 3 |
| Compromises (partial acceptance) | 3 |
| Rejected proposals | 0 |
| Debate rounds used | 0 (no direct conflicts — agents found complementary issues) |

## Modifications Applied

### Bug Fixes (14)
| # | Source | Section | Fix |
|---|--------|---------|-----|
| 1 | A2#1 | §3.3 | Retry budget formula: removed `+ initial attempt`, now references §4.4 |
| 2 | A2#4 | §8 | `total_attempts: 6` → `5` (matches corrected formula) |
| 3 | A2#5 | §2.2 | Added `coercions?: CoercionRecord[]` to LLMResult struct |
| 4 | A2#2 | §4.2 | Flow diagram: Tier 1 now shows 2 failures before escalation (was 1) |
| 5 | A2#6 | §3.2 | Added `"true"→true` and `"false"→false` to coercion table |
| 6 | A2#7 | §3.3 | Error injection: confidence template changed to `field_name (value, threshold: N)` |
| 7 | A2#3 | §4.5 | Audit trail: added note clarifying scenario (Tier 0 exhausted, Tier 1 success) |
| 8 | A2#12 | §4.6/§5 | Renamed: "Implementation Options" → "Model Escalation Strategies" / "Gateway Validation Strategies" |
| 9 | A2#8 | §4.2 | Added max_tokens guard (pre-call estimate, fail fast on truncation) |
| 10 | A2#9 | §4.9 | Clarified sticky tier TTL: checked once per call, at initiation |
| 11 | A2#10 | §3.5 | Clarified warn_and_accept escalation: does NOT consume escalation slots |
| 12 | A2#13 | §4.4 | Added `llm_extra_retry: false` config for last tier, with trade-off note |
| 13 | A2#14 | §4.9 | Added `max_sticky_tier` trade-off note (cost guard vs repeated escalation) |
| 14 | A2#18 | §3.5 | Clarified confidence=0 edge case: gate disabled when minimum is saturated |

### Judge Rulings (3)
| # | Conflict | Ruling | Key Change |
|---|----------|--------|------------|
| 1 | Agent 1: Relax mandatory output_schema for Layer 3 | **COMPROMISE** | Keep mandatory JSON (per AD#11); added §3.6 Free-Text Handling with minimal-schema guidance; updated §7.3 preamble |
| 2 | Agent 1: Remove deterministic fallback (quality concerns) | **COMPROMISE** | Keep fallback (per VISION.md §6.2); added post-fallback schema validation, `min_field_confidence` gate (0.5), restricted to extraction nodes only |
| 3 | Agent 1: Replace x-threshold with standard minimum | **COMPROMISE** | Removed `x-threshold` custom keyword; now uses standard JSON Schema `minimum`; gateway differentiates quality vs structural violations by field identity |

### Open Improvements (not yet applied, deferred for future version)
| # | Source | Section | Suggestion |
|---|--------|---------|------------|
| 1 | A1#3 | §6 | Add Pydantic model as schema definition option (Instructor/LangChain pattern) |
| 2 | A1#7 | §4 | Add pre-call checks before escalation (context window, rate limits, health) |
| 3 | A1#9 | §4.6 | Augment Dynamic Routing with ML-based options (liteLLM Adaptive Router) |
| 4 | A1#11 | §3.3 | Add cost-based retry budget alongside count-based budget |
| 5 | A1#13 | §5 | Add Option D: Validator-Enhanced Post-Process (Instructor/Guardrails) |
| 6 | A1#14 | §3.3 | Add per-error-type retry policy (liteLLM pattern) |
| 7 | A1#15 | §4.5/§8 | Unify audit structures across escalation and errorNode |
| 8 | A1#16 | §9.5 | Resolve open question: prompt strategy on escalation (carry_forward/reset/summarize) |
| 9 | A1#17 | §9.2 | Move caching from open question to documented feature (§3.7) |
| 10 | A1#18 | §9.3 | Move $ref/$defs handling from open question to §6.3 Schema Preprocessing |

### Additional Improvements Applied (from Agent 2)
| # | Source | Section | Fix |
|---|--------|---------|-----|
| 15 | A2#11 | §4.2 | Clarified deterministic fallback scope: extraction nodes only, not available for response |
| 16 | A2#16 | §4.2 | Added circuit breaker for total provider outage (30s circuit-open state) |
| 17 | A2#17 | §4.1 | Standardized model names with version suffixes (claude-sonnet-4-20250514 etc.) |

## Remaining Open Questions (spec §9)
| # | Question | Status |
|---|----------|--------|
| 1 | Streaming validation vs full-response | Open |
| 2 | Caching identical LLM calls | Deferred (see A1#17 above) |
| 3 | $ref/$defs handling across providers | Deferred (see A1#18 above) |
| 4 | Schema violation traces to LangSmith | Open |
| 5 | Prompt reset vs carry-forward on escalation | Deferred (see A1#16 above) |
| 6 | Per-node escalation configuration | Deferred |
| 7 | Cross-provider system prompt/schema directive handling | Open |
