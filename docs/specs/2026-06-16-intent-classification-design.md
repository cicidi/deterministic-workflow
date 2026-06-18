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
| 2026-06-18 | 0.6.0 | Remove keyword fallback entirely: delete §3.4 (Keyword Matching) + §3.6 (Merge Strategy); simplify to LLM-only flow with `unrecognized_intent` as the sole fallback; remove `"keyword"` from `ClassifiedIntent.source` enum; keywords kept in IntentDef as metadata only |
| 2026-06-18 | 0.5.1 | Simplify §2.4: remove Options A/B/C comparison table; keep only LLM + keyword fallback as the single strategy |
| 2026-06-18 | 0.5.0 | Expand system intents from 8 to 17: remove `resume_conversation` (demoted to system state, not user intent); add `help`, `correction`, `chitchat`, `out_of_scope`, `repeat`, `escalate`, `restart`, `complaint`, `pause`, `ambiguous_request`; add keyword + example YAML definitions for all system intents; expand §5.2 payload mapping to all 17 system intents |
| 2026-06-18 | 0.4.0 | IntentDef adds `complex` field; multi-intent detection implemented (single user message → multiple intents); intent combination validation rules; intent→payload mapping table |

---

## 1. Role

Intent classification answers: *"What does the user want to do?"*

It maps a free-form user utterance to a predefined intent label, optionally with a confidence score. The output is consumed by the state machine (Layer 2) to determine valid state transitions.

## 2. Intent Model

### 2.1 System Intents (built-in)

All 17 system intents below are available to every workflow. They cover conversation lifecycle, error recovery, task disambiguation, and social interaction — independent of any product domain.

| Category | Intent | Description | Complex |
|----------|--------|-------------|---------|
| **Conversation Lifecycle** | `start_conversation` | User initiates a new conversation | false |
| | `finish_conversation` | User wants to end the conversation | false |
| | `pause` | User asks the bot to pause or wait ("hold on", "wait a moment") | false |
| | `restart` | User wants to start the current workflow over from the beginning | false |
| **Information Exchange** | `ask_question` | User asks for information or explanation | false |
| | `provide_information` | User provides data in response to a prompt | false |
| | `repeat` | User asks the bot to repeat the last response | false |
| **Confirmation** | `confirm` | User agrees or confirms | false |
| | `decline` | User disagrees, cancels, or rejects | false |
| **Error & Recovery** | `unrecognized_intent` | Cannot determine intent (low confidence fallback) | false |
| | `correction` | User corrects a prior statement — theirs or the bot's | false |
| | `ambiguous_request` | Utterance maps to multiple possible intents; needs disambiguation | false |
| | `out_of_scope` | Request recognized but system explicitly does not support it | false |
| **Social & Meta** | `help` | User asks about system capabilities or how to use the bot | false |
| | `chitchat` | Casual social conversation unrelated to any task | false |
| | `complaint` | User expresses dissatisfaction or files a complaint | false |
| | `escalate` | User requests to speak with a human agent | false |

> **All system intents are `complex: false`** — they can be freely combined with each other and with custom intents in a single classification round (see §4.3).

#### System Intent Keywords & Examples

Each system intent includes `keywords` for documentation and `examples` for LLM few-shot prompting. Keywords are not used in runtime classification.

```yaml
# SYSTEM INTENTS — built into the framework
# All complex: false; all can combine with simple intents

system_intents:
  # ── Conversation Lifecycle ──
  - name: start_conversation
    description: User initiates a new conversation
    keywords: [hello, hi, hey, good morning, good afternoon, greetings, what's up]
    examples:
      - "Hello, I need help"
      - "Hi there"
      - "Good morning"

  - name: finish_conversation
    description: User wants to end the conversation
    keywords: [bye, goodbye, that's all, done, no more questions, I'm finished, see you, thanks bye]
    examples:
      - "That's all I needed, thanks"
      - "Goodbye"
      - "I'm done, thank you"

  - name: pause
    description: User asks the bot to pause or wait
    keywords: [wait, hold on, one moment, give me a second, pause, hang on, let me think, not ready]
    examples:
      - "Wait, let me check something"
      - "Hold on a moment"
      - "Give me a second"

  - name: restart
    description: User wants to start the current workflow over from the beginning
    keywords: [start over, begin again, restart, from the beginning, reset, clear everything, new session, let's redo]
    examples:
      - "Let's start over"
      - "Can we begin again?"
      - "Reset everything, I made a mistake"

  # ── Information Exchange ──
  - name: ask_question
    description: User asks for information or explanation
    keywords: [what is, how does, tell me about, explain, why, when did, where is, who is, can you tell]
    examples:
      - "What is my deductible?"
      - "How does the claims process work?"
      - "Tell me about coverage options"

  - name: provide_information
    description: User provides data in response to a prompt
    keywords: [my name is, my phone is, my address is, the number is, it's, here is, this is]
    examples:
      - "My name is John"
      - "The address is 123 Main St"
      - "It's 555-0123"

  - name: repeat
    description: User asks the bot to repeat the last response
    keywords: [repeat, say that again, what did you say, come again, pardon, sorry what, can you repeat, once more]
    examples:
      - "Can you repeat that?"
      - "What did you say?"
      - "Say that again please"

  # ── Confirmation ──
  - name: confirm
    description: User agrees or confirms
    keywords: [yes, yeah, correct, that's right, exactly, sounds good, okay, sure, go ahead, proceed]
    examples:
      - "Yes, that's correct"
      - "Sounds good, proceed"
      - "Yeah, go ahead"

  - name: decline
    description: User disagrees, cancels, or rejects
    keywords: [no, nope, not, that's wrong, incorrect, cancel, stop, never mind, I don't want, reject]
    examples:
      - "No, that's not what I want"
      - "Cancel that"
      - "Never mind, forget it"

  # ── Error & Recovery ──
  - name: unrecognized_intent
    description: Cannot determine intent (low confidence fallback)
    keywords: []  # no keywords — produced by classifier when confidence < threshold
    examples: []  # no examples — this is a fallback output, not a user-expressed intent
    note: "Framework-internal fallback. Not matched by keywords; produced when all classification fails."

  - name: correction
    description: User corrects a prior statement — theirs or the bot's
    keywords: [no, wrong, that's not right, I meant, actually, not that, I said, change that to, correct that, not X]
    examples:
      - "No, I meant 456 Oak Street, not 123 Main"
      - "That's wrong, my phone is 555-9999"
      - "Actually, I changed my mind — make it $500k coverage"

  - name: ambiguous_request
    description: Utterance maps to multiple possible intents; needs disambiguation
    keywords: []  # no keywords — produced by classifier when confidence is split
    examples: []  # no examples — this is a classifier meta-output
    note: "Framework-internal meta-intent. Produced when classifier detects multiple equally-plausible intents and needs user disambiguation."

  - name: out_of_scope
    description: Request recognized but system explicitly does not support it
    keywords: []  # no keywords — determined by system capability registry, not user phrasing
    examples: []  # no examples — the user's words vary; classifier cross-references with capability registry
    note: "Framework-internal meta-intent. Produced when the classifier identifies a valid request pattern that the system's capability registry marks as unsupported."

  # ── Social & Meta ──
  - name: help
    description: User asks about system capabilities or how to use the bot
    keywords: [help, what can you do, how do I use, guide me, assist, support, what are you capable of, commands, options]
    examples:
      - "What can you help me with?"
      - "How do I use this?"
      - "What are my options?"

  - name: chitchat
    description: Casual social conversation unrelated to any task
    keywords: [how are you, how's it going, thank you, thanks, appreciate it, tell me a joke, nice weather, lol, haha, how do you do]
    examples:
      - "How are you today?"
      - "Thank you for helping!"
      - "Tell me a joke"

  - name: complaint
    description: User expresses dissatisfaction or files a complaint
    keywords: [complaint, unhappy, dissatisfied, frustrated, terrible, awful, bad service, not satisfied, want to complain, this is unacceptable]
    examples:
      - "I'm very unhappy with this process"
      - "This is terrible service"
      - "I want to file a complaint"

  - name: escalate
    description: User requests to speak with a human agent
    keywords: [human, speak to someone, real person, talk to a person, representative, agent, customer service, operator, transfer me, connect me to]
    examples:
      - "I want to speak to a human"
      - "Can you transfer me to an agent?"
      - "Let me talk to a real person"
```

> **Meta-intents** (`unrecognized_intent`, `ambiguous_request`, `out_of_scope`) are produced by the classifier, not by pattern matching. They rely entirely on LLM classification and capability registry lookup. See §3 for classification flow.

### 2.2 Custom Intents (per-workflow)

Each workflow can define additional domain-specific intents. For a complete catalog of home insurance intents with keywords and examples, see [intent-definitions.md](../../examples/home-insurance/intent-definitions.md). The framework uses the same `IntentDef` schema for both system and custom intents.

### 2.3 Intent Definition Schema

```yaml
# Schema: IntentDef
#   name:        string      # unique identifier
#   description: string      # guides LLM classification
#   complex:     boolean     # true = multi-turn task; cannot combine with other complex intents
#   keywords:    string[]    # metadata only (not used in runtime classification)
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

### 2.4 Classification Strategy

The framework uses **LLM-first classification**. No keyword fallback — if the LLM cannot classify with sufficient confidence, the framework asks the user to clarify.

| Dimension | Behavior |
|-----------|----------|
| **Primary** | LLM classifies the user utterance with conversation context and intent definitions |
| **Confidence Threshold** | Configurable, default `0.7`. Below threshold → `unrecognized_intent` → clarification |
| **LLM Failure** | Gateway retries within budget. Exhausted → `unrecognized_intent` → clarification |
| **Temperature** | 0 (deterministic output) |

The full classification flow is specified in §3.

## 3. Classification Strategy: LLM-First

> **All LLM output is JSON.** The framework enforces schema validation, field presence, and type coercion on every classification result via output guardrails (see HLD Section 4.3). If JSON is malformed, the guardrail auto-retries within the retry budget.

### 3.1 Conversation Context

Intent classification is not a single-message operation. The LLM prompt must include conversation history to resolve ambiguous utterances. For example, "yes" means `confirm` if the agent just asked "should I proceed?" but means `provide_information` if the agent asked "is your phone number 555-0123?" (confirming extracted data). Without context, a one-word reply like "yes" to "what's your name?" is `unrecognized_intent` — it makes no semantic sense.

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

### 3.4 Classification Flow

```
1. Build LLM prompt (context + intents + examples)
2. Call LLM Gateway (temperature=0, output_schema enforcement)
3. If confidence ≥ threshold → return classified intents
4. If confidence < threshold or LLM fails (retries exhausted) → return unrecognized_intent
5. Route to Layer 3 for clarification response
```

There is no keyword fallback. A low-confidence result and a failed LLM call produce the same outcome: `unrecognized_intent`, triggering a clarification question. This is simpler, more predictable, and avoids keyword collision across 17+ intents.

## 4. Output Contract

### 4.1 Classification Result (per-intent)

```
ClassifiedIntent {
  intent:     string      // the resolved intent label
  confidence: number      // 0.0 - 1.0
  source:     "llm" | "unrecognized"
  reasoning?: string      // LLM's reasoning (for audit trail)
}
```

The `source` field indicates which classifier produced the result, enabling downstream nodes to adjust behavior (e.g., "LLM match with high confidence → proceed; LLM match with borderline confidence → re-confirm").

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
                message="Multiple tasks detected. Please choose one to handle first."
            )
        # sequential: keep highest-confidence, queue the rest
```

---

## 5. Open Questions

### 5.1 Multi-Intent Detection

Multi-intent detection is now implemented. The classifier returns a list of `ClassifiedIntent` objects per user message (see Section 4.2). Intent combination validation (Section 4.3) prevents incompatible complex intents from being processed together.

### 5.2 Intent → Extraction Payload Mapping

Each intent is mapped to a typed extraction payload consumed by the Extract node (see [Extraction Layer Spec](./2026-06-17-extraction-layer-design.md)):

#### System Intents

| Intent | Payload Class | Extraction / Routing |
|--------|--------------|---------------------|
| `start_conversation` | *(skip extraction)* | route to conversation init node |
| `finish_conversation` | *(skip extraction)* | route to conversation end node |
| `pause` | *(skip extraction)* | pause processing, await user signal |
| `restart` | *(skip extraction)* | reset agentState, return to entry |
| `ask_question` | *(skip extraction)* | route directly to Q&A node |
| `provide_information` | `ProvideInformationIntentPayload` | `field_values: dict[str, Any]` |
| `repeat` | *(skip extraction)* | replay last assistant message |
| `confirm` | `ConfirmIntentPayload` | `fields: dict[str, bool]` |
| `decline` | `DeclineIntentPayload` | `fields: dict[str, bool]` |
| `unrecognized_intent` | *(skip extraction)* | route to clarification node |
| `correction` | `CorrectionIntentPayload` | `corrected_fields: dict[str, Any]` |
| `ambiguous_request` | `AmbiguousRequestPayload` | `possible_intents: str[]`, requires user disambiguation |
| `out_of_scope` | *(skip extraction)* | route to out-of-scope response node |
| `help` | *(skip extraction)* | route to help/capabilities node |
| `chitchat` | *(skip extraction)* | route to chitchat response node |
| `complaint` | `ComplaintIntentPayload` | `subject: str, details: str` |
| `escalate` | `EscalateIntentPayload` | `reason: str, urgency: str` |

#### Custom Intents (per-workflow)

| Intent | Payload Class | Extraction / Routing |
|--------|--------------|---------------------|
| `<domain_intent>` | `<DomainIntentPayload>` | `field_values: dict[str, Any]` |

Custom intents follow the same pattern as `provide_information` — entity extraction populates a domain-specific payload consumed by the downstream workflow node. The payload class is derived from the intent name (e.g., `get_quote` → `GetQuoteIntentPayload`). Complex intents may skip extraction on the first turn and defer to multi-turn slot-filling.

> **Example — Home Insurance:** `get_quote` → `GetQuoteIntentPayload` (`field_values`), `file_claim` → `FileClaimIntentPayload` (`field_values`), `check_coverage` → `CheckCoverageIntentPayload` (`field_values`).

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
