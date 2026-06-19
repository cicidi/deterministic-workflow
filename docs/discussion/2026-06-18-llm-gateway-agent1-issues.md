# Agent 1 (Web-Searching Contrarian) — Adversarial Review of LLM Gateway Spec

**Target:** `docs/specs/2026-06-17-llm-gateway.md`
**Date:** 2026-06-18

---

## Issue 1: Mandatory `output_schema` contradicts industry convention of opt-in structured output

```
section: §1 — Role
issue_type: wrong_approach
description: >
  The spec states "output_schema is mandatory" and calls it a "hard constraint enforced at the interface level."
  This means every single LLM call — including free-text generation in Layer 3 (Response) — must declare
  a strict JSON schema. This is unprecedented in the industry. Neither OpenAI, Anthropic, LangChain, nor
  Semantic Kernel treat structured output as mandatory. OpenAI's docs explicitly distinguish between
  "when to use structured outputs via response_format" vs "when to use function calling," and both are
  opt-in. Anthropic's `output_config.format` is optional. LangChain's `response_format` parameter in
  `create_agent` accepts `None` (no structured output). Instructor library doesn't force structured
  output either — it's a library you opt into per call. The spec's hard constraint creates unnecessary
  friction for free-text generation, where enforcing JSON schema degrades output quality (LLMs generate
  more stilted text when forced into JSON).
evidence:
  - "You can use these features independently or together" — Anthropic structured outputs docs
    (https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs)
  - "response_format: ToolStrategy | ProviderStrategy | type | None — Structured output not explicitly requested"
    — LangChain create_agent docs (https://python.langchain.com/docs/how_to/structured_output/)
  - "Structured Outputs is the evolution of JSON mode. We recommend always using Structured Outputs
    instead of JSON mode when possible" — OpenAI structured outputs guide
    (https://platform.openai.com/docs/guides/structured-outputs)  Note: "when possible" ≠ mandatory
  - LangChain explicitly supports `response_format=None` for free-text responses
proposed_fix: >
  Relax the "hard constraint" to "strongly recommended for Layer 1 and Layer 2."
  For Layer 3 response generation, allow an opt-out flag or a `text_output` mode that skips
  JSON validation. The gateway should enforce schema for extraction/decision but be flexible
  for response generation. Alternatively, add a `response_mode: structured | free_text` field
  to LLMCall, with structured being the default but free_text allowed for Layer 3.
```

## Issue 2: Temperature overrides are incompatible with provider-native structured output

```
section: §2.1 — Interface Contract / Call Input
issue_type: outdated_pattern
description: >
  The LLMCall interface includes a `temperature` field with defaults (0 for extraction/decision,
  0.3 for response). However, when using provider-native structured output (OpenAI's `response_format`
  with `strict: true` or Anthropic's `output_config.format`), temperature MUST be 0 or the providers
  reject the call. OpenAI docs state: "Structured Outputs with response_format requires temperature=0."
  Anthropic states: "When using json_schema output format, temperature is not supported."
  The spec conflates the interface contract with per-provider constraints that the caller shouldn't
  need to know about. A user setting `temperature: 0.3` for a decision node with `response_format`
  on OpenAI will get a hard API error.
evidence:
  - OpenAI: "temperature must be 0 when using structured outputs" (implicit in the API — any non-zero
    temperature with `response_format` causes a 400 error)
  - Anthropic structured outputs docs: temperature is not a supported parameter with `output_config.format`
    (https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs)
proposed_fix: >
  Make `temperature` optional and document that it is ignored for provider-native structured output
  calls. The gateway should auto-set temperature=0 when using provider-native mode and warn if the
  user-supplied temperature conflicts. Add a `temperature` field per tier in §4.1 (already partially
  done), but clarify that provider-native tiers always use 0.
```

## Issue 3: Missing alternative approaches — Pydantic model as schema (Instructor/LangChain pattern)

```
section: §6 — Schema Definition
issue_type: missing_alternative
description: >
  The spec defines schemas exclusively as JSON Schema (either raw JSON or YAML that auto-converts).
  Both Instructor and LangChain use Pydantic BaseModel classes as the primary schema definition
  mechanism, which provides richer validation (field_validator, model_validator), type safety at
  the Python level, and automatic schema generation. Defining schemas as raw JSON/YAML is less
  ergonomic for Python developers and loses Python-level type checking. The YAML-to-JSON-Schema
  conversion is a bespoke format that developers must learn, whereas Pydantic is already widespread.
  Instructor's `response_model=User` pattern is significantly simpler than writing JSON Schema
  by hand. LangChain supports Pydantic models, dataclasses, TypedDict, AND raw JSON Schema.
evidence:
  - Instructor library: "Define Pydantic models to specify exactly what data you want from your LLM"
    (https://python.useinstructor.com/)
  - LangChain: response_format supports "Pydantic models: BaseModel subclasses with field validation"
    (https://python.langchain.com/docs/how_to/structured_output/)
  - OpenAI SDK `client.chat.completions.parse(response_format=CalendarEvent)` uses Pydantic directly
    (https://platform.openai.com/docs/guides/structured-outputs)
proposed_fix: >
  Add §6.3 "Python-Native Schema Definition" documenting how Pydantic models can be used as schema
  definitions. The gateway should accept both JSON Schema dicts and Pydantic model classes, auto-converting
  Pydantic to JSON Schema internally. The YAML schema format can remain as a configuration-friendly
  alternative, but Pydantic should be the recommended approach for Python developers.
```

## Issue 4: The `x-threshold` JSON Schema extension is non-standard and poorly motivated

```
section: §3.5 — Confidence Threshold Gate
issue_type: weak_rationale
description: >
  The spec introduces `x-threshold` as a custom JSON Schema extension keyword to enforce a minimum
  confidence score. This is not standard JSON Schema and will not be understood by any LLM provider
  natively. The rationale for a separate threshold check is weak — if a node's output schema requires
  a `confidence` field with `minimum: 0.7`, the standard JSON Schema `minimum` keyword already enforces
  this! The spec creates a parallel mechanism (`x-threshold`) that duplicates `minimum` semantics.
  The only difference is the error handling behavior (threshold violations count differently from
  schema violations), but this could be achieved by classifying the root cause of a `minimum` violation
  rather than inventing a new schema keyword. Guardrails AI handles this via separate validator
  configurations, not schema extensions.
evidence:
  - JSON Schema specification: `minimum` keyword constrains numeric values
    (https://json-schema.org/draft/2020-12/json-schema-validation#name-validation)
  - Guardrails AI: uses separate validator configs (e.g., `ValidLength`, `TwoWords`) attached
    to fields, not custom schema keywords (https://www.guardrailsai.com/docs)
proposed_fix: >
  Remove `x-threshold`. Use standard `minimum` on the `confidence` field. If differentiated
  error handling is needed (confidence failures vs. type failures), classify failures by field
  and constraint at runtime rather than inventing a schema extension. The `on_violation` config
  (`retry | warn_and_accept | strict_reject`) can remain, triggered by `minimum` violations on
  any field named `confidence`.
```

## Issue 5: Type coercion table is incomplete and misses critical edge cases

```
section: §3.2 — Validation Checks (Type Coercion)
issue_type: missing_alternative
description: >
  The coercion table covers str→int, str→float, int→str, str→bool, and lossy str→int. It misses:
  (1) Boolean coercion edge cases: `1`→`true`, `0`→`false`, `"false"`→`false`, `"no"`→`false`
  (2) Null/missing field coercion: what happens when a required field is `null`?
  (3) Array coercion: `"a,b,c"` → `["a", "b", "c"]` (common LLM output pattern)
  (4) Nested object flattening: LLMs sometimes output `{"person.name": "John"}` instead of
  `{"person": {"name": "John"}}`
  (5) Enum coercion: case-insensitive matching for enum values
  The industry standard is Pydantic's type coercion, which handles all of these cases through
  its parsing system. Instructor library relies entirely on Pydantic for this.
evidence:
  - Pydantic coercion: `model_validate` with `from_attributes=True` or `strict=False` handles
    str→int, str→float, str→bool, and many more conversions
    (https://docs.pydantic.dev/latest/concepts/models/)
  - Instructor: "Automatic Retries: Built-in retry logic when validation fails. Data Validation:
    Leverage Pydantic's powerful validation to ensure response quality"
    (https://python.useinstructor.com/)
proposed_fix: >
  Add comprehensive coercion rules covering boolean aliases, null handling, array splitting,
  nested object flattening, and case-insensitive enum matching. Consider using Pydantic's
  validation engine internally instead of implementing a custom coercion layer. Add a
  `coercion_strategy: strict | lenient` flag to LLMCall so callers can opt into aggressive
  coercion for specific nodes.
```

## Issue 6: Structured error injection format may be ineffective compared to tool-based retry feedback

```
section: §3.3 — Retry on Violation (Structured Error Injection)
issue_type: weak_rationale
description: >
  The spec injects validation errors into the prompt using a plaintext `--- VALIDATION ERRORS ---`
  block. Both OpenAI and Anthropic use fundamentally different retry mechanisms. OpenAI's function
  calling retry sends ERROR tool_result messages back to the model. Anthropic similarly uses
  tool_result blocks. LangChain's ToolStrategy sends ToolMessage blocks with error content. The
  plaintext injection approach has two problems: (1) It multiplies prompt size with each retry,
  and (2) LLMs may misinterpret the injected text as part of the original prompt. There is no
  evidence the plaintext separator format outperforms structured tool_result messages. Additionally,
  the escalating prompt size problem (§9 Q5) is made worse by injecting full validation errors.
evidence:
  - LangChain ToolStrategy: uses `ToolMessage` with structured error feedback. "Schema validation error:
    When structured output doesn't match the expected schema, the agent provides specific error feedback"
    (https://python.langchain.com/docs/how_to/structured_output/#schema-validation-error)
  - OpenAI error handling: the `refusal` field on response indicates refusal, not a retry prompt
  - Anthropic: tool use responses include structured error blocks, not plaintext injection
proposed_fix: >
  When using provider-native structured output, rely on the provider's built-in error feedback
  (e.g., OpenAI's `refusal` field). When using post-process validation, use tool_result / ToolMessage
  blocks for retry feedback instead of plaintext injection into the prompt. If plaintext injection
  is retained, add a `max_prompt_inflation` guard to limit cumulative injection size and reference
  research on LLM correction behavior.
```

## Issue 7: Progressive Model Escalation misses industry-standard pre-call checks

```
section: §4 — Progressive Model Escalation
issue_type: missing_alternative
description: >
  The escalation system reacts to failures AFTER they occur (reactive). liteLLM's routing system
  provides proactive pre-call checks that avoid failures entirely:
  1. Context window checks — filter out deployments whose context window is too small
  2. RPM/TPM rate limit awareness — avoid deployments that would hit rate limits
  3. EU region filtering — enforce data residency before calling
  4. Health check driven routing — automatically skip unhealthy deployments
  5. Cooldown management — temporarily remove failing deployments
  The spec's escalation triggers (§4.3) only react to failures. Adding pre-call checks would reduce
  the need for escalation by preventing calls to models that are known to fail, reducing cost
  (fewer failed attempts on expensive tiers) and latency (no timeouts).
evidence:
  - liteLLM pre-call checks: "Enable pre-call checks to filter out deployments with context window
    limit < messages for a call" (https://docs.litellm.ai/docs/routing#pre-call-checks-context-window-eu-regions)
  - liteLLM cooldowns: "Set the limit for how many calls a model is allowed to fail in a minute,
    before being cooled down for a minute" (https://docs.litellm.ai/docs/routing#cooldowns)
  - liteLLM health check routing: automatic removal of unhealthy deployments
    (https://docs.litellm.ai/docs/proxy/health_check_routing)
proposed_fix: >
  Add §4.10 "Pre-Call Checks" that runs before escalation. Checks should include: context window
  verification, rate limit awareness (track RPM/TPM per deployment), deployment health status
  (automatic cooldown after N failures/minute), and optional region filtering. Pre-call checks
  reduce the number of unnecessary escalation triggers and provide a cost-efficient "fail before
  calling" mechanism. This is complementary to the reactive escalation flow.
```

## Issue 8: Deterministic fallback before escalation is a questionable optimization

```
section: §4.2 — Escalation Flow (Deterministic Fallback)
issue_type: wrong_approach
description: >
  The spec inserts a "deterministic fallback" step (keyword/regex extraction) between LLM failures
  and model escalation. The rationale is to avoid "unnecessary model escalation cost and latency."
  This is problematic because:
  (1) If the LLM couldn't produce valid JSON, keyword/regex on its raw text output is unlikely
      to produce higher-quality data — it's salvaging garbage.
  (2) A failing small model's raw output may contain hallucinations that keyword extraction
      silently accepts (no schema validation on fallback output).
  (3) The spec marks fallback results as "deterministic_fallback" in the audit trail but doesn't
      define quality gates for accepting fallback results (what confidence should we have in
      regex-extracted data?).
  (4) liteLLM's approach is the opposite: fallback is a completely separate mechanism (different
      model group), not a pre-escalation step within the same call chain.
  (5) The 100ms timeout for fallback is arbitrary and allows partial extraction (what if regex
      finds only 2 of 5 required fields?).
evidence:
  - liteLLM fallbacks: fallbacks happen between model groups AFTER retries are exhausted, not
    between retries on the same tier (https://docs.litellm.ai/docs/proxy/reliability)
  - No known industry pattern uses keyword/regex fallback between escalation tiers. It's an
    original (and untested) design.
proposed_fix: >
  Either: (a) Remove deterministic fallback from the escalation flow and keep it as a separate,
  optional node strategy (a "regex_extractor" executor alternative to "llm" executor at the
  node level); OR (b) Add strict quality gates: deterministic fallback must extract ALL required
  fields, must pass a minimum confidence check (e.g., regex pattern match rate ≥ 80%), and
  fallback-discovered values must be flagged for downstream review. The "salvage" approach should
  never silently produce production-quality data.
```

## Issue 9: Dynamic Routing (Option C) uses hardcoded weights vs. industry-standard ML-based routing

```
section: §4.6 — Option C: Dynamic Routing
issue_type: outdated_pattern
description: >
  The spec's Dynamic Routing option uses hardcoded weights (cost=0.4, latency=0.2, accuracy=0.4)
  to compute a ranking score per candidate model. This is a static heuristic. The industry is
  moving toward learned routing: liteLLM's Adaptive Router uses multi-armed bandit learning to
  estimate per-request-type quality scores for each model, with posterior sampling for optimal
  cost/quality trade-off. It learns over time which model performs best for "code_generation" vs
  "factual_lookup" vs "analytical_reasoning." liteLLM's Complexity Router uses rule-based scoring
  across 7 dimensions (token count, code presence, reasoning markers, etc.) without requiring ML.
  The hardcoded weight approach in the spec doesn't cite any research supporting the specific
  weight values, and static weights can't adapt to model improvements or degradation over time.
evidence:
  - liteLLM Adaptive Router: "The adaptive router does this automatically. It tracks which model
    performs best for each type of request (code, writing, analysis, etc.) and routes accordingly,
    balancing quality against cost based on weights you control"
    (https://docs.litellm.ai/docs/adaptive_router)
  - liteLLM Complexity Router: 7-dimension rule-based scoring with "zero external API calls and
    sub-millisecond latency" (https://docs.litellm.ai/docs/proxy/auto_routing#complexity-router)
  - Signals paper: "Trajectory Sampling and Triage for Agentic Interactions"
    (https://arxiv.org/abs/2604.00356)
proposed_fix: >
  Replace or augment Option C with two sub-options:
  C1: "Rule-Based Routing" (liteLLM's Complexity Router pattern) — score requests by token count,
       code presence, reasoning markers, technical terms, etc. with configurable dimension weights.
  C2: "Learned Routing" (liteLLM's Adaptive Router pattern) — multi-armed bandit or Bayesian
       optimization that learns per-request-type quality scores over time.
  Both are more maintainable and empirically grounded than hardcoded per-model weights.

  Also: the 3-option presentation implies these are mutually exclusive, but in practice they
  compose. liteLLM combines cooldowns, health checks, fallbacks, AND routing strategies. The
  spec should clarify how these options compose rather than presenting them as alternatives.
```

## Issue 10: Sticky Tier TTL decay is novel and untested — no industry evidence

```
section: §4.9 — Sticky Tier (Escalation Memory)
issue_type: weak_rationale
description: >
  The Sticky Tier concept — remembering which model worked last for a (node_id, intent) pair and
  starting from that tier — is a novel idea not seen in any major LLM routing framework. liteLLM
  uses cooldowns (temporary removal of failing deployments) and weighted failover (retry within
  same group before cross-group fallback), but not "remember success and skip lower tiers."
  The 300-second TTL is arbitrary with no evidence supporting it. The `max_sticky_tier: 1` guard
  is a reasonable safety measure but also limits the utility of the feature (you can never skip
  directly to Tier 2, even if Tier 2 consistently works). The `scope: node_id_and_intent` is
  granular but creates a large state space (N nodes × M intents × T tiers). No memory eviction
  strategy is defined. No mechanism for detecting when the small model has improved enough to
  warrant resetting to Tier 0 before TTL expiry.
evidence:
  - liteLLM cooldowns: temporarily remove deployments after N failures, don't remember successes
    (https://docs.litellm.ai/docs/routing#cooldowns)
  - liteLLM weighted failover: retry within same model group before cross-group, but always
    resets to initial routing strategy on next call
    (https://docs.litellm.ai/docs/routing#weighted-failover)
proposed_fix: >
  Mark §4.9 as EXPERIMENTAL with a clear caveat that this is a speculative optimization.
  Add: (1) Citation of evidence or simulation showing sticky tier reduces cost without
  degrading quality. (2) Memory eviction strategy (LRU with max entries). (3) Periodic
  probing: after N sticky-tier successes, attempt Tier 0 once to recalibrate (probe
  interval). (4) Consider removing in favor of liteLLM-style cooldowns, which are simpler
  and battle-tested.
```

## Issue 11: Missing retry budget dimension — cost-based budget

```
section: §3.3 — Retry on Violation / §4.4 — Tier-Aware Retry Budget
issue_type: missing_alternative
description: >
  The retry budget is defined exclusively in terms of attempt counts (base_max_attempts: 3,
  failures_before_escalation: 2). It does not consider cost. A caller might prefer "retry up
  to $0.05 total cost across all tiers" rather than "retry up to 5 attempts across 3 tiers."
  This is important because the cost difference between Tier 0 (gpt-4o-mini) and Tier 2 (gpt-4.1)
  is ~30x. Five Tier 2 attempts could cost more than twenty Tier 0 attempts. A count-based
  budget without a cost cap creates unpredictable billing. liteLLM supports cost-based routing
  and budget routing with spend limits per key/team that provides this guard.
evidence:
  - liteLLM Budget Routing: "Set budget limits per key or team to control spending"
    (https://docs.litellm.ai/docs/proxy/provider_budget_routing)
  - liteLLM cost-based routing: "Picks a deployment based on the lowest cost"
    (https://docs.litellm.ai/docs/routing#lowest-cost-routing-async)
proposed_fix: >
  Add `cost_budget` to the retry configuration:
  ```yaml
  retry_budget:
    type: attempts | cost
    max_attempts: 3        # when type=attempts
    max_cost_usd: 0.05     # when type=cost
    cost_tracking: per_call | per_node | per_conversation
  ```
  The audit trail already tracks cost (§4.5), so the data is available to enforce this.
```

## Issue 12: Layer 3 forced structured output is an anti-pattern for response generation

```
section: §7.3 — Layer 3 Response (generate_response)
issue_type: wrong_approach
description: >
  The spec mandates that even free-text response generation must use structured JSON output
  (`"text": { "type": "string", "required": true }`). This is an anti-pattern:
  (1) Both OpenAI and Anthropic docs distinguish between structured output (for extraction/APIs)
      and free-text responses.
  (2) Forcing JSON structure on creative/generative output degrades quality — LLMs produce
      stilted, overly-formal text when constrained by JSON schemas.
  (3) The schema `{"text": string, "components": array}` wraps free-text in a JSON envelope,
      adding parsing overhead with no benefit — the "text" field IS the free-text response.
  (4) The `components` field suggests structured UI components, but the YAML schema (`items:
      { type: object }`) doesn't specify what those components are, making the schema a
      false guarantee.
  The industry standard is: OPTIONAL structured output for extraction/classification; NO
  structured output for conversational response generation.
evidence:
  - OpenAI: "If you want to structure the model's output when it responds to the user, then
    you should use a structured response_format" — this is an OPTIONAL recommendation, not
    a mandate (https://platform.openai.com/docs/guides/structured-outputs)
  - OpenAI: "Structured Outputs via response_format are more suitable when you want to indicate
    a structured schema for use when the model responds to the user" — "more suitable" ≠ required
  - Anthropic: "JSON outputs control Claude's response format" — this is an opt-in feature
    (https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs)
  - LangChain: `response_format=None` for free-text agents
proposed_fix: >
  Allow Layer 3 nodes to use `response_mode: free_text` that bypasses JSON validation.
  The gateway would still require `output_schema` for all other layers but accept a
  `free_text` mode for response generation. If structured response components are needed
  (e.g., for a chat UI with cards), define that as a separate response composition layer
  rather than forcing the LLM to generate it during free-text response.
```

## Issue 13: Implementation Options comparison misses Instructor and Guardrails approaches

```
section: §5 — Implementation Options
issue_type: missing_alternative
description: >
  The spec covers three implementation options (Provider-Native, Post-Process, Hybrid) but
  misses two important patterns:
  1. Instructor library's approach: wrap any LLM client, intercept responses, parse and validate
     via Pydantic, re-ask on failure with validation context. This is similar to Post-Process
     but with a richer validation/re-ask cycle.
  2. Guardrails AI's approach: define validators per field (not just type, but also content
     quality checks like ValidLength, TwoWords, etc.), run them post-response, and either fix,
     reask, or filter. This adds content-level validation beyond JSON schema validation.
  Both Instructor and Guardrails support the "reask on validation failure" pattern that the
  spec's validation pipeline implements, but they offer richer validation primitives.
evidence:
  - Instructor: "Instructor's hooks system lets you intercept and handle events during LLM
    interactions. Use hooks for logging, monitoring, or custom error handling"
    (https://python.useinstructor.com/#using-hooks)
  - Instructor: "Automatically reask the model when validation fails, ensuring high-quality
    outputs. Leverage Pydantic's validation for robust error handling"
    (https://python.useinstructor.com/#why-use-instructor)
  - Guardrails AI: "Guardrails runs Input/Output Guards that detect, quantify and mitigate
    the presence of specific types of risks. Multiple validators can be combined together"
    (https://www.guardrailsai.com/docs)
proposed_fix: >
  Add §5.5 "Option D: Validator-Enhanced Post-Process" based on the Instructor/Guardrails pattern:
  - Post-process validation using Pydantic (not raw JSON Schema)
  - Field-level validators for content quality (not just type)
  - Rich reask context: instead of "missing field X," tell the LLM "field X should be a valid
    email address matching the pattern /.../"
  - Hooks/callbacks for custom validation logic
  Add this as a column to the comparison matrix in §5.4.
```

## Issue 14: No per-error-type retry policy — liteLLM's granular error handling is superior

```
section: §3.3 — Retry on Violation
issue_type: missing_alternative
description: >
  The spec treats all failures uniformly — same number of retries regardless of error type.
  liteLLM provides a RetryPolicy that allows per-error-type retry counts: ContentPolicyViolationError=3,
  AuthenticationError=0, RateLimitError=3, etc. This is important because:
  - AuthenticationError (401) should NEVER retry — it wastes budget
  - ContentPolicyViolationError may benefit from more retries with rephrased prompts
  - RateLimitError (429) needs exponential backoff, not fixed retries
  - TimeoutError (408) might benefit from a shorter timeout on retry
  The spec's uniform retry budget is simplistic and can lead to wasted retries on non-retryable errors.
evidence:
  - liteLLM RetryPolicy: "Use RetryPolicy to set num_retries based on the Exception received"
    with per-exception-type counts (https://docs.litellm.ai/docs/routing#advanced-custom-retries-cooldowns-based-on-error-type)
  - liteLLM AllowedFailsPolicy: per-error-type cooldown thresholds
proposed_fix: >
  Add `retry_policy` configuration with per-error-type overrides:
  ```yaml
  retry_policy:
    default: { max_attempts: 3, backoff: exponential }
    overrides:
      AuthenticationError: { max_attempts: 0, backoff: none }
      RateLimitError: { max_attempts: 5, backoff: exponential, base_delay_ms: 2000 }
      ContentPolicyViolationError: { max_attempts: 1 }
  ```
  Non-retryable errors (401, 403) should immediately escalate to errorNode regardless of
  retry budget.
```

## Issue 15: audit trail in §8 (errorNode) is less detailed than escalation audit in §4.5

```
section: §8 — Integration with errorNode
issue_type: weak_rationale
description: >
  The errorNode audit structure records: schema_violation, total_attempts, tiers_exhausted,
  last_tier, last_error. It is missing:
  - Cost breakdown per tier (present in §4.5 escalation audit but not here)
  - Coercion details (present in §3.2 but not propagated to errorNode)
  - Confidence threshold violations (from §3.5)
  - A machine-readable error classification (distinguishing JSON parse vs schema mismatch vs
    provider timeout vs confidence threshold)
  - The raw LLM responses from each failed attempt (critical for debugging)
  The escalation audit trail (§4.5) is significantly richer and inconsistent with §8's structure,
  suggesting these were designed by different authors or at different times.
evidence:
  - liteLLM includes deployment_id, model_id, error type classification, and per-deployment
    cost tracking in all failure records (https://docs.litellm.ai/docs/routing#cooldowns)
proposed_fix: >
  Unify the audit structures in §4.5 and §8. The errorNode audit should be a superset of the
  escalation audit: include cost breakdown, coercion details, confidence thresholds, raw responses,
  and a structured error classification field with an enum (JSON_PARSE_ERROR, SCHEMA_MISMATCH,
  TYPE_COERCION_FAILURE, CONFIDENCE_BELOW_THRESHOLD, PROVIDER_TIMEOUT, PROVIDER_5XX,
  RATE_LIMITED, AUTH_FAILURE, CONTENT_POLICY_VIOLATION). This enables downstream analytics
  on failure patterns.
```

## Issue 16: Open Question §9 Q5 (prompt reset vs carry-forward) is a significant cost concern

```
section: §9.5 — Open Question: Should escalation reset the prompt context?
issue_type: weak_rationale
description: >
  The spec asks whether escalation should reset the prompt or carry forward error-enriched
  prompts. This is flagged as an open question but has significant cost implications:
  - Carrying forward: each escalation adds the full previous conversation (system prompt +
    user messages + all error injections) to the next tier's context. With 3 tiers and 2
    failures per tier, the prompt could grow 4x (original + 3 error injections).
  - Resetting: loses the correction context, so the new tier's LLM sees a "clean" prompt
    but doesn't know what went wrong.
  OpenAI's accuracy optimization guide recommends AGAINST long correction chains: "Don't
  keep retrying with the same approach — vary your prompts." But neither option (reset vs
  carry-forward) is clearly correct. The spec should acknowledge this as a research question
  and provide a configurable strategy rather than punting it to the adoption phase.
evidence:
  - OpenAI accuracy optimization guide: recommends varying approach on retry, not accumulating
    error context (https://platform.openai.com/docs/guides/optimizing-llm-accuracy)
  - liteLLM allows per-fallback custom messages (different prompts per model), which is a middle
    ground (https://docs.litellm.ai/docs/proxy/reliability#control-fallback-prompts)
proposed_fix: >
  Add a configuration option `prompt_strategy_on_escalation` with three values:
  - `carry_forward`: append error context (current behavior, default)
  - `reset`: fresh prompt per tier (no error history)
  - `summarize`: inject a one-line summary of previous failures ("Previous attempts on Tier 0
    failed with: missing field 'confidence'. Please ensure all required fields are present.")
  Document the trade-offs (cost, correction quality) and recommend `summarize` as the default
  for production. Add a `max_prompt_length` guard that forces `reset` if the accumulated prompt
  exceeds a configured limit.
```

## Issue 17: Missing caching integration — liteLLM provides this out of the box

```
section: §9.2 — Open Question: Should the gateway cache identical LLM calls?
issue_type: missing_alternative
description: >
  The spec treats caching as an open question but liteLLM provides Redis-based response caching
  and in-memory caching out of the box with `cache_responses=True`. This is not just a dev-time
  optimization — in production, identical extraction calls (same user utterance → same intent
  classification) are common in multi-turn conversations. The cost savings of caching are
  significant (zero-token responses for cache hits). OpenAI supports prompt caching natively
  for system prompts, which is complementary. Anthropic also supports prompt caching. The spec
  should move caching from an open question to a documented feature.
evidence:
  - liteLLM caching: "In production, we recommend using a Redis cache. For quickly testing
    things locally, we also support simple in-memory caching"
    (https://docs.litellm.ai/docs/routing#caching)
  - OpenAI prompt caching: "Prompt Caching reduces latency and cost by caching the longest
    prefix of a prompt" (https://platform.openai.com/docs/guides/prompt-caching)
  - Anthropic prompt caching: server-side caching of system prompts and long prefixes
proposed_fix: >
  Move caching from Open Question to a documented feature (§3.6 "LLM Call Caching"):
  - In-memory cache for dev (simple dict, no dependencies)
  - Redis cache for production (distributed, TTL-based invalidation)
  - Cache key: (hash(prompt) + hash(output_schema) + model + temperature)
  - Configurable per-node: `cache: enabled | disabled | ttl_seconds`
  - Audit trail records `cache_hit: true/false` for cost tracking
  - Note interaction with model escalation: cached results bypass escalation (if a call was
    previously cached, it already succeeded — no need to re-escalate)
```

## Issue 18: `$ref` and `$defs` handling is a real implementation gap but spec doesn't acknowledge severity

```
section: §9.3 — Open Question: How to handle $ref/$defs across providers?
issue_type: outdated_pattern
description: >
  The spec asks how `$ref` and `$defs` should be handled. This is not an open question — it's
  a well-understood limitation. OpenAI's Structured Outputs does NOT support `$ref` or `$defs`
  in schemas — all references must be resolved (dereferenced/inlined) before sending to the API.
  OpenAI also limits nesting depth to 5 levels and total schema properties to 100. Anthropic's
  structured outputs similarly requires flat schemas. The solution is schema preprocessing:
  dereference all `$refs`, flatten recursively, and validate against provider limits before
  sending. This should be a documented implementation detail, not an open question.
  LangChain's JSON Schema support already handles auto-inlining of references.
evidence:
  - OpenAI: "Structured Outputs supports a subset of JSON Schema. root must be type:object,
    nesting depth max 5, total properties max 100" (https://platform.openai.com/docs/guides/structured-outputs)
  - Anthropic: "JSON Schema limitations: root must be type:object, additionalProperties: false
    required, no $ref, no $defs" (https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs#json-schema-limitations)
  - LangChain schema handling: auto-dereferences $refs and adapts schemas for each provider
proposed_fix: >
  Move §9.3 from Open Questions to §6.3 "Schema Preprocessing" documenting the dereference
  pipeline: (1) Resolve all `$ref` references (inline $defs), (2) Validate nesting depth ≤ 5,
  (3) Count total properties ≤ provider limit, (4) Strip unsupported keywords per provider
  (e.g., remove `$comment`, `examples` for OpenAI). Add a `schema_complexity` warning level
  that alerts when a schema is pushing provider limits.
```

---

## Summary: Severity Classification

| Severity | Issues |
|----------|--------|
| **Critical** (design flaw) | #1 (mandatory output_schema), #12 (Layer 3 forced JSON), #8 (deterministic fallback quality) |
| **High** (missing alternative) | #3 (Pydantic schema), #13 (Instructor/Guardrails), #7 (pre-call checks), #11 (cost-based budget) |
| **Medium** (weak rationale) | #4 (x-threshold), #9 (static weights), #6 (error injection), #15 (audit inconsistency), #10 (sticky tier no-evidence) |
| **Low** (incomplete/edge case) | #2 (temperature conflict), #5 (coercion gaps), #14 (per-error retry), #16 (Q5 cost concern), #17 (caching), #18 ($ref handling) |

**Top 3 most impactful fixes:**
1. Make `output_schema` strongly recommended, not mandatory — exclude Layer 3 from the hard constraint (#1)
2. Add Pydantic model as a first-class schema definition mechanism, following the Instructor/LangChain pattern (#3)
3. Add pre-call checks (context window, rate limits, deployment health) before escalation to prevent avoidable failures (#7)
