# Agent 2 (MiniMax-angle) Review: LLM Gateway Spec — Issues Found

> **Reviewer**: Agent 2 (independent cross-model perspective)
> **Document**: `docs/specs/2026-06-17-llm-gateway.md` v0.3.0
> **Date**: 2026-06-18

---

## Issue 1: Retry budget formula contradiction between §3.3 and §4.4

section: §3.3 (Retry on Violation) vs §4.4 (Tier-Aware Retry Budget)
issue_type: correctness
description: >
  §3.3 line 149 defines the total retry budget when escalation is enabled as:
  `total budget = Σ(tier.failures_before_escalation) + initial attempt`.
  With tiers [2,2,1] that yields 2+2+1+1 = 6.
  However, §4.4 lines 334-335 define it as:
  `max_total_calls = Σ(tier.failures_before_escalation) = 2 + 2 + 1 = 5`.
  The "+ initial attempt" term in §3.3 double-counts the first call on Tier 0,
  which is already included in Tier 0's `failures_before_escalation` count.
  The changelog (v0.3.0) confirms §4.4 was corrected from "Σ+1" to "Σ", but
  §3.3 was not updated. Two sections now give different answers for the same
  budget ceiling. A reader following §3.3's formula would allocate 6 attempts
  but the gateway would enforce 5 — a runtime mismatch.
proposed_fix: >
  In §3.3 line 149, change:
  `// total budget = Σ(tier.failures_before_escalation) + initial attempt`
  to:
  `// total budget = Σ(tier.failures_before_escalation)   (see §4.4)`

---

## Issue 2: §4.2 escalation flow diagram contradicts §4.3 YAML configuration

section: §4.2 (Escalation Flow) vs §4.3 (Escalation Triggers YAML)
issue_type: consistency
description: >
  The §4.2 flow diagram (lines 263-279) shows:
  - Tier 0: 2 failures → escalate ✓
  - Tier 1: **1 failure** → deterministic fallback → escalate to Tier 2
  - Tier 2: 1 call → SUCCESS

  But both the text at line 281 ("retries up to `failures_before_escalation` times, default: 2")
  and the YAML config at lines 317-321 (`failures_before_escalation: 2` for gpt-4o, Tier 1)
  say Tier 1 should allow 2 failures before escalation. The flow diagram shows only 1 failure
  on Tier 1, misrepresenting the actual behavior for the default configuration.
proposed_fix: >
  Either:
  (a) Add a second failure on Tier 1 in the diagram (Attempt 3a and 3b on Tier 1,
  then escalate), making the example 5 attempts worst-case and adding a note
  that the last call succeeds on Tier 2; or
  (b) Add a note explicitly stating the diagram uses `failures_before_escalation: 1`
  for Tier 1 (a simplified example), not the documented default of 2.

---

## Issue 3: §4.5 audit trail doesn't match §4.2 escalation flow example

section: §4.5 (Audit Trail)
issue_type: consistency
description: >
  §4.2 depicts a 3-tier escalation path ending at Tier 2 (gpt-4.1): Tier 0→Tier 1→Tier 2→SUCCESS.
  But §4.5's audit trail JSON (lines 354-378) shows:
  - Only ONE escalation record (Tier 0 → Tier 1)
  - `final_tier_used: gpt-4o` (Tier 1, not Tier 2)
  - `total_attempts: 4`

  These describe an entirely different scenario (Tier 0 exhausts, Tier 1 succeeds on its
  second attempt — only one escalation). The reader naturally expects the audit trail
  to illustrate the flow example immediately above it. Instead they see a different scenario
  with no explanation of the mismatch. Additionally, no deterministic fallback attempt is
  recorded in the audit JSON, despite §4.2 showing it as a mandatory step before each escalation.
  If deterministic fallback is part of the flow, the audit trail must capture it.
proposed_fix: >
  Add a second audit trail example matching the §4.2 3-tier escalation path,
  OR add a note above the §4.5 JSON stating: "Example: Tier 0 fails twice,
  Tier 1 succeeds on second attempt (only one escalation)." Also add a
  `deterministic_fallback_attempted: true/false` field (with result) to the
  escalation record.

---

## Issue 4: §8 errorNode example shows `total_attempts: 6` — no configured budget produces 6

section: §8 (Integration with errorNode)
issue_type: correctness
description: >
  Line 693: `total_attempts: 6, tiers_exhausted: 3, last_tier: "gpt-4.1"`.
  With 3 tiers configured as [2,2,1]:
  - Non-LLM max = 2+2+1 = **5**
  - LLM max = 3+3+2 = **8**
  Neither equals 6. The value 6 could only arise if all three tiers had
  `failures_before_escalation: 2` (2+2+2=6), but the YAML config in §4.3
  explicitly sets the last tier to 1. The number 6 appears to be a leftover
  from before the §4.4 formula correction, or an arbitrary placeholder.
proposed_fix: >
  Change `total_attempts: 6` to `total_attempts: 5` (for non-LLM, all tiers
  exhausted) or `total_attempts: 8` (for LLM, all tiers exhausted), with a
  note indicating which scenario is depicted. Also change `tiers_exhausted: 3`
  to be consistent with the tier count shown in the YAML config.

---

## Issue 5: `LLMResult` struct in §2.2 lacks `coercions` field but §3.2 claims coercions are recorded there

section: §3.2 (Validation Checks) vs §2.2 (Call Output)
issue_type: consistency
description: >
  §3.2 line 122 states: "All coercions are recorded in the `LLMResult` with
  original and coerced values for audit." However, the `LLMResult` struct
  defined in §2.2 (lines 56-65) has only six fields: `data`, `raw`, `model`,
  `usage`, `attempts`, `validated`. There is no `coercions` field and no
  `coercion_loss` counter. The coercion audit JSON at lines 124-137 implicitly
  expects a `coercions` array in the result, but the contract doesn't include it.
proposed_fix: >
  Add to the `LLMResult` struct in §2.2:
  ```
  coercions?:    CoercionRecord[]  // type coercion audit entries (see §3.2)
  ```
  And define `CoercionRecord` inline or by reference to §3.2.

---

## Issue 6: Type coercion table missing `"true"`/`"false"` boolean string conversions

section: §3.2 (Validation Checks)
issue_type: completeness
description: >
  The coercion table (lines 113-120) lists `"yes" → true` as the boolean
  string coercion example. However, the most common JSON boolean string
  representations in LLM output are `"true"` and `"false"` (actual JSON
  boolean values serialized as strings). Neither appears in the table.
  A reader might reasonably wonder: is `"true"` coerced to `true`? Is it
  classified as lossy or unparseable? Omitting these leaves a gap.
proposed_fix: >
  Add a row to the coercion table:
  | `"true"` → `true` (str→bool) | Yes | `debug` | Standard boolean string |
  | `"false"` → `false` (str→bool) | Yes | `debug` | Standard boolean string |

---

## Issue 7: Error injection `confidence_below_threshold` doesn't follow the stated `category: detail` pattern

section: §3.3 (Retry on Violation)
issue_type: clarity
description: >
  Line 169 defines the error template for `confidence_below_threshold` as
  `value < threshold`. In the structured error block example (line 158),
  this renders as:
  `- confidence_below_threshold: 0.45 < 0.7`

  However, every other error category follows a `category: detail_value`
  pattern:
  - `missing_required_field: "confidence"`
  - `type_mismatch: "confidence" (expected: number, got: string "high")`
  - `invalid_enum: "field_name": "value" not in [allowed_values]`

  Confidence below threshold breaks the pattern — it has the expression as the
  "detail" instead of using a structured format. Was this intentional? The
  table could define a more parseable format.
proposed_fix: >
  Either change the template to:
  `value (threshold)`, e.g. `- confidence_below_threshold: 0.45 (threshold: 0.7)`
  or add a column clarifying that this category uses a different format.

---

## Issue 8: `max_tokens` too small for `output_schema` creates an unrecoverable retry loop

section: §4 (Progressive Model Escalation) / §3.1 (Validation Pipeline)
issue_type: missing_edge_case
description: >
  If `max_tokens` is set too small for the required `output_schema` (e.g.,
  `max_tokens: 200` for a schema requiring 20 fields), every LLM response
  will be truncated → invalid JSON → retry. The retry will fail for the same
  reason (token limit unchanged), consuming the entire retry budget (potentially
  5-8 calls across 3 tiers) before hitting errorNode. This is wasteful and
  hides the real root cause. Neither §3.1 (validation pipeline) nor §4
  (escalation) addresses token-limit-induced failures.
proposed_fix: >
  Add a pre-call validation check: if the estimated token requirement of the
  output_schema (field count × average tokens per field) exceeds `max_tokens`,
  emit a `warning`-level audit entry. Optionally add a `truncated_output`
  failure type to the escalation trigger table in §4.3 that causes immediate
  escalation (skip retries on same tier) since retrying with the same token
  limit is guaranteed to fail.

---

## Issue 9: Sticky tier TTL expiry mid-request behavior undefined

section: §4.9 (Sticky Tier)
issue_type: missing_edge_case
description: >
  §4.9 defines a TTL of 300 seconds for sticky tier memory. What happens
  if the TTL expires while an LLM call is in-flight? Does the gateway:
  (a) check at call start and hold the sticky tier until completion,
  (b) re-check between retry attempts within the same call, or
  (c) re-check between tiers if escalation occurs?
  The spec is silent on this. In a worst-case scenario, if (b) or (c),
  a long-running escalation (multiple tiers with backoff delays) could
  lose sticky state mid-call and reset to Tier 0, causing an infinite
  re-escalation loop.
proposed_fix: >
  Add a sentence: "TTL is checked once per LLM call, at call initiation.
  If the sticky tier is found valid at the start of the call, it is held
  for the entire call (including all escalation tiers within that call).
  Expiry only affects subsequent calls."

---

## Issue 10: `warn_and_accept` confidence threshold mode + escalation counting behavior undefined

section: §3.5 (Confidence Threshold Gate)
issue_type: clarity
description: >
  §3.5 line 229 defines `on_violation: retry | warn_and_accept | strict_reject`.
  Line 232 states: "When escalation is enabled (§4), confidence threshold
  violations count toward `failures_before_escalation`." But this is only
  sensible for `retry` and `strict_reject` modes. In `warn_and_accept` mode,
  the response is accepted and returned — there is no retry. Does a
  `warn_and_accept`-classified confidence violation still count toward
  escalation? If yes, a SINGLE `warn_and_accept` event on Tier 0 would
  consume an escalation slot, which seems wrong (the call succeeded).
proposed_fix: >
  Clarify: "Confidence threshold violations count toward
  `failures_before_escalation` only when `on_violation` is `retry` or
  `strict_reject`. In `warn_and_accept` mode, the call is treated as a
  success and does not count toward escalation."

---

## Issue 11: Deterministic fallback described as extraction-only; applicability to decision nodes unclear

section: §4.2 (Escalation Flow)
issue_type: completeness
description: >
  §4.2 line 267 describes deterministic fallback as "keyword/regex extraction"
  and line 281 calls it "keyword or regex extraction against the last raw LLM
  response to salvage partial data." This language is extraction-centric.
  However, the gateway serves all three layers including Layer 2 Decision
  nodes (which output route/enum values, not extracted entities). Can
  deterministic fallback salvage a route value (e.g., `auto_approve` vs
  `manual_review`) from raw text? The spec should clarify whether
  deterministic fallback applies to decision and response nodes, and if so,
  how keyword matching on enums works differently from entity extraction.
proposed_fix: >
  Add a sentence: "Deterministic fallback applies to extraction nodes
  (keyword/regex against raw text). For decision nodes, fallback uses enum-value
  substring matching against the raw LLM response. For response nodes,
  deterministic fallback is typically disabled since free-text generation
  cannot be salvaged deterministically."

---

## Issue 12: Duplicate section name "Implementation Options" for both §4.6 (escalation) and §5 (gateway strategy)

section: §4.6 and §5
issue_type: clarity
description: >
  Both §4.6 and §5 are titled "Implementation Options." §4.6 covers model
  escalation implementation strategies (Fixed Tiers, Provider-Cascade,
  Dynamic Routing). §5 covers gateway validation strategies (Native,
  Post-Process, Hybrid). Each also has a "Comparison Matrix" subsection
  (§4.7 and §5.4) and each uses Options A/B/C. A cross-reference saying
  "see Option C" is ambiguous — the reader doesn't know whether it refers
  to Dynamic Routing or Hybrid validation. The changelog even uses §4
  heading "Progressive Model Escalation" correctly but the section
  numbering doesn't differentiate the two option sets.
proposed_fix: >
  Rename §4.6 to "Model Escalation Strategies" (or similar) and §5 to
  "Gateway Validation Strategies." Keep A/B/C labels but qualify
  cross-references (e.g., "Escalation Option C" vs "Gateway Option C").

---

## Issue 13: LLM +1 per-tier gives last tier 2 attempts, contradicting "fail fast" intent

section: §4.4 (Tier-Aware Retry Budget) vs §4.3 YAML
issue_type: consistency
description: >
  §4.3 YAML line 326: `failures_before_escalation: 1    # last tier: fail fast to errorNode`.
  The intent is clear — on the most expensive model, fail after 1 attempt.
  However, §4.4 line 347 applies LLM +1 per tier:
  `LLM max calls: (2+1) + (2+1) + (1+1) = 3 + 3 + 2 = 8`
  The last tier gets 1+1 = 2 attempts, not 1. LLM nodes on the last tier
  will always attempt twice, undermining the "fail fast" cost-saving intent.
  The +1 per tier is intended to compensate for LLM non-determinism, but
  on the last (most expensive) tier this may be counterproductive.
proposed_fix: >
  Either: (a) Carve out the last tier from LLM +1: add `llm_extra_retry:
  true` field to the tier config, defaulting to `false` on the last tier;
  or (b) Document the trade-off explicitly — "LLM +1 applies to all tiers
  including the last, meaning the most expensive model may be called twice
  before errorNode. The `failures_before_escalation: 1` on the last tier
  is a non-LLM default; for LLM nodes the effective limit is 2."

---

## Issue 14: `max_sticky_tier` trade-off not discussed

section: §4.9 (Sticky Tier)
issue_type: trade_off_gap
description: >
  §4.9 line 487: `max_sticky_tier: 1   # never stick above medium (cost guard).`
  This is presented as a safety feature, but the downside is not discussed:
  if only Tier 2 (large model) consistently produces valid output for a given
  `(node_id, intent)` pair, every call will waste 2 attempts on Tier 0 and 1-2
  attempts on Tier 1 before reaching Tier 2. The cost guard saves money on
  sticking, but costs money on repeated escalation. There is no mention of
  this trade-off or guidance on when to raise `max_sticky_tier`.
proposed_fix: >
  Add a note: "If `max_sticky_tier` is set below the tier that consistently
  succeeds for a given intent, each call will incur escalation overhead.
  This is a deliberate cost-vs-latency trade-off: you accept repeated
  escalation cost to prevent permanent lock-in to an expensive model.
  Monitor escalation rates per intent to tune `max_sticky_tier`."

---

## Issue 15: `x-threshold` auto-injection from `default_min` mechanism not described

section: §3.5 (Confidence Threshold Gate)
issue_type: clarity
description: >
  §3.5 defines `x-threshold` as a schema-level extension and
  `default_min: 0.7` as a fallback "when schema omits x-threshold"
  (line 228). However, the mechanism is underspecified:
  - Does the gateway inject `x-threshold` into every schema that has a
    `confidence` field of type `number`?
  - Or only when the `llm.validation.confidence_threshold.enabled` flag is true?
  - What if the schema already has `minimum: 0` but no `x-threshold` — does the
    gateway inject `x-threshold: 0.7` at runtime?
  - What if the `confidence` field is not named "confidence" (e.g., `score`)?
  The spec implies auto-detection but doesn't define the detection rules.
proposed_fix: >
  Add: "The gateway detects the confidence-threshold-gated field by scanning
  the output_schema for a property whose key matches `confidence_field_name`
  (configurable, default: `confidence`) and whose type is `number`. If found
  and the property lacks `x-threshold`, the gateway injects `x-threshold` with
  the value of `llm.validation.confidence_threshold.default_min`."

---

## Issue 16: All LLM providers down — no explicit handling described

section: §4 (Progressive Model Escalation)
issue_type: missing_edge_case
description: >
  §4.6 Option B (Provider-Cascade) mentions "provider outage handled" as a
  strength, but the document never explicitly describes what happens when ALL
  providers return `provider_error` (timeout, 5xx). The escalation chain would
  exhaust all tiers of all providers, then reach errorNode. But should the
  gateway enter a circuit-breaker state? Should it cache the failure to avoid
  re-attempting on the next call? The spec defers completely to errorNode
  without guidance on the "total provider outage" scenario, which is a
  realistic operational concern.
proposed_fix: >
  Add to §4.2 or §4.3: "If all tiers across all providers return provider_error,
  the gateway enters a 'circuit-open' state for `circuit_breaker_ttl_seconds`
  (default: 30 seconds), during which all LLM calls immediately route to
  errorNode with strategy `escalate_to_human` without attempting any provider."
  Reference the existing errorNode strategies in §8.

---

## Issue 17: Model naming inconsistency between §4.1 and §4.6

section: §4.1 (Model Tiers) vs §4.6 (Implementation Options)
issue_type: clarity
description: >
  §4.1 line 248 lists "claude-haiku → claude-sonnet → claude-opus" as the
  Anthropic tier chain. §4.6 Option B (line 416) uses
  "claude-sonnet-4-20250514" and "claude-opus-4-20250514". §2.1 line 49
  uses "claude-sonnet-4-20250514" as an example model ID.
  The §4.1 names lack version suffixes and are ambiguous — does "claude-sonnet"
  mean Sonnet 3.5, Sonnet 4, or the latest available? The fully-qualified IDs
  used elsewhere are better practice for a deterministic framework. The
  abbreviated names in §4.1 are presented as canonical examples but don't
  match the concrete identifiers used elsewhere.
proposed_fix: >
  Standardize model names in §4.1 to match §4.6 and §2.1:
  `claude-haiku-3-5 → claude-sonnet-4-20250514 → claude-opus-4-20250514`
  Or add a note that §4.1 uses abbreviated names for readability and
  §4.6 uses fully-qualified IDs for configuration.

---

## Issue 18: Confidence threshold of 0 — degenerate behavior undefined

section: §3.5 (Confidence Threshold Gate)
issue_type: missing_edge_case
description: >
  If `x-threshold: 0` is set (the JSON Schema `minimum: 0` already allows 0),
  then `confidence >= 0` is always true and the threshold gate is effectively
  disabled but still active. Is `x-threshold: 0` treated as "gate disabled"
  or "gate with threshold 0"? Does the gateway skip the check when threshold
  equals the schema minimum? The behavior is undefined for this edge.
proposed_fix: >
  Add: "If `x-threshold` equals the schema's `minimum` value (e.g., both 0),
  the confidence threshold gate is treated as disabled — the value always
  satisfies the comparison and no retry is triggered. To explicitly disable
  the gate per-schema, omit `x-threshold` and set
  `llm.validation.confidence_threshold.enabled: false`."

---

## Summary Table

| # | Section | Type | Severity |
|---|---------|------|----------|
| 1 | §3.3 vs §4.4 | correctness | **High** — formula conflict breaks budget calculation |
| 2 | §4.2 vs §4.3 | consistency | **High** — flow diagram shows wrong tier behavior |
| 3 | §4.5 | consistency | **Medium** — audit trail doesn't match preceding example |
| 4 | §8 | correctness | **Medium** — artifact value doesn't match any formula |
| 5 | §3.2 vs §2.2 | consistency | **Medium** — struct missing documented field |
| 6 | §3.2 | completeness | Low — minor gap in coercion table |
| 7 | §3.3 | clarity | Low — formatting inconsistency |
| 8 | §4 | missing_edge_case | **Medium** — max_tokens too small causes wasteful loops |
| 9 | §4.9 | missing_edge_case | Low — TTL edge case undefined |
| 10 | §3.5 | clarity | Low — escalation counting in warn_and_accept mode |
| 11 | §4.2 | completeness | Low — extraction-centric language |
| 12 | §4.6/§5 | clarity | Low — duplicate section names |
| 13 | §4.4 vs §4.3 | consistency | **Medium** — LLM +1 undermines fail-fast |
| 14 | §4.9 | trade_off_gap | Low — missing cost trade-off discussion |
| 15 | §3.5 | clarity | Low — mechanism underspecified |
| 16 | §4 | missing_edge_case | **Medium** — total provider outage unaddressed |
| 17 | §4.1 vs §4.6 | clarity | Low — model name drift |
| 18 | §3.5 | missing_edge_case | Low — degenerate threshold behavior |
