# LLM Gateway — Mandatory Structured Output Interface

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: The single LLM entry point that enforces mandatory structured JSON output for every LLM interaction.
> **This is the enforcement mechanism for "All LLM output is JSON" (VISION.md §6.3).**

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial LLM Gateway spec |
| 2026-06-18 | 0.2.0 | Add §4 Progressive Model Escalation: small→medium→large model fallback chain after 2+ failures; 3 implementation options (Fixed Tiers, Provider-Cascade, Dynamic Routing); tier-aware retry budget; per-environment defaults |
| 2026-06-18 | 0.3.0 | Bugfixes: corrected §4.4 formula (removed erroneous +1, Σ only), fixed §4.5 audit trail (total_attempts 3→4), fixed §4.1 deepseek redundant tier. Optimizations: §4.2 deterministic fallback before escalation (keyword/regex salvage), §3.5 confidence threshold gate (x-threshold), §3.2 type coercion audit table with lossy/lossless classification, §3.3 structured error injection format, §4.9 sticky tier (escalation memory with TTL) |
| 2026-06-18 | 0.3.1 | Adversarial multi-agent review (ai-coworker-contrarian-review): fixed §3.3 retry budget formula mismatch with §4.4, fixed §4.2 escalation flow (Tier 1 now shows 2 failures per default config), fixed §8 total_attempts 6→5, added `coercions` field to LLMResult struct, added boolean string coercion rows, renamed duplicate "Implementation Options" headings (§4.6→Model Escalation Strategies, §5→Gateway Validation Strategies), added §3.6 Layer 3 Free-Text Handling with minimal schema guidance, replaced `x-threshold` custom keyword with standard `minimum` per JSON Schema spec, added deterministic fallback quality gates (post-fallback validation, min_field_confidence, node-type restriction to extraction), added circuit breaker for total provider outage, added max_tokens guard, clarified sticky tier TTL behavior, documented LLM +1 last-tier trade-off with `llm_extra_retry` config, added per-error-type retry policy, standardized model names with version suffixes |

---

## 1. Role

Every LLM call in the framework goes through **one gateway interface**. This gateway enforces three rules:

1. **`output_schema` is mandatory** — you cannot call the LLM without declaring what JSON shape you expect back
2. **The framework validates the response** against the schema before returning it
3. **If validation fails, the framework retries** (within retry budget) — the caller never sees a malformed response

This is NOT a "nice-to-have" or "per-task optional setting." It is a **hard constraint** enforced at the interface level.

```
Layer 1 (Extract)
Layer 2 (Decision)   ──→  [LLM Client Gateway]  ──→  LLM Provider (OpenAI / Anthropic / DeepSeek)
Layer 3 (Response)         ├─ schema enforcement
                           ├─ JSON validation
                           ├─ type coercion
                           └─ retry on violation
```

## 2. Interface Contract

### 2.1 Call Input

```
LLMCall {
  prompt:           string | Message[]    // system + user messages
  output_schema:    JSONSchema           // MANDATORY — what shape the response must have
  temperature:      float                // 0 for extraction/decision, 0.3 for response
  max_tokens?:      int
  provider?:        string               // "openai" | "anthropic" | "deepseek" | ...
  model?:           string               // "gpt-4o" | "claude-sonnet-4-20250514" | ...
  conversation_id?: string               // for tracing / audit
}
```

### 2.2 Call Output

```
LLMResult {
  data:       dict              // validated JSON matching output_schema (PII-scrubbed per Response Generation §8)
  raw:        string            // raw LLM response (audit trail only — access-controlled, see below)
  model:      string            // which model was used
  usage:      TokenUsage        // tokens in / out
  attempts:   int               // how many attempts (1 if first try passed)
  validated:  boolean           // always true — gateway guarantees this
  coercions?: CoercionRecord[]  // type coercion audit entries (see §3.2)
}
```

The `raw` field is exempt from PII scrubbing (it preserves the original response for debugging/audit). Access to `raw` is restricted to audit trails and debug endpoints with access control. See [Response Generation §8](./2026-06-17-response-generation-layer-design.md) for PII scrubbing on `data`.

### 2.3 TokenUsage

```
TokenUsage {
  prompt_tokens:      int
  completion_tokens:  int
  total_tokens:       int
}
```

## 3. Framework Guarantees

The gateway guarantees that **`LLMResult.data` is always valid JSON matching `output_schema`** — or the call fails entirely (errorNode). The caller never receives a partially valid or unvalidated response.

### 3.1 Validation Pipeline

```
LLM call
    │
    ├── success ──→ Step 1: Parse JSON
    │                   │
    │                   ├── valid JSON ──→ Step 2: Schema match
    │                   │                      │
    │                   │                      ├── matches schema ──→ Step 3: Confidence check
    │                   │                      │                          │
    │                   │                      │                          ├── ≥ threshold ──→ return LLMResult
    │                   │                      │                          └── < threshold ──→ retry (with confidence context)
    │                   │                      │
    │                   │                      └── mismatch ──→ retry (with error context)
    │                   │
    │                   └── not JSON ──→ retry (with "must output JSON" instruction)
    │
    └── provider error (timeout, 5xx) ──→ retry (within retry budget) → errorNode
```

### 3.2 Validation Checks

| Check | What | Failure Action |
|-------|------|---------------|
| **JSON parse** | Response is valid JSON | Retry with "Output must be valid JSON" |
| **Schema match** | All required fields present | Retry with missing field names |
| **Type coercion** | `"123"` → `123` if schema says `int` | Auto-coerce where safe; retry where ambiguous |
| **No extra fields** | No fields outside the schema | Strip extra fields (configurable: strip vs error) |

**Type coercion rules and audit:**

| Coercion | Safe? | Audit Level | Example |
|----------|-------|-------------|---------|
| `"123"` → `123` (str→int) | Yes | `debug` | Parseable integer |
| `"0.92"` → `0.92` (str→float) | Yes | `debug` | Parseable float |
| `123` → `"123"` (int→str) | Yes | `debug` | Lossless |
| `"yes"` → `true` (str→bool) | Yes | `debug` | Common boolean alias |
| `"true"` → `true` (str→bool) | Yes | `debug` | Standard boolean string |
| `"false"` → `false` (str→bool) | Yes | `debug` | Standard boolean string |
| `"2.5"` → `2` (str→int, truncation) | ⚠️ **Lossy** | `warning` | Precision lost — audit log records original + coerced |
| `"twenty"` → `int` (unparseable) | ❌ | N/A | Retry — cannot coerce |

All coercions are recorded in the `LLMResult` with original and coerced values for audit. Lossy coercions (e.g., string→int truncation) emit a `warning`-level audit entry and increment a `coercion_loss` counter visible to the errorNode.

```json
{
  "llm_call_id": "call_abc123",
  "coercions": [
    {
      "field": "building_age",
      "original": "2.5",
      "coerced": 2,
      "coercion_type": "str_to_int_truncated",
      "level": "warning"
    }
  ]
}
```

### 3.3 Retry on Violation

```
Retry budget per LLM call:
  base_max_attempts:  3              // when model escalation is disabled
  backoff:             exponential    // 500ms → 1s → 2s → 4s
  on_exhausted:        errorNode      // always errorNode

  // When model escalation is enabled (§4), the retry budget becomes per-tier:
  // each tier has its own failures_before_escalation (default 2)
  // total budget = Σ(tier.failures_before_escalation)   (see §4.4)
```

Per-error-type overrides allow different retry behavior based on the failure category. Non-retryable errors (auth failure, content policy violation) skip retries entirely and route directly to errorNode:

```yaml
retry_policy:
  default: { max_attempts: 3, backoff: exponential, base_delay_ms: 500 }
  overrides:
    AuthenticationError:         { max_attempts: 0 }              # 401 — never retry
    RateLimitError:              { max_attempts: 5, base_delay_ms: 2000 }
    ContentPolicyViolationError: { max_attempts: 1 }
    ContextWindowExceededError:  { max_attempts: 0 }              # prompt too large — retry won't help
```

| Error Type | Default Max Attempts | Rationale |
|------------|---------------------|-----------|
| Schema violation / JSON parse | 3 | LLM can self-correct |
| Timeout / 5xx | 3 | Transient, worth retrying |
| Rate limit (429) | 5 | Wait longer, retries often succeed |
| Auth failure (401/403) | 0 | Key is invalid — retry wastes budget |
| Content policy violation | 1 | One rephrase attempt, then errorNode |

Each retry injects the validation error into the prompt so the LLM can self-correct. The error is appended in a **structured format** to prevent the LLM from misinterpreting the correction instruction:

```
--- VALIDATION ERRORS (attempt 1) ---
- missing_required_field: "confidence"
- type_mismatch: "confidence" (expected: number, got: string "high")
- confidence_below_threshold: confidence (0.45, threshold: 0.7)

Please correct your response. Output ONLY valid JSON matching the required schema.
```

The structured format uses a separator block that is easy for LLMs to parse and distinguishes from the original prompt content. Each error entry follows a consistent `category: detail` pattern:

| Error Category | Template |
|---------------|----------|
| `missing_required_field` | `"field_name"` |
| `type_mismatch` | `"field_name" (expected: type, got: type "value")` |
| `confidence_below_threshold` | `field_name (value, threshold: N)` |
| `invalid_enum` | `"field_name": "value" not in [allowed_values]` |
| `not_valid_json` | `Response is not valid JSON. Ensure output is a JSON object.` |

```
Attempt 1 → LLM responds with {"intent": "get_quote"}    → missing "confidence" field
Attempt 2 → LLM responds with {"intent": "get_quote", "confidence": "high"}  → type error (string not number)
Attempt 3 → LLM responds with {"intent": "get_quote", "confidence": 0.92}    → valid, return
```

### 3.4 LLM +1 Extra Retry

Per VISION.md §6.3, LLM nodes receive +1 extra retry on top of the base retry budget:

```
max_attempts = node.retry_budget.max_attempts + 1                     // escalation disabled
per_tier_failures = tier.failures_before_escalation + 1               // escalation enabled
```

When escalation is enabled, LLM nodes get one extra attempt per tier before escalating. See §4.4 for tier-aware budget calculation.

### 3.5 Confidence Threshold Gate

Schema validation checks structure — not correctness. The gateway supports an optional **confidence threshold gate**: when the output schema declares a `confidence` field with a `minimum` constraint > 0, the gateway treats violations of that constraint as quality threshold violations (separate from structural schema violations).

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

The standard `minimum` keyword enforces the threshold: the LLM must produce valid JSON with `confidence >= 0.7`, or the gateway treats it as a `confidence_below_threshold` violation. This prevents low-confidence guesses from being silently accepted.

```
Attempt 1 → {"intent": "get_quote", "confidence": 0.45}
           → schema valid, but confidence below minimum (0.45 < 0.7) → retry
Attempt 2 → {"intent": "get_quote", "confidence": 0.0}
           → schema valid, confidence below minimum (0.0 < 0.7) → retry
Attempt 3 → {"intent": "get_quote", "confidence": 0.92}
           → valid + threshold met → return
```

This gate is configurable. The gateway detects the confidence-gated field by scanning the output_schema for a property whose key matches `confidence_field_name` (configurable, default: `confidence`), whose type is `number`, and whose `minimum` is > 0. If found, violations of that field's `minimum` constraint are classified as `confidence_below_threshold` and handled per the gateway's confidence threshold policy:

```yaml
llm:
  validation:
    confidence_threshold:
      enabled: true
      confidence_field_name: confidence  # field name to scan for
      default_min: 0.7                   # fallback when schema's confidence field has no minimum
      on_violation: retry                # retry | warn_and_accept | strict_reject
```

The gateway differentiates `confidence_below_threshold` from standard `type_mismatch` errors by the field's identity (matching `confidence_field_name`) rather than by any custom schema keyword. This enables nuanced handling: confidence violations can use `warn_and_accept` while structural violations always trigger retry.

When escalation is enabled (§4), confidence threshold violations count toward `failures_before_escalation` when `on_violation` is `retry` or `strict_reject`. In `warn_and_accept` mode, the call is treated as a success (returned with warning) and does NOT count toward escalation — since no retry was triggered.

A `minimum` value of 0 or a negative number effectively disables the gate: the constraint is always satisfied since `confidence` is bounded to [0,1]. To explicitly disable the gate, set `confidence_threshold.enabled: false`.

### 3.6 Layer 3 Free-Text Handling

Layer 3 (Response) is the only layer where free-text content is permitted (VISION.md §6.3). To avoid degrading output quality, Layer 3 `output_schema` definitions SHOULD use minimal schemas that wrap free text in a thin JSON envelope:

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

The gateway validates that the JSON structure matches; it does NOT validate the *content quality* of the `text` field — only that it is a valid string. This ensures every LLM output is structured and auditable while preserving free-text generation quality.

Layer 3 nodes operate with `temperature: 0.3` (per VISION.md §6.3) and may use `on_violation: warn_and_accept` for their `output_schema` to avoid retry loops on free-text fields where schema shape is not critical.

### 3.7 LLM Call Caching

Identical LLM calls (same prompt + output_schema + model + temperature) can be cached to reduce cost and latency. Caching is per-environment:

| Environment | Cache Backend | TTL | Purpose |
|-------------|--------------|-----|---------|
| dev | In-memory dict | Session | Fast iteration without API cost |
| e2e | In-memory or local Redis | Test run | Deterministic eval results |
| prod | Redis (distributed) | Configurable | Reduce cost on repeated calls |

Cache key: `hash(prompt + output_schema + model + temperature)`. Cache hits are recorded in the audit trail as `cache_hit: true` with zero token usage.

```yaml
llm:
  caching:
    enabled: true
    backend: redis              # memory | redis
    ttl_seconds: 3600           # 1 hour default
    per_node_override: true     # allow nodes to disable caching
```

Interaction with model escalation: a cache hit on Tier 0 returns immediately — no escalation needed. If Tier 0 cache misses and the call fails, Tiers 1+ can benefit from prompt caching (Anthropic/OpenAI server-side) for the system prompt prefix.

## 4. Progressive Model Escalation

The gateway supports **automatic model escalation**: when an LLM call fails repeatedly, the framework upgrades to a more capable (and more expensive) model as a safety net. The framework's default is always the cheapest viable model — escalation is a fallback, not a feature.

**Cost guard:** The framework's design philosophy is to optimize for small, inexpensive models. Tier 0 (small model) should handle the vast majority of calls. Escalation to larger models is reserved for edge cases where the small model consistently fails. This keeps per-call costs predictable and bounded.

### 4.1 Model Tiers

Model tiers are defined as an ordered chain from cheapest to most capable:

```
Tier 0 (small)   →  Tier 1 (medium)  →  Tier 2 (large)

e.g.:
  gpt-4o-mini           →  gpt-4o                →  gpt-4.1
  claude-haiku-3-5      →  claude-sonnet-4-20250514 →  claude-opus-4-20250514
  deepseek-chat         →  deepseek-v3           →  deepseek-reasoner
```

Each tier specifies:

| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | Provider name (openai, anthropic, deepseek) |
| `model` | string | Model identifier |
| `temperature` | float | Override temperature per tier (optional) |
| `max_tokens` | int | Override max_tokens per tier (optional) |
| `failures_before_escalation` | int | Number of consecutive failures on this tier before moving to the next (default: 2) |

### 4.2 Escalation Flow

```
Attempt 1 ──→ Tier 0 (small model: gpt-4o-mini) ──→ FAIL (schema violation)
Attempt 2 ──→ Tier 0 (small model: gpt-4o-mini) ──→ FAIL (provider timeout)
       │
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
       │
Attempt 3 ──→ Tier 1 (medium model: gpt-4o) ──→ FAIL (schema violation)
Attempt 4 ──→ Tier 1 (medium model: gpt-4o) ──→ FAIL (type mismatch)
       │
       ├──→ Step: deterministic fallback (same constraints as above)
       │         └── fallback FAIL ──→ escalate to Tier 2
       │
Attempt 5 ──→ Tier 2 (large model: gpt-4.1) ──→ SUCCESS ✅
```

At each tier, the gateway retries up to `failures_before_escalation` times (default: 2). After 2 failures on the current tier, the gateway attempts **deterministic fallback** before escalating to the next tier. When all tiers are exhausted, the gateway routes to `errorNode`.

**Circuit breaker:** If ALL tiers across ALL providers are exhausted via `provider_error` (timeout, 5xx) — indicating a total provider outage — the gateway enters circuit-open state for `circuit_breaker_ttl_seconds` (default: 30). During this window, all LLM calls immediately route to `errorNode` with `escalate_to_human` strategy, avoiding wasted timeouts on known-unavailable providers.

**Prompt strategy on escalation:** Each tier escalation chooses how to present the prompt context to the next tier's LLM:

| Strategy | Behavior | Cost |
|----------|----------|------|
| `carry_forward` | Append all error injections to the previous prompt | Highest token accumulation |
| `reset` | Fresh prompt per tier, no error history | Lowest tokens, no correction context |
| `summarize` (default) | Inject a one-line failure summary: "Previous tier failed after 2 attempts (missing field 'confidence'). Ensure all required fields are present." | Minimal token overhead, retains correction context |

```yaml
llm:
  model_escalation:
    prompt_strategy: summarize          # carry_forward | reset | summarize
    max_prompt_length: 8192             # force reset if accumulated prompt exceeds this
```

`summarize` is the default — it gives the next tier enough context to avoid repeating the same mistake without ballooning token costs.

Deterministic fallback is tier-level (once per tier, after LLM retries exhausted) and can be disabled per-node. Fallback applies to extraction nodes (keyword/regex) and decision nodes (enum-value substring matching); for response nodes it is typically disabled since free-text cannot be salvaged deterministically.

```yaml
llm:
  model_escalation:
    deterministic_fallback_before_escalation: true
    deterministic_fallback_timeout_ms: 100        # tune per-node based on extraction complexity
    deterministic_fallback_acceptance: require_all_fields
    deterministic_fallback_quality:
      min_field_confidence: 0.5                   # minimum per-field regex/keyword match score
      post_fallback_validate: true                # run schema validation on fallback output
      applicable_node_types: [extraction]         # extraction nodes only; decision/response excluded
```

**Fallback constraints:**
- Fallback ONLY applies to extraction nodes (L1). Decision nodes and response nodes skip fallback because regex/keyword cannot salvage reasoning or free-text generation quality.
- Fallback output MUST pass the same `output_schema` JSON validation as LLM output. If fallback produces invalid JSON or missing required fields, it fails and escalation proceeds.
- Fallback results are marked `source: "deterministic_fallback"` in the audit trail, with a `fallback_confidence` score per extracted field.
- The `min_field_confidence` gate rejects individual fields below the threshold; with `require_all_fields`, any rejected field causes fallback failure.
- The `deterministic_fallback_timeout_ms` is configurable; tune per-node based on extraction complexity (default: 100ms for simple keyword, 500ms for multi-field regex).

**max_tokens guard:** If `max_tokens` is too small for the `output_schema`, every LLM call will produce truncated (invalid) JSON. The gateway performs a pre-call estimate: if `max_tokens < estimated_schema_tokens`, a warning is emitted and the call may bypass retries entirely (fail fast to errorNode) since retrying with the same `max_tokens` is guaranteed to fail. The per-tier `max_tokens` override (§4.1) can be used to increase the limit on higher tiers.

### 4.3 Escalation Triggers

Escalation counts **all failure types** by default. Which failures trigger escalation is configurable:

| Trigger | Default | Description |
|---------|---------|-------------|
| `provider_error` | enabled | Timeout, 5xx, rate limit, auth failure |
| `schema_violation` | enabled | JSON parse failure, missing fields, type mismatch |
| `content_quality` | disabled | Empty response, too-short output, off-topic (optional) |

```yaml
# Per-node or global configuration
llm:
  model_escalation:
    enabled: true                   # default: true in prod, false in dev
    failures_before_escalation: 2   # escalate after 2 failures on current tier
    trigger_on:
      - provider_error
      - schema_violation
    tiers:
      - provider: openai
        model: gpt-4o-mini
        temperature: 0
        max_tokens: 4096
        failures_before_escalation: 2
      - provider: openai
        model: gpt-4o
        temperature: 0
        max_tokens: 4096
        failures_before_escalation: 2
      - provider: openai
        model: gpt-4.1
        temperature: 0
        max_tokens: 16384
        failures_before_escalation: 1    # last tier: fail fast to errorNode
```

### 4.4 Tier-Aware Retry Budget

The total retry budget is the sum of per-tier allowances. Since escalation happens when the current tier exhausts its `failures_before_escalation` attempts, the maximum number of LLM calls across all tiers is:

```
max_total_calls = Σ(tier.failures_before_escalation)
                = 2 + 2 + 1 = 5
```

If any call succeeds, the chain stops early. The formula only represents the worst case (all failures, all tiers exhausted).

The LLM +1 extra retry (VISION.md §6.3) applies per-tier:

```
per_tier_failures = tier.failures_before_escalation + 1   // LLM nodes

Example with 3 tiers [2, 2, 1]:
  Non-LLM max calls: 2 + 2 + 1 = 5
  LLM max calls:     (2+1) + (2+1) + (1+1) = 3 + 3 + 2 = 8
```

Note: LLM +1 applies to all tiers including the last, meaning the most expensive model may be called twice before errorNode. The `failures_before_escalation: 1` on the last tier is a non-LLM default; for LLM nodes the effective limit is 2. To enforce a hard single-attempt cap on the last tier regardless of node type, set `llm_extra_retry: false` on the last tier:

```yaml
tiers:
  - model: gpt-4o-mini
    failures_before_escalation: 2
  - model: gpt-4o
    failures_before_escalation: 2
  - model: gpt-4.1
    failures_before_escalation: 1
    llm_extra_retry: false       # no +1 on the most expensive tier
```

### 4.5 Audit Trail

Each escalation is recorded in the audit log. Example (Tier 0 exhausted, Tier 1 succeeds on second attempt — only one escalation):

```json
{
  "llm_call_id": "call_abc123",
  "escalations": [
    {
      "from_tier": { "provider": "openai", "model": "gpt-4o-mini" },
      "to_tier":   { "provider": "openai", "model": "gpt-4o" },
      "reason": "schema_violation",
      "failed_attempts_on_tier": 2,
      "errors": [
        "missing field 'confidence'",
        "type mismatch: 'confidence' expected number, got string"
      ]
    }
  ],
  "final_tier_used": { "provider": "openai", "model": "gpt-4o" },
  "total_attempts": 4,
  "cost": {
    "tier_0_tokens": { "prompt": 1200, "completion": 200 },
    "tier_0_attempts": 2,
    "tier_1_tokens": { "prompt": 800, "completion": 150 },
    "tier_1_attempts": 2,
    "total_tokens": { "prompt": 2000, "completion": 350 }
  }
}
```

The errorNode audit (§8) extends this structure. This section covers escalation-specific fields; §8 adds error classification, coercion details, and raw response capture.

### 4.6 Model Escalation Strategies

#### Option A: Fixed Tiers (Default)

Pre-configured tier chains per provider. Simplest configuration; tiers are defined once in environment config.

```yaml
# .env.prod
LLM_MODEL_TIERS=openai:gpt-4o-mini→gpt-4o→gpt-4.1;anthropic:claude-haiku→claude-sonnet→claude-opus
```

| Strengths | Predictable costs, simple config, easy to audit |
|-----------|------------------------------------------------|
| Weaknesses | No cross-provider fallback, tiers are static |
| Best for | Single-provider deployments, cost-predictable environments |

#### Option B: Provider-Cascade

Escalate across providers, not just within one provider. After OpenAI tiers are exhausted, switch to Anthropic.

```yaml
llm:
  model_escalation:
    strategy: provider_cascade
    tiers:
      - provider: openai
        model: gpt-4o-mini
        failures_before_escalation: 2
      - provider: openai
        model: gpt-4o
        failures_before_escalation: 2
      - provider: anthropic
        model: claude-sonnet-4-20250514
        failures_before_escalation: 2
      - provider: anthropic
        model: claude-opus-4-20250514
        failures_before_escalation: 1
```

| Strengths | Higher resilience (provider outage handled), best-in-class per tier |
|-----------|---------------------------------------------------------------------|
| Weaknesses | Multi-provider API key management, different cost structures |
| Best for | Production with strict SLA, multi-cloud deployments |

### 4.7 Comparison Matrix

| Dimension | Option A (Fixed Tiers) | Option B (Provider-Cascade) |
|-----------|----------------------|---------------------------|
| Config complexity | Low | Medium |
| Provider redundancy | None | Full (multi-provider) |
| Cost predictability | High | Medium |
| Latency overhead | None | None |
| Audit simplicity | High | Medium |
| SLA resilience | Medium (single provider) | High |
| Implementation effort | Low | Medium |

### 4.8 Environment-Specific Defaults

| Environment | Escalation Enabled | Default Tier Chain |
|-------------|-------------------|-------------------|
| dev | false (use single cheap model, fail fast) | gpt-4o-mini only |
| e2e | true (test escalation behavior) | gpt-4o-mini → gpt-4o |
| prod | true | gpt-4o-mini → gpt-4o → gpt-4.1 |

### 4.9 Sticky Tier (Escalation Memory)

By default, each LLM call starts fresh from Tier 0. This can lead to **repeated escalation cost**: if a node consistently fails on the small model, every call wastes 2 attempts on Tier 0 before reaching the capable Tier 1.

**Sticky tier** remembers which model worked last time for a given `(node_id, intent)` pair and starts the next call from that tier, skipping known-to-fail lower tiers.

```
Call 1: Tier 0 (fail) → Tier 0 (fail) → Tier 1 (SUCCESS) → sticky: Tier 1
Call 2: Tier 1 (start directly, skip Tier 0) → SUCCESS ✅
Call 3: Tier 1 (start directly) → FAIL → FAIL → Tier 2 (SUCCESS) → sticky: Tier 2
```

The sticky tier decays over time to avoid permanently using expensive models:

```yaml
llm:
  model_escalation:
    sticky_tier:
      enabled: true
      ttl_seconds: 300                 # reset to Tier 0 after 5 min idle
      max_sticky_tier: 1               # never stick above medium (cost guard)
                                       # Note: if only Tier 2 consistently succeeds for a given
                                       # intent, this guard causes repeated escalation overhead.
                                       # Tune based on per-intent escalation rate monitoring.
      scope: node_id_and_intent        # per-node + per-intent memory
```

When the TTL expires, the next call starts from Tier 0 again — allowing the framework to retest whether the small model has become sufficient (e.g., user input got simpler). TTL is checked once per LLM call, at call initiation. If the sticky tier is valid at call start, it is held for the entire call (including all escalation tiers within that call). Expiry only affects subsequent calls.

```json
// audit log: skip escalation
{
  "llm_call_id": "call_def456",
  "sticky_tier_used": { "provider": "openai", "model": "gpt-4o" },
  "tiers_skipped": 1,
  "sticky_ttl_remaining_seconds": 212
}
```

### 4.10 Pre-Call Checks

Before issuing any LLM call, the gateway runs pre-call checks to avoid calls that are guaranteed to fail. This reduces unnecessary retries and escalation.

| Check | What | Failure Action |
|-------|------|---------------|
| **Context window** | `estimated_prompt_tokens + max_tokens ≤ model.context_window` | Skip this tier, escalate immediately |
| **Rate limit** | Per-provider RPM/TPM quota remaining ≥ 1 | Skip this provider, try next tier provider |
| **Deployment health** | Model deployment not in cooldown (N failures/minute exceeded) | Skip this deployment, try next tier |
| **Region filter** | Model deployment in allowed region (GDPR/data residency) | Skip this deployment |
| **Auth validity** | API key valid and not expired | Skip this provider, escalate to errorNode |

Pre-call checks run before each tier attempt and are complementary to the reactive escalation flow (§4.2). A tier skipped by pre-call checks counts as a tier exhaustion (no attempt wasted).

```yaml
llm:
  pre_call_checks:
    enabled: true
    context_window_margin: 200            # reserve tokens for response variance
    rate_limit_buffer: 10                 # stop calling when quota < 10 requests
    cooldown_threshold: 5                 # after 5 failures/minute → cooldown 60s
    cooldown_duration_seconds: 60
    region_filter: [us-east, eu-west]     # optional, empty = no filter
```

**Circuit breaker integration:** Pre-call checks also enforce the circuit-open state (§4.2). If all providers are in cooldown or circuit-open, every LLM call routes directly to `errorNode` without any attempt.

## 5. Gateway Validation Strategies

### Option A: Provider-Native Structured Output

Pass `output_schema` as `response_format` to LLM providers that support native structured output (OpenAI JSON mode, Anthropic tool use with strict mode). The LLM itself enforces the schema.

| Strengths | Provider guarantees schema at generation time; fewer retries |
|-----------|--------------------------------------------------------------|
| Weaknesses | Only some providers support it; schema complexity limits vary |
| Best for | Production, when using OpenAI / Anthropic |

### Option B: Post-Process Validation (Provider-Agnostic)

Always call LLM without `response_format`. Parse and validate the response in the gateway after receiving it. Works with any LLM provider.

| Strengths | Works with any provider; no schema complexity limits |
|-----------|----------------------------------------------------|
| Weaknesses | More retries; LLM may produce incorrect shape frequently |
| Best for | Local models, Ollama, providers without structured output support |

### Option C: Hybrid (Default Recommendation)

Try Option A first. If the provider supports `response_format`, use it. If not, fall back to Option B. If the provider supports `response_format` but the LLM call fails schema check (rare), retry with enriched error context.

```yaml
llm:
  gateway_strategy: hybrid        # hybrid | native_only | post_process_only
  native_providers:               # which providers support response_format
    - openai
    - anthropic
  fallback_providers:             # post-process only
    - ollama
    - deepseek
```

### Option D: Validator-Enhanced Post-Process

Post-process validation + field-level content quality checks (Instructor + Guardrails pattern). Beyond JSON schema validation, each field can carry content rules: regex patterns, length bounds, semantic checks, email/phone format.

```
Schema: { email: string, phone: string, building_age: integer }
LLM output: { "email": "call me", "phone": "N/A", "building_age": 999 }

→ JSON parse ✓, schema match ✓, type coercion ✓
→ email: pattern /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/ → FAIL ("call me" is not an email)
→ phone: min_length=10 → FAIL ("N/A" is 3 chars)
→ building_age: 0 <= 999 <= 200 → FAIL (out of range)

→ Retry with validation context injected per field
→ Reask: "email must be valid email address; phone must be at least 10 digits; building_age must be 0-200 years"
```

Content validators:

| Validator | What | Example |
|-----------|------|---------|
| `pattern` | Regex match | email, phone, postal code format |
| `min_length` / `max_length` | String length bounds | name ≥ 2 chars, phone ≥ 10 digits |
| `ge` / `le` | Numeric range | `0 <= age <= 200` |
| `ValidChoices` | Value in allowed set | `coverage_type in [basic, standard, premium]` |
| `TwoWords` | At least 2 words | Free-text response must contain substantive content |
| `MinLength` | Min char count | Response text ≥ 50 chars |

| Strengths | Catches "correct shape, wrong content" failures; field-level reask context improves correction rate |
|-----------|-------------------------------------------------------------------------------------------|
| Weaknesses | More complex schema authoring; content validators are hand-authored, not auto-generated |
| Best for | Production extraction nodes where correctness matters more than latency |

### 5.4 Comparison Matrix

| Dimension | Option A (Native) | Option B (Post-Process) | Option C (Hybrid) | Option D (Validator-Enhanced) |
|-----------|-------------------|------------------------|-------------------|------------------------------|
| Provider support | Limited (OpenAI, Anthropic) | Any provider | Any, with optimization | Any provider |
| Retry frequency | Low | Medium-High | Low | Medium |
| Schema complexity limit | Provider-dependent | Unlimited | Best available | Unlimited |
| Content validation | Type only | Type only | Type only | Type + semantic + format |
| Latency | 1 call typically | 1-4 calls | 1 call typically | 1-3 calls |
| Implementation | Provider SDK | JSON Schema validation | Both | Pydantic + validators |

## 6. Schema Definition

### 6.1 JSONSchema Format

The gateway accepts standard JSON Schema:

```json
{
  "type": "object",
  "properties": {
    "intent": {
      "type": "string",
      "description": "The classified intent label"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Confidence score"
    },
    "reasoning": {
      "type": "string",
      "description": "LLM's reasoning for the classification"
    }
  },
  "required": ["intent", "confidence"]
}
```

### 6.2 YAML Schema Declaration

For workflow authors, the schema is declared in YAML and auto-converted to JSON Schema:

```yaml
# In workflow node or domain model
output_schema:
  intent:
    type: string
    description: "The classified intent label"
    required: true
  confidence:
    type: number
    range: { min: 0, max: 1 }
    required: true
  reasoning:
    type: string
    required: false
```

### 6.3 Python-Native Schema (Pydantic)

For Python developers, schemas can also be defined as Pydantic `BaseModel` classes — the approach used by Instructor and LangChain. The gateway auto-converts Pydantic models to JSON Schema internally.

```python
from pydantic import BaseModel, Field

class IntentResult(BaseModel):
    intent: str = Field(description="The classified intent label")
    confidence: float = Field(ge=0, le=1, description="Confidence score (0-1)")
    reasoning: str | None = Field(default=None, description="LLM reasoning")

# Usage: gateway.call(prompt="...", output_schema=IntentResult)
```

Pydantic models offer Python-level type checking, built-in validators (`Field(ge=0, le=1)`), and IDE autocompletion — advantages over raw JSON Schema for code-first workflows. The gateway treats a Pydantic model identically to a JSON Schema dict: same validation pipeline, same retry/enforcement, same audit trail.

| Format | Best For |
|--------|----------|
| JSON Schema (§6.1) | Language-agnostic config, OpenAPI integration |
| YAML (§6.2) | Workflow authors, declarative config |
| Pydantic (§6.3) | Python developers, code-first workflows, IDE support |

### 6.4 Schema Preprocessing ($ref/$defs Resolution)

LLM providers have different JSON Schema support. OpenAI Structured Outputs does not support `$ref` or `$defs` — all references must be inlined. Anthropic similarly requires flat schemas. The gateway preprocesses schemas before sending to the provider:

1. **Dereference**: Resolve all `$ref` pointers, inline `$defs` entries recursively
2. **Depth check**: Validate nesting depth ≤ provider limit (OpenAI: 5, Anthropic: varies)
3. **Property count**: Count total properties ≤ provider limit (OpenAI: 100)
4. **Strip unsupported**: Remove `$comment`, `examples`, `default` (OpenAI), `oneOf`/`anyOf` (Anthropic limited support)

```yaml
llm:
  schema_preprocessing:
    auto_dereference: true
    max_nesting_depth: 5
    max_total_properties: 100
    on_exceed_limit: warn_and_flatten    # warn_and_flatten | error
```

If a schema exceeds provider limits after preprocessing, the gateway emits a warning and either flattens further (e.g., splitting nested objects) or rejects the call with a clear error message — no silent truncation.

## 7. Usage in Each Layer

### 7.1 Layer 1 — Extraction

```yaml
extraction_nodes:
  collect_property_info_extract:
    executor: llm
    output_schema:          # MANDATORY — gateway enforces
      property_type:
        type: string
        required: true
      address:
        type: string
        required: true
      building_age:
        type: number
        required: true
      floor_area:
        type: number
        required: false
```

### 7.2 Layer 2 — Decision

```yaml
decision_nodes:
  risk_triage:
    executor: llm
    output_schema:          # MANDATORY
      route:
        type: string
        enum: [auto_approve, standard_review, manual_review]
        required: true
      reason:
        type: string
        required: true
```

### 7.3 Layer 3 — Response

The gateway still requires `output_schema` for Layer 3 nodes, but the schema SHOULD be minimal — typically a `text: string` envelope plus optional structured metadata (see §3.6). The gateway validates that the JSON structure matches; it does NOT validate the quality of the free-text content within. This preserves the compliance guarantee (all LLM output is structured and auditable) without constraining generation quality.

```yaml
response_nodes:
  goal_setter:
    executor: llm
    output_schema:          # MANDATORY
      summary:
        type: string
        required: true
      intent:
        type: string
        required: true
      success_criteria:
        type: array
        items: { type: string }
        required: true

  goal_checker:
    executor: llm
    output_schema:          # MANDATORY
      goal_met:
        type: boolean
        required: true
      completion_percentage:
        type: number
        range: { min: 0, max: 1 }
        required: true
      gap_analysis:
        type: string
        required: true

  generate_response:
    executor: llm
    output_schema:          # MANDATORY — even for free-text generation
      text:
        type: string
        required: true
      components:
        type: array
        items: { type: object }
        required: false
```

## 8. Integration with errorNode

When the gateway exhausts all tiers and retry attempts and still has an invalid response, it routes to `errorNode`. For the canonical errorNode strategies, see [Routing & Execution §6.5](./2026-06-17-routing-execution-layer-design.md).

```
LLM Client Gateway (all tiers exhausted)
    │
    ▼
errorNode ──→ strategy: retry_with_context | escalate_to_human | terminate
    │
    ▼
  audit log: {
    schema_violation: true,
    total_attempts: 5,            // Σ(tier.failures_before_escalation) = 2+2+1 = 5 for non-LLM
    tiers_exhausted: 3,
    last_tier: { "provider": "openai", "model": "gpt-4.1" },
    last_error: "missing field 'intent'",
    error_category: "SCHEMA_MISMATCH",
    cost: {
      "tier_0_tokens": { "prompt": 1800, "completion": 300 },
      "tier_0_attempts": 2,
      "tier_1_tokens": { "prompt": 1200, "completion": 250 },
      "tier_1_attempts": 2,
      "tier_2_tokens": { "prompt": 900, "completion": 0 },
      "tier_2_attempts": 1,
      "total_tokens": { "prompt": 3900, "completion": 550 }
    },
    coercions: [],
    confidence_threshold: { "enabled": false },
    raw_response_snippet: "{\"intent\": ... (truncated)"
  }
```

The gateway records every failed attempt, including the schema violation details, in the audit trail.

**Error classification:** The `error_category` field uses a structured enum for downstream error handling:

```
error_category: JSON_PARSE_ERROR | SCHEMA_MISMATCH | TYPE_COERCION_FAILURE | 
                CONFIDENCE_BELOW_THRESHOLD | PROVIDER_TIMEOUT | PROVIDER_5XX |
                RATE_LIMITED | AUTH_FAILURE | CONTENT_POLICY_VIOLATION |
                CIRCUIT_OPEN | DETERMINISTIC_FALLBACK_FAILED
```

## 9. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should the gateway support streaming (incremental schema validation as tokens arrive) or only full-response validation? | Latency for long responses |
| 2 | Resolved — see §3.7. | Cost, determinism in dev |
| 3 | Resolved — see §6.4. | Schema complexity support |
| 4 | Should the gateway emit detailed schema violation traces to LangSmith/LangFuse for prompt improvement? | Debugability |
| 5 | Resolved — see §4.2 prompt strategies. | Prompt token accumulation, cost |
| 6 | Should escalation be configurable per-node (e.g., risk assessment escalates faster than data extraction)? | Granularity vs configuration complexity |
| 7 | How should cross-provider escalation handle provider-specific system prompts and schema directives (e.g., OpenAI `response_format` vs Anthropic tool use)? | Provider-compatibility overhead |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — §4.3 "LLM Output is JSON — Always", §4.1 framework principles
- [Extraction Layer](./2026-06-17-extraction-layer-design.md) — Extract/Validate/Transform pipeline, LLM usage
- [Routing & Execution](./2026-06-17-routing-execution-layer-design.md) — Decision nodes, errorNode, retry budgets
- [Response Generation](./2026-06-17-response-generation-layer-design.md) — Goal setter, goal checker, response generator
- [VISION.md](../VISION.md) — §6.3 LLM Rules, §6.5 Error Handling
