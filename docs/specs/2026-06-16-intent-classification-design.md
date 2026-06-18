# Layer 1: Intent Classification

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Focused on: Intent classification within the UNDERSTAND layer.
> All concrete intent examples have been extracted to [examples/home-insurance/](../../examples/home-insurance/).

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | Initial intent classification spec |
| 2026-06-16 | 0.2.0 | Extract custom intent examples to examples/; fix section numbering |
| 2026-06-17 | 0.3.0 | Add implementation options comparison, YAML schema, open questions, errorNode cross-reference, agentState.phase mention |
| 2026-06-18 | 0.4.0 | IntentDef adds `complex` field; multi-intent detection implemented (single user message → multiple intents); intent combination validation rules; intent→payload mapping table |

---

## 1. Role

Intent classification answers: *"What does the user want to do?"*

It maps a free-form user utterance to a predefined intent label, optionally with a confidence score. The output is consumed by the state machine (Layer 2) to determine valid state transitions.

## 2. Intent Model

### 2.1 System Intents (built-in)

| Intent | Description | Complex | Can Combine |
|--------|-------------|---------|-------------|
| `ask_question` | User asks for information or explanation | false | yes |
| `provide_information` | User provides data in response to a prompt | false | yes |
| `start_conversation` | User initiates a new conversation | false | yes |
| `resume_conversation` | User returns to a previous conversation | false | yes |
| `finish_conversation` | User wants to end the conversation | false | yes |
| `unrecognized_intent` | Cannot determine intent (low confidence fallback) | false | yes |
| `confirm` | User agrees or confirms | false | yes |
| `decline` | User disagrees, cancels, or rejects | false | yes |

### 2.2 Custom Intents (per-workflow)

Each workflow can define additional domain-specific intents. For a complete catalog of home insurance intents with keywords and examples, see [intent-definitions.md](../../examples/home-insurance/intent-definitions.md). The framework uses the same `IntentDef` schema for both system and custom intents.

### 2.3 Intent Definition Schema

```yaml
# Schema: IntentDef
#   name:        string      # unique identifier
#   description: string      # guides LLM classification
#   complex:     boolean     # true = multi-turn task; cannot combine with other complex intents
#   keywords:    string[]    # deterministic fallback patterns
#   examples:    string[]    # few-shot examples for LLM prompt

intents:
  - name: "ask_question"
    description: "User asks for information or explanation"
    complex: false
    keywords:
      - "what is"
      - "how does"
      - "tell me about"
      - "explain"
    examples:
      - "What is my deductible?"
      - "How does the claims process work?"
      - "Tell me about coverage options"

  - name: "get_quote"
    description: "User requests a new insurance quote"
    complex: true
    keywords:
      - "quote"
      - "get a price"
      - "how much"
      - "estimate"
    examples:
      - "I want a quote for home insurance"
      - "How much would it cost to insure my house?"
      - "Give me a price estimate"
```

### 2.4 Implementation Options

The framework supports three classification strategies. Projects select one at configuration time based on their latency, cost, and determinism requirements.

| Dimension | Option A: LLM-Only | Option B: Keyword/Regex-Only | Option C: LLM + Keyword Fallback |
|-----------|-------------------|------------------------------|----------------------------------|
| **Accuracy** | High (understands nuance) | Low–Medium (literal matches only) | High (LLM primary, keyword safety net) |
| **Determinism** | Low (non-deterministic by nature) | High (100% predictable) | Medium (keyword guarantees for known patterns) |
| **Latency** | 200–800ms (API call) | <1ms | 200–800ms (LLM); <1ms on LLM failure |
| **Cost** | Per-classification API cost | Free | Per-classification API cost (no cost on keyword-only hit) |
| **Graceful Degradation** | None (LLM failure = unrecognized) | Bare keyword matching only | Falls back to keyword on LLM failure |
| **Extensibility** | Prompt adjustments only | Add keywords/regex patterns | Add keywords + prompt adjustments |
| **Best For** | Prototyping, simple domains | High-throughput, narrow-domain bots | Production systems in regulated industries |

**Option A: LLM-Only** — Every classification goes through the LLM. No keyword fallback. Simple but no safety net.
**Option B: Keyword/Regex-Only** — Pure pattern matching. Fast and deterministic but cannot handle ambiguous or novel utterances.
**Option C: LLM + Keyword Fallback** (default) — LLM-first with keyword safety net. Recommended for production.

The remainder of this document describes Option C in detail.

## 3. Classification Strategy: LLM-First + Keyword Fallback

> **All LLM output is JSON.** The framework enforces schema validation, field presence, and type coercion on every classification result via output guardrails (see HLD Section 4.3). If JSON is malformed, the guardrail auto-retries within the retry budget.

### 3.1 Conversation Context

Intent classification is not a single-message operation. The LLM prompt must include conversation history to resolve ambiguous utterances. For example, "yes" means `confirm` if the agent just asked "should I proceed?" but means `provide_information` if the agent asked "what's your name?".

The framework includes the **last 3 user messages + last 3 agent messages** as context in every classification call. This provides enough history to disambiguate short responses without bloating the prompt.

> **Note:** Intent classification input also includes `agentState.phase` (e.g., `quoting`, `claims`, `onboarding`). The current workflow phase provides state-aware context that helps the classifier disambiguate intents — for example, "I want to change that" in the `quoting` phase likely refers to modifying a quote, while in the `claims` phase it likely refers to updating a claim.

### 3.2 Edge Case Coverage

Intent classification serves as the system's safety net for unexpected user behavior. Edge cases it must handle:

- Abrupt topic switches mid-workflow ("never mind, I want to pay someone instead")
- Ambiguous one-word responses ("ok", "sure", "no")
- Off-topic questions during a workflow
- Partial or incomplete utterances
- Code-switching or mixed-language input

When the classifier cannot confidently resolve an edge case, it returns `unrecognized_intent`, triggering a clarification response.

### 3.3 LLM Prompt Construction

The framework builds a system prompt from the user's intent definitions and conversation context. The prompt includes:

1. The last 3 user messages + last 3 agent messages (context window)
2. A list of all intents with their descriptions
3. A few-shot examples for each intent
4. A structured output instruction: `{ intent: string, confidence: number, reasoning: string }`

Temperature is set to 0 for deterministic classification.

### 3.4 Fallback: Keyword Matching

If the LLM call fails or returns `confidence < threshold`, the framework runs keyword matching against the user's input:

```
For each intent:
  if any keyword matches user_input (case-insensitive):
    return that intent with confidence=1.0
```

System intents have built-in keyword patterns. Custom intents use user-provided `keywords`.

### 3.5 Confidence Threshold

A configurable threshold (default `0.7`). When the LLM returns `confidence < threshold`, the result is treated as `unrecognized_intent`, which triggers a clarification response from Layer 3.

### 3.6 Merge Strategy

```
1. Try LLM classification
2. If LLM fails → fallback to keyword matching
3. If LLM succeeds but confidence < threshold → use fallback result (if any)
4. If neither produces a result → unrecognized_intent
```

LLM result + fallback result can disagree. When they disagree and LLM confidence is above threshold, LLM wins. When both are below, keyword fallback wins (it's deterministic).

> **Note:** If neither LLM nor keyword produces a result (`unrecognized_intent`), the framework routes to the `errorNode` for unified error handling (see Routing & Execution spec Section 6).

## 4. Output Contract

### 4.1 Classification Result (per-intent)

```
ClassifiedIntent {
  intent:     string      // the resolved intent label
  confidence: number      // 0.0 - 1.0
  source:     "llm" | "keyword" | "unrecognized"
  reasoning?: string      // LLM's reasoning (for audit trail)
}
```

The `source` field indicates which classifier produced the result, enabling downstream nodes to adjust behavior (e.g., "keyword match → proceed immediately; LLM match → consider re-confirming").

### 4.2 Multi-Intent Output

A single user utterance may carry multiple intents ("I want to file a claim, my phone is 123-456-7890"). The classifier returns a list of `ClassifiedIntent` objects:

```
ClassificationResult {
  intents: ClassifiedIntent[]  // one or more resolved intents
}
```

**Example:**

```json
{
  "intents": [
    {
      "intent": "file_claim",
      "confidence": 0.95,
      "source": "llm"
    },
    {
      "intent": "provide_information",
      "confidence": 0.88,
      "source": "llm",
      "reasoning": "User provided phone number alongside claim intent"
    }
  ]
}
```

### 4.3 Intent Combination Rules

Each intent carries a `complex` flag. The combination rules prevent incompatible combinations in a single processing round:

| Scenario | Allowed | Behavior |
|----------|---------|----------|
| Multiple simple intents | Yes | Process together |
| 1 complex + N simple intents | Yes | Process together (simple intents ride on the complex workflow) |
| Multiple complex intents | No (by default) | See conflict resolution below |

**Conflict resolution for multiple complex intents** is configured in the Response node under `on_multi_intent_conflict`:

| Mode | Behavior |
|------|----------|
| `error` (default) | Throw `MultiIntentConflictError`; response layer asks user which task to handle first |
| `sequential` | Process highest-confidence complex intent first; queue remaining for next turn |

**Validation pseudo-code:**

```
def validate_intent_combination(intents: ClassifiedIntent[], intent_defs: IntentDef[], mode: string):
    complex = [i for i in intents if intent_defs[i.intent].complex]
    if len(complex) > 1:
        if mode == "error":
            raise MultiIntentConflictError(
                conflict_intents=[i.intent for i in complex],
                message="您提到了多个任务，请先选择一个处理。"
            )
        # sequential: keep highest-confidence, queue the rest
```

---

## 5. Open Questions

### 5.1 Multi-Intent Detection

Multi-intent detection is now implemented. The classifier returns a list of `ClassifiedIntent` objects per user message (see Section 4.2). Intent combination validation (Section 4.3) prevents incompatible complex intents from being processed together.

### 5.2 Intent → Extraction Payload Mapping

Each intent is mapped to a typed extraction payload consumed by the Extract node (see [Extraction Layer Spec](./2026-06-17-extraction-layer-design.md)):

| Intent | Payload Class | Payload Data |
|--------|--------------|--------------|
| `confirm` | `ConfirmIntentPayload` | `fields: dict[str, bool]` |
| `decline` | `DeclineIntentPayload` | `fields: dict[str, bool]` |
| `provide_information` | `ProvideInformationIntentPayload` | `field_values: dict[str, Any]` |
| `get_quote` | `GetQuoteIntentPayload` | `field_values: dict[str, Any]` |
| `file_claim` | `FileClaimIntentPayload` | `field_values: dict[str, Any]` |
| `ask_question` | *(skip extraction)* | routed directly to Q&A node |
| `unrecognized_intent` | *(skip extraction)* | routed directly to clarification node |

### 5.3 Intent Analysis Prompt Guidelines

When the LLM analyzes a user message, it should:

1. Identify all intents present (may be multiple)
2. For each intent, extract any associated data fields
3. Return an `ClassifiedIntent` for EACH detected intent with its own confidence score
4. Do not merge data from different intents into a single payload

**Example:** "I want to file a claim, my phone is 123-456-7890" produces TWO payloads — one `FileClaimIntentPayload` (no data) + one `ProvideInformationIntentPayload` (phone number).

### 5.4 Confidence Threshold Calibration

The default threshold of `0.7` is a starting point. In practice, optimal thresholds vary by domain, intent complexity, and LLM model choice. How should teams calibrate thresholds? Options include: historical accuracy analysis per intent, A/B testing, or adaptive thresholds based on conversation phase.

### 5.5 Intent Drift Over Long Conversations

In long-running conversations (e.g., 20+ turns), user intent may shift gradually without an abrupt topic switch. Should the framework detect intent drift via a windowed confidence trend, or rely on the Layer 2 state machine to detect phase mismatches?

### 5.6 Cross-Lingual Intent Classification

How should the framework handle non-English input? Options include: (a) translate-to-English before classification, (b) include multilingual examples in the prompt, (c) use a multilingual embedding model. Each has different latency, cost, and accuracy trade-offs.

### 5.7 Cold Start: Zero-Shot vs. Few-Shot Prompting

For custom intents with no training examples provided, should the framework fall back to a zero-shot prompt, or require a minimum number of examples? Zero-shot is more flexible but less accurate for domain-specific intents.

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent document
- [State Machine Design](./2026-06-16-state-machine-design.md) — intent+state resolution logic
