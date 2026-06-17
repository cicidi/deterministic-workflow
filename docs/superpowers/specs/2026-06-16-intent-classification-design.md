# Layer 1: Intent Classification

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Focused on: Intent classification within the UNDERSTAND layer.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | Initial intent classification spec |

---

## 1. Role

Intent classification answers: *"What does the user want to do?"*

It maps a free-form user utterance to a predefined intent label, optionally with a confidence score. The output is consumed by the state machine (Layer 2) to determine valid state transitions.

## 2. Intent Model

### 2.1 System Intents (built-in)

| Intent | Description |
|--------|-------------|
| `ask_question` | User asks for information or explanation |
| `provide_information` | User provides data in response to a prompt |
| `start_conversation` | User initiates a new conversation |
| `resume_conversation` | User returns to a previous conversation |
| `finish_conversation` | User wants to end the conversation |
| `unrecognized_intent` | Cannot determine intent (low confidence fallback) |
| `confirm` | User agrees or confirms |
| `decline` | User disagrees, cancels, or rejects |

### 2.2 Custom Intents (per-workflow)

Each workflow can define additional domain-specific intents. Example for an insurance workflow:

```
intents:
  - name: get_quote
    description: User wants an insurance premium quote
    keywords: [quote, price, cost, how much, 报价]
    examples:
      - "I want to get a car insurance quote"
      - "How much for home insurance?"

  - name: file_claim
    description: User wants to file an insurance claim
    keywords: [claim, accident, damage, 理赔]
    examples:
      - "I need to file a claim"
      - "My car was damaged in an accident"
```

### 2.3 Intent Definition Schema

```
IntentDef {
  name:         string      // unique identifier
  description:  string      // guides LLM classification
  keywords:     string[]    // deterministic fallback patterns
  examples:     string[]    // few-shot examples for LLM prompt
}
```

## 3. Classification Strategy: LLM-First + Keyword Fallback

### 3.1 Conversation Context

Intent classification is not a single-message operation. The LLM prompt must include conversation history to resolve ambiguous utterances. For example, "yes" means `confirm` if the agent just asked "should I proceed?" but means `provide_information` if the agent asked "what's your name?".

The framework includes the **last 3 user messages + last 3 agent messages** as context in every classification call. This provides enough history to disambiguate short responses without bloating the prompt.

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

### 3.2 Fallback: Keyword Matching

If the LLM call fails or returns `confidence < threshold`, the framework runs keyword matching against the user's input:

```
For each intent:
  if any keyword matches user_input (case-insensitive):
    return that intent with confidence=1.0
```

System intents have built-in keyword patterns. Custom intents use user-provided `keywords`.

### 3.3 Confidence Threshold

A configurable threshold (default `0.7`). When the LLM returns `confidence < threshold`, the result is treated as `unrecognized_intent`, which triggers a clarification response from Layer 3.

### 3.4 Merge Strategy

```
1. Try LLM classification
2. If LLM fails → fallback to keyword matching
3. If LLM succeeds but confidence < threshold → use fallback result (if any)
4. If neither produces a result → unrecognized_intent
```

LLM result + fallback result can disagree. When they disagree and LLM confidence is above threshold, LLM wins. When both are below, keyword fallback wins (it's deterministic).

## 4. Output Contract

```
ClassificationResult {
  intent:     string      // the resolved intent label
  confidence: number      // 0.0 - 1.0
  source:     "llm" | "keyword" | "unrecognized"
  reasoning?: string      // LLM's reasoning (for audit trail)
}
```

The `source` field indicates which classifier produced the result, enabling downstream nodes to adjust behavior (e.g., "keyword match → proceed immediately; LLM match → consider re-confirming").

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent document
- [State Machine Design](./2026-06-16-state-machine-design.md) — intent+state resolution logic
