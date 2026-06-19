# Judge Rulings — LLM Gateway Spec Review

> **Target Document:** `docs/specs/2026-06-17-llm-gateway.md` (v0.3.0)
> **Review Type:** Adversarial multi-agent review — Agent 4 (The Judge), final authority, no appeals
> **Date:** 2026-06-18

---

## Ruling Criteria (in priority order)

1. **Evidence strength** — citations and industry patterns beat opinions
2. **Alignment with project principles** — VISION.md, CLAUDE.md
3. **Change safety** — does the fix introduce new problems?

---

## Ruling 1: Mandatory `output_schema` — Relaxation for Layer 3

**Agent 1 Proposal:** Allow `response_mode: free_text` for Layer 3 that bypasses JSON validation entirely.

### Verdict: **COMPROMISE**

### Rationale

**Evidence Analysis:**
Agent 1 correctly establishes that structured output is opt-in across OpenAI, Anthropic, and LangChain — no major provider or framework treats it as mandatory. This is undisputed. However, the framework's position is an *intentional* opinionated constraint, not an oversight. Architecture Decision #11 (VISION.md §5, dated 2026-06-17) explicitly states: "Structured output always; free text only in Layer 3." The framework chooses mandatory JSON as a compliance guarantee for regulated industries — the exact environment where optional JSON mode would be circumvented.

**Project Principles Alignment:**
VISION.md §6.3 contains two clauses in tension: (a) "All LLM output is JSON" and (b) "Free-text limited to Layer 3 (Response)." The current spec reconciles these by wrapping Layer 3 output in a minimal JSON envelope (e.g., `{"text": "...", "components": [...]}` — see spec §7.3). This is a defensible interpretation: free-text *content* is allowed in Layer 3, but it must be contained within a validated JSON structure. The JSON envelope provides auditability, PII scrubbing hooks, and machine-parsability without constraining the content quality.

Allow raw free-text to bypass the gateway would:
- Create a validation gap exploitable in regulated workflows
- Break the framework guarantee that `LLMResult.data` is always valid JSON
- Undermine the gateway's role as the single enforcement point for output structure

**Change Safety:**
Agent 1's quality concern has merit: LLMs *can* produce stilted text when shoehorned into complex schemas. The fix should minimize schema complexity for Layer 3, not remove the schema requirement.

### Implementation

In `docs/specs/2026-06-17-llm-gateway.md`:

**1. Add to §3.1 (Validation Pipeline) or a new §3.6, text preservation guidance:**

Add after §3.5 a new section:

```
### 3.6 Layer 3 Free-Text Handling

Layer 3 (Response) is the only layer where free-text content is permitted (VISION.md §6.3). To
avoid degrading output quality, Layer 3 `output_schema` definitions SHOULD use minimal schemas
that wrap free text in a thin JSON envelope:

```yaml
# Preferred: minimal envelope — JSON structural constraint is negligible
response_nodes:
  generate_response:
    executor: llm
    output_schema:
      text:
        type: string
        required: true
      citations:
        type: array
        items: { type: string }
        required: false
```

The gateway does NOT validate the *content quality* of the `text` field — only that it is a
valid string. This ensures every LLM output is structured and auditable while preserving
free-text generation quality.

Layer 3 nodes operate with `temperature: 0.3` (per VISION.md §6.3) and may use
`on_violation: warn_and_accept` for their `output_schema` to avoid retry loops on
free-text fields where schema shape is not critical.
```

**2. Update §7.3 (Layer 3 — Response) preamble:**

Replace the current implicit stance with explicit guidance:

```markdown
### 7.3 Layer 3 — Response

The gateway still requires `output_schema` for Layer 3 nodes, but the schema SHOULD be
minimal — typically a `text: string` envelope plus optional structured metadata. The
gateway validates that the JSON structure matches; it does NOT validate the quality of
the free-text content within. This preserves the compliance guarantee (all LLM output
is structured and auditable) without constraining generation quality.
```

---

## Ruling 2: Deterministic Fallback Before Escalation

**Agent 1 Proposal:** Remove the deterministic fallback step between LLM retries and model escalation, citing lack of quality gates, no known industry pattern, and salvaging garbage from failed LLM output.

### Verdict: **COMPROMISE**

### Rationale

**Evidence Analysis:**
Agent 1 correctly observes that liteLLM's fallback mechanism operates between model groups, not as a pre-escalation keyword/regex step within the same call chain. No major industry framework implements this pattern. However, the framework's value proposition is precisely to introduce patterns that the industry does not yet standardize — deterministic extraction techniques (regex/keyword) predate LLMs by decades and are well-understood.

**Project Principles Alignment:**
VISION.md §6.2 explicitly lists "Deterministic fallback (regex/keyword for every extractable field)" as a core framework pattern. Architecture Decision #3 (LLM-assisted NLU + deterministic core) reinforces that "execution must be auditable." Removing this feature would violate explicit vision requirements. However, VISION.md §6.5 also requires that "All errors → errorNode" with defined strategies — the current spec's fallback risks silently accepting wrong data, which conflicts with error handling principles.

**Change Safety:**
Agent 1 has identified real gaps:
1. No post-fallback schema validation (risk: accepting garbage)
2. No quality thresholds for partial extraction
3. The 100ms timeout is arbitrary, not calibrated
4. Fallback applied uniformly to all node types, including decision nodes where regex on failed LLM output is meaningless

The fix must preserve the feature (per vision) while closing these safety gaps.

### Implementation

In `docs/specs/2026-06-17-llm-gateway.md`:

**1. Update §4.2 deterministic fallback config YAML:**

Replace:
```yaml
llm:
  model_escalation:
    deterministic_fallback_before_escalation: true
    deterministic_fallback_timeout_ms: 100
    deterministic_fallback_acceptance: require_all_fields
```

With:
```yaml
llm:
  model_escalation:
    deterministic_fallback_before_escalation: true
    deterministic_fallback_timeout_ms: 100        # node-configurable, tune per extraction complexity
    deterministic_fallback_acceptance: require_all_fields  # require_all_fields | partial_ok
    deterministic_fallback_quality:
      min_field_confidence: 0.5                    # minimum per-field regex/keyword match score to accept
      post_fallback_validate: true                 # always run schema validation on fallback output
      applicable_node_types: [extraction]          # only extraction nodes; decision/response are excluded
```

**2. Add after the current deterministic fallback paragraph in §4.2:**

```
**Fallback constraints:**
- Fallback ONLY applies to extraction nodes (L1). Decision nodes and response nodes skip fallback
  because regex/keyword cannot salvage reasoning or free-text generation quality.
- Fallback output MUST pass the same `output_schema` JSON validation as LLM output. If fallback
  produces invalid JSON or missing required fields, it fails and escalation proceeds.
- Fallback results are marked `source: "deterministic_fallback"` in the audit trail, with a
  `fallback_confidence` score per extracted field.
- The `min_field_confidence` gate rejects individual fields below the threshold;
  with `require_all_fields`, any rejected field causes fallback failure.
- The `deterministic_fallback_timeout_ms` is a configurable starting point; tune per-node
  based on extraction complexity. Default: 100ms for simple keyword extraction, 500ms for
  multi-field regex extraction.
```

**3. Update the escalation flow diagram in §4.2 to show post-fallback validation:**

Replace the fallback step:
```
        ├──→ Step: deterministic fallback (keyword/regex extraction)
        │         │
        │         ├── fallback SUCCESS ──→ return result (marked as "deterministic_fallback")
        │         └── fallback FAIL ──→ escalate to Tier 1
```

With:
```
        ├──→ Step: deterministic fallback (keyword/regex extraction)
        │         │
        │         ├── fallback produces candidate data
        │         │        │
        │         │        ├── schema validation PASS + min_field_confidence met
        │         │        │        └──→ return result (source: "deterministic_fallback", auditable)
        │         │        └── schema validation FAIL or below min_field_confidence
        │         │                 └──→ escalate to Tier 1
        │         │
        │         └── fallback extracts nothing ──→ escalate to Tier 1
```

---

## Ruling 3: `x-threshold` — Non-Standard JSON Schema Extension

**Agent 1 Proposal:** Replace `x-threshold` with standard JSON Schema `minimum` keyword, eliminating the custom extension.

### Verdict: **COMPROMISE** (strongly favoring Agent 1)

### Rationale

**Evidence Analysis:**
Agent 1's evidence is technically correct and decisive. The JSON Schema 2020-12 specification (§6.2.4) defines `minimum` as: "If the instance is a number, then this keyword validates only if the instance is greater than or exactly equal to 'minimum'." Setting `"confidence": {"type": "number", "minimum": 0.7}` would enforce confidence >= 0.7 identically to the current `x-threshold: 0.7` behavior. The Guardrails AI approach (separate validator config, not custom schema keywords) further supports using standard constructs.

The one legitimate distinction `x-threshold` provides — differentiating quality threshold violations from structural schema violations (enabling different `on_violation` policies) — can be achieved without a custom keyword. The gateway already has `confidence_threshold` config that identifies which fields are quality-sensitive by name matching. The enforcement can use standard `minimum` while the gateway's behavior differentiation is driven by field identity, not keyword type.

**Project Principles Alignment:**
The framework claims to use standard JSON Schema (§6). Introducing a custom extension keyword contradicts this principle and creates compatibility issues with standard validators, code generators, and downstream tooling. Using `minimum` as the enforcement mechanism aligns with VISION.md's preference for standard formats and interfaces.

**Change Safety:**
Replacing `x-threshold` with `minimum` is mechanically safe:
- Gateway already scans for `confidence_field_name` fields — same detection logic applies
- Gateway already has configurable `on_violation` for confidence thresholds — same policy engine applies
- The gateway differentiates `confidence_below_threshold` from `type_mismatch` by the field identity (`confidence` field name match), not by the keyword that triggered validation

### Implementation

In `docs/specs/2026-06-17-llm-gateway.md`:

**1. Rewrite §3.5 (Confidence Threshold Gate):**

Replace the entire §3.5 content with:

```
### 3.5 Confidence Threshold Gate

Schema validation checks structure — not correctness. The gateway supports an optional
**confidence threshold gate**: when the output schema declares a `confidence` field with
a `minimum` constraint > 0, the gateway treats violations of that constraint as quality
threshold violations (separate from structural schema violations).

```json
{
  "type": "object",
  "properties": {
    "intent": { "type": "string" },
    "confidence": {
      "type": "number",
      "minimum": 0.7,
      "maximum": 1,
      "description": "LLM self-assessed confidence score (0-1). Values below minimum trigger quality retry."
    }
  },
  "required": ["intent", "confidence"]
}
```

The standard `minimum` keyword enforces the threshold: the LLM must produce valid JSON with
`confidence >= 0.7`, or the gateway treats it as a `confidence_below_threshold` violation.
This prevents low-confidence guesses from being silently accepted.

```
Attempt 1 → {"intent": "get_quote", "confidence": 0.45}
           → schema valid, but confidence below minimum (0.45 < 0.7) → retry
Attempt 2 → {"intent": "get_quote", "confidence": 0.0}
           → schema valid, confidence below minimum (0.0 < 0.7) → retry
Attempt 3 → {"intent": "get_quote", "confidence": 0.92}
           → valid + threshold met → return
```

**How the gateway detects confidence-gated fields:**

The gateway scans `output_schema` for a property whose key matches `confidence_field_name`
(configurable, default: `confidence`), whose type is `number`, and whose `minimum` is > 0.
If found, violations of that field's `minimum` constraint are classified as
`confidence_below_threshold` and handled per the gateway's confidence threshold policy:

```yaml
llm:
  validation:
    confidence_threshold:
      enabled: true
      confidence_field_name: confidence  # field name to scan for
      on_violation: retry                # retry | warn_and_accept | strict_reject
```

The gateway differentiates `confidence_below_threshold` from standard `type_mismatch` errors
by the field's identity (matching `confidence_field_name`) rather than by any custom schema
keyword. This enables nuanced handling: confidence violations can use `warn_and_accept` while
structural violations always trigger retry.

When escalation is enabled (§4), confidence threshold violations count toward
`failures_before_escalation` when `on_violation` is `retry` or `strict_reject`. In
`warn_and_accept` mode, the call is treated as a success (returned with warning) and does
NOT count toward escalation.

A `minimum` value of 0 or a negative number effectively disables the gate: the constraint
is always satisfied since `confidence` is bounded to [0,1]. To explicitly disable the gate,
set `confidence_threshold.enabled: false`.
```

**2. Remove `x-threshold` from the §3.2 error injection format and §3.3 error categories table:**

In §3.3, the structured error format example currently shows:
```
- confidence_below_threshold: confidence (0.45, threshold: 0.7)
```

Keep this error format — it now refers to the `minimum` constraint on the confidence field, not to `x-threshold`.

In the error categories table (§3.3), the row:
```
| `confidence_below_threshold` | `field_name (value, threshold: N)` |
```

Keep unchanged — the threshold value `N` is now sourced from the schema's `minimum` keyword.

**3. Update the confidence_threshold config description (current §3.5 config block):**

Replace:
```yaml
      default_min: 0.7                   # fallback when schema omits x-threshold
```

With:
```yaml
      default_min: 0.7                   # fallback when schema's confidence field has no minimum
```

---

## Summary

| Conflict | Ruling | Key Change |
|----------|--------|------------|
| 1. Relax `output_schema` for Layer 3 | **COMPROMISE** | Keep mandatory; add minimal-schema guidance for Layer 3; clarify free-text quality is not validated |
| 2. Remove deterministic fallback | **COMPROMISE** | Keep fallback; add post-fallback schema validation, `min_field_confidence` gate, node-type restriction to extraction only |
| 3. Remove `x-threshold` | **COMPROMISE** | Replace `x-threshold` with standard `minimum`; gateway differentiates quality vs structural violations by field identity, not keyword |

All three rulings maintain alignment with VISION.md while incorporating Agent 1's valid concerns through targeted specification improvements. No feature is removed; all are strengthened with quality gates, standard formats, or clarified scope.
