# Extraction Layer Specification

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Entity extraction, validation, and transformation within Layer 1 (UNDERSTAND).
> **This spec defines interfaces and alternative implementation strategies — not a single solution.**

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial extraction layer spec: Extract/Validate/Transform pipeline |
| 2026-06-17 | 0.2.0 | Refactor to interface-first: each interface with 2+ implementation options |
| 2026-06-17 | 0.3.0 | Replace Python code blocks with YAML schemas; add errorNode cross-reference in Sections 2.2 & 2.3; add LLM JSON guardrail note in Section 3.2; add agentState.phase to StateContext in Section 3.3 |
| 2026-06-17 | 0.4.0 | Section 2.3: add explicit LLM +1 extra retry rule for extract/transform nodes; fix Chinese text on line 35; Section 4.2 Option B: replace Python expressions with declarative predicate descriptions |
| 2026-06-18 | 0.6.0 | Add §2.6 Per-State Extraction Scope: three-pass algorithm (targeted extraction → global history scan → user confirmation); scope resolved from domain model x-state-bindings; pass 1 uses state scope only, pass 2 scans all preceding states' fields, pass 3 requires user confirmation before merging | |

---

## 1. Role

Extraction answers: *"What specific data does the user provide?"*

Intent classification determines *what the user wants to do* (e.g., `get_quote`). Extraction pulls the structured data from the utterance — property type, address, coverage amount — and validates it before handing it to Layer 2 (DECIDE).

Extraction is the second half of Layer 1 (UNDERSTAND):

```
User Input
   |
   v
+------------------------------------+
| Layer 1: UNDERSTAND                |
|                                    |
|  Intent Classification (already designed) |
|       ↓                            |
|  Entity Extraction (this document)  |
|       Extract → Validate ← Transform|
+------------------------------------+
            |
            v
      Layer 2: DECIDE
```

## 2. Core Pipeline

### 2.1 Three Interfaces

The extraction pipeline consists of three node interfaces. Each interface defines a contract; the implementation is chosen per deployment.

| Interface | Responsibility |
|-----------|----------------|
| **Extract** | Pull raw entities from user utterance |
| **Validate** | Check entities against rules; produce pass/fail + errors |
| **Transform** | Type coercion, normalization, data completion/correction |

### 2.2 Flow

```
User Input ──→ [Extract] ──→ entities_raw
                  │
                  ↓
             [Validate] ──(all pass)──→ emit result to Layer 2
                  │
               (fail)
                  │
                  ↓
             [Transform] ──(success)──→ loop back to [Validate]
                  │
               (fail: max attempts exhausted or unrecoverable error)
                  │
                  ↓
             on_transform_failure node → ultimately routes to errorNode (see Routing & Execution spec Section 6)
```

### 2.3 Retry Gating

Each extraction node declares `max_transform_attempts` (default: 2). The Validate→Transform→Validate loop runs up to that limit. **LLM-based extraction and transform nodes receive +1 extra retry beyond `max_transform_attempts`** (to compensate for LLM non-determinism), matching the framework-wide rule that all LLM nodes get +1 retry. Non-LLM nodes retry exactly `max_transform_attempts` times. On the final attempt, if Validate still fails, the pipeline routes to the configured `on_transform_failure` node, which ultimately routes to `errorNode` (see Routing & Execution spec Section 6).

### 2.4 Graph Topology

The three interfaces are **independent nodes** in the LangGraph — not a hidden macro-node.

```yaml
nodes:
  - {step}_extract
  - {step}_validate
  - {step}_transform
  - {next_step}
  - {on_failure}

edges:
  {step}_extract    → {step}_validate
  {step}_validate   → {next_step}              (all rules pass)
  {step}_validate   → {step}_transform         (any rule fails)
  {step}_transform  → {step}_validate           (transform succeeded)
  {step}_transform  → {on_failure}              (transform failed)
```

### 2.5 Interface Definition

The framework exposes nodes through a strategy-based factory pattern. Each extraction node (extract / validate / transform) conforms to a shared contract:

```yaml
# Extraction Node Protocol (interface contract)
# Each node receives the full GraphState, returns updated GraphState.
# Nodes are stateless — all context lives in the state graph.
extraction_node_protocol:
  signature: (GraphState) → GraphState
  description: >
    Execute this node against the current LangGraph state.
    The node reads from and writes to the state graph.
    No side effects outside of state mutation.
```

The framework wires nodes into the graph via a factory configured per-node in YAML:

```yaml
# ExtractionFactory configuration (per-node in workflow YAML)
extraction_factory:
  # Strategy selection drives which implementation is instantiated
  extract_strategy: hybrid        # llm_primary | deterministic | hybrid
  validate_strategy: native       # durable_rules | business_rules | pyknow | native | pydantic
  transform_strategy: deterministic  # deterministic | llm_assisted | hybrid

  # Each factory method signature:
  #   create_extract(strategy: string, config: dict) → ExtractionNode
  #   create_validate(strategy: string, config: dict) → ExtractionNode
  #   create_transform(strategy: string, config: dict) → ExtractionNode
  #
  # The factory reads the strategy name and instantiates the corresponding
  # implementation class, passing the YAML `config` as constructor arguments.
```

### 2.6 Per-State Extraction Scope

The Extract node operates on a **per-state scope** — not the full domain model. The framework constructs the extraction scope from the domain model's `x-state-bindings`:

**Scope resolution:**

```
agentState.phase = "collect_property_address"
       │
       ▼
x-state-bindings[collect_property_address]:
  entity: HomeInsurance
  fields: [home_address]                     ← only this sub-schema
       │
       ▼
framework resolves $ref:
  home_address → #/components/schemas/Address
       │
       ▼
LLM receives ONLY Address schema:
  { street, city, province, postal_code, country }
  5 fields, not 30+
```

**Why not the full HomeInsurance schema (all 30+ fields):**

| Approach | Tokens | Accuracy | Risk |
|----------|--------|----------|------|
| Full schema (all entities) | High | Low | LLM maps "Toronto" to email, phone to postal_code |
| Per-state scope (only address fields) | Low | High | LLM knows exactly 5 fields to extract, no confusion |

**Three-pass extraction algorithm:**

The Extract node processes each user message in three stages:

```
Pass 1: Targeted extraction (current state scope)
  Input: user message + scope schema (e.g., Address only)
  Output: { extracted fields matching current scope }
  Strategy: LLM extracts only fields in scope; ignores everything else

Pass 2: Global lookup (historical scan)
  Trigger: any required field still null after Pass 1
  Input: full conversation history + ALL fields defined in x-state-bindings
         for ALL states that precede this one in the phase sequence
  Output: { candidate_fields } — fields found in history but not yet captured
  Strategy: scan agentState.messages for candidate matches using LLM
            with a relaxed schema that accepts partial/fuzzy matches

Pass 3: Confirmation prompt (user verification)
  Trigger: candidate_fields is non-empty after Pass 2
  Input: candidate_fields + current scope
  Output: confirmed_fields (user confirms) or rejected (user corrects)
  Strategy: LLM generates a natural confirmation message:
    "I noticed you mentioned your phone is 647-555-1234 earlier.
     Is that correct?"
  → user confirms → framework merges into collectedFields
  → user corrects → framework re-extracts with correction
```

**Data flow through passes:**

```
User: "I live at 123 Main St"                  ← Pass 1 scope: address only
  → Pass 1: { street: "123 Main St" }          ← extracted, merged
  → city, province, postal_code still null      ← incomplete

User: "Toronto, ON M5V 2H1"                    ← Pass 1 scope: address only
  → Pass 1: { city: "Toronto", province: "ON", postal_code: "M5V 2H1" }
  → Pass 2: skip (all required fields filled)

State advances → collect_policyholder_info
  Scope: { first_name, last_name, email, phone }

User: "my email is alice@example.com"           ← Pass 1 scope: user info
  → Pass 1: { email: "alice@example.com" }
  → first_name, last_name, phone still null

  → Pass 2: scan history → finds "my name is Alice" from 3 turns ago
  → candidate: { first_name: "Alice" }

  → Pass 3: framework generates:
    "I noticed you mentioned your name is 'Alice' earlier.
     Is that your first name?"
  → user confirms → { first_name: "Alice" } merged
```

**Design decisions:**

| Decision | Rationale |
|----------|-----------|
| Pass 1 uses only current state scope | Prevents cross-field confusion; minimal tokens |
| Pass 2 scans full history with relaxed schema | Recovers data user gave in wrong state |
| Pass 3 requires user confirmation | Never silently accept guessed data; deterministic safety |
| Pass 2 scope = ALL preceding states' fields | Users can mention any earlier-state field; don't lose data |
| Pass 2 scope ≠ future states' fields | Don't extract fields from states the user hasn't reached yet |

Thus the Extract node is not a single LLM call — it is a **three-pass orchestration** driven by the per-state scope defined in the domain model's `x-state-bindings`.

---

## 3. Extract Interface

### 3.1 Contract

```
Input:
  user_input:           string              // raw user utterance
  conversation_context: ContextWindow        // last N messages
  intent_payloads:      ClassifiedIntent[]    // from intent classification (Section 4 of intent spec)
  extraction_rules:     ExtractionRuleSchema[] // what fields to look for
  state_context:        StateContext          // FSM state name + hint

Output:
  result: ExtractionResult  // msg_id + typed payloads per intent
```

```
ExtractionResult {
  msg_id:   string                      // unique per message (auto-generated on receipt)
  payloads: ExtractedIntentPayload[]    // one per resolved intent; may be empty for skip-intents
}
```

The Extract node receives the `ClassifiedIntent[]` from the classifier and produces typed `ExtractedIntentPayload` subclasses. Each intent maps to its corresponding payload class via `INTENT_PAYLOAD_MAP` (see Section 3.7).

### 3.2 Implementation Options

#### Option A: LLM with Structured Output (Recommended)

Use LLM with structured output (JSON mode / function calling) to extract all fields at once. Relies on the LLM's natural language understanding to handle varied phrasings, multi-turn context, and implicit references.

| Aspect | Detail |
|--------|--------|
| Strengths | Handles varied phrasings; understands implicit references; multi-turn aware |
| Weaknesses | LLM cost/latency; non-deterministic; can hallucinate values |
| Best for | Open-ended forms, free-text fields, ambiguous inputs |
| Dependencies | LLM provider (OpenAI, Anthropic, local) |
| Fallback | On LLM failure → return partial results with lower confidence |

**Prompt construction:**
- System prompt: `extraction_rules` descriptions + `state_context.state_hint`
- Context: last N messages from `conversation_context`
- Output format: JSON with field_name → value, plus `reasoning`
- Temperature: 0
- **Guardrail**: All LLM-based extraction output is JSON. The framework enforces output validation guardrails (schema check, field presence, type coercion) before the result enters the extraction pipeline.

### 3.3 State-Aware Prompting

Regardless of implementation option, the Extract node receives `StateContext`:

```
StateContext {
  state_name:        string    // e.g., "collect_property_info"
  state_description: string    // what this state expects
  state_hint:        string    // disambiguation instruction from node metadata
  required_fields:   string[]  // list of field names
  phase:             string    // current agentState.phase (e.g., "collecting", "validating", "confirming")
}
```

Options B and C use state context to scope the fallback rules. Option A injects it into the LLM prompt.

### 3.4 Comparison Matrix

| Dimension | Option A (LLM-Primary) | Option B (Deterministic) | Option C (Hybrid) |
|-----------|----------------------|--------------------------|-------------------|
| Cost | $$$ (per-call LLM) | $ (free) | $$ (LLM + compute) |
| Latency | ~1-3s | <1ms | ~1-3s |
| Determinism | Low | High | Medium |
| Accuracy on free text | High | Low | High |
| Accuracy on structured fields | Medium | High | High |
| Maintenance | Prompt tuning | Regex maintenance | Both |
| Auditability | Partial (LLM reasoning) | Full | Partial |
| Deployment complexity | Low (LLM SDK) | Minimal (stdlib) | Medium |

### 3.5 ExtractedIntentPayload Schema

Every extract call produces an `ExtractionResult` containing typed `ExtractedIntentPayload` objects. Each intent maps to a subclass.

**Base class (Python dataclass):**

```python
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

@dataclass
class ExtractedIntentPayload:
    msg_id: str = field(default_factory=lambda: uuid4().hex)
    intent: str = ""
    confidence: float = 0.0
```

**Payload subclasses:**

```python
@dataclass
class ConfirmIntentPayload(ExtractedIntentPayload):
    fields: dict[str, bool] = field(default_factory=dict)

@dataclass
class DeclineIntentPayload(ExtractedIntentPayload):
    fields: dict[str, bool] = field(default_factory=dict)

@dataclass
class ProvideInformationIntentPayload(ExtractedIntentPayload):
    field_values: dict[str, Any] = field(default_factory=dict)

@dataclass
class GetQuoteIntentPayload(ExtractedIntentPayload):
    field_values: dict[str, Any] = field(default_factory=dict)

@dataclass
class FileClaimIntentPayload(ExtractedIntentPayload):
    field_values: dict[str, Any] = field(default_factory=dict)
```

**ExtractionResult wrapper:**

```python
@dataclass
class ExtractionResult:
    msg_id: str
    payloads: list[ExtractedIntentPayload]
```

| Payload Class | Intent | Data Shape |
|--------------|--------|------------|
| `ConfirmIntentPayload` | `confirm` | `fields: dict[str, bool]` |
| `DeclineIntentPayload` | `decline` | `fields: dict[str, bool]` |
| `ProvideInformationIntentPayload` | `provide_information` | `field_values: dict[str, Any]` |
| `GetQuoteIntentPayload` | `get_quote` | `field_values: dict[str, Any]` |
| `FileClaimIntentPayload` | `file_claim` | `field_values: dict[str, Any]` |

Intents `ask_question` and `unrecognized_intent` skip extraction entirely and route directly to their respective Layer 3 nodes.

### 3.6 Payload Guardrail Validation

After the Extract node produces payloads, a guardrail validates each `field_values` or `fields` entry before handing off to the Validate node:

1. **Field name existence check** — every key must map to an actual field in the `AgentState` dataclass. This is analogous to Jackson `ObjectMapper` validating JSON keys against a POJO. The validation uses a whitelist derived from `AgentState.__dataclass_fields__`:

```python
VALID_AGENT_FIELDS: set[str] = {
    "policy_type", "property_type", "address", "postal_code",
    "building_age", "floor_area", "coverage_amount", "phone",
    "claim_type", "claim_description", ...
}

def validate_payload_fields(payload: ExtractedIntentPayload):
    data = getattr(payload, "fields", None) or getattr(payload, "field_values", {})
    for field_name, value in data.items():
        if field_name not in VALID_AGENT_FIELDS:
            raise GuardrailError(f"Unknown field '{field_name}' — not found in AgentState")
        if value is None or value == "":
            raise GuardrailError(f"Empty value for field '{field_name}'")
```

2. **Non-empty value check** — no field value may be `None`, `""`, or for boolean payloads, `False` is also treated as empty.

### 3.7 Intent → Payload Factory

The framework uses a dispatch map to instantiate the correct payload class for each intent:

```python
INTENT_PAYLOAD_MAP = {
    "confirm":              ConfirmIntentPayload,
    "decline":              DeclineIntentPayload,
    "provide_information":  ProvideInformationIntentPayload,
    "get_quote":            GetQuoteIntentPayload,
    "file_claim":           FileClaimIntentPayload,
}

def build_extraction_result(msg_id: str, intent_payloads: list) -> ExtractionResult:
    payloads = []
    for ip in intent_payloads:
        cls = INTENT_PAYLOAD_MAP.get(ip.intent)
        if cls is None:
            continue  # skip intents with no extraction (ask_question, unrecognized)
        payload = cls(msg_id=msg_id, intent=ip.intent, confidence=ip.confidence)
        payloads.append(payload)
    return ExtractionResult(msg_id=msg_id, payloads=payloads)
```

The LLM prompt must guide extraction so that:
1. Each intent in the input produces one `ExtractedIntentPayload`
2. Data fields belonging to different intents are placed in separate payloads
3. Multi-intent messages produce multiple payloads in a single `ExtractionResult`

**Multi-intent example:**

> User: "I want to file a claim, my phone is 123-456-7890"

```json
{
  "msg_id": "a1b2c3d4",
  "payloads": [
    {
      "intent": "file_claim",
      "confidence": 0.95,
      "field_values": {}
    },
    {
      "intent": "provide_information",
      "confidence": 0.88,
      "field_values": {"phone": "123-456-7890"}
    }
  ]
}
```

**Intent combination validation** (cross-reference): Before extraction proceeds, the intent classifier validates that incompatible complex intents are not combined in a single message (see Intent Classification spec Section 4.3).

---

## 4. Validate Interface

### 4.1 Contract

```
Input:
  entities:         Map<string, any>     // values from Extract (strings) or Transform (typed)
  validation_rules: ValidationRuleSchema[] // per-field rules from node metadata

Output:
  passed:       boolean       // true if ALL rules pass
  field_errors: FieldError[]  // list of failures
```

```
FieldError {
  field:   string    // which field failed
  rule:    string    // which rule failed (e.g., "required", "type", "regex")
  message: string    // human-readable error
  value:   any       // the value that failed (for audit)
}
```

### 4.2 Rule Types (Declarative Schema)

These rule types are defined in the YAML declaration (Section 6) and are engine-agnostic. Each implementation option interprets the same schema.

| Rule | Signature | Description |
|------|-----------|-------------|
| `required` | `{ required: true }` | Field must be non-null and non-empty |
| `type` | `{ type: "int" \| "float" \| "string" \| "date" \| "boolean" \| "enum" }` | Value must match the given type |
| `enum` | `{ enum: [val1, val2, ...] }` | Value must be one of the listed options |
| `range` | `{ range: { min?: number, max?: number } }` | Numeric value within range |
| `regex` | `{ regex: "pattern" }` | String value must match pattern |
| `length` | `{ length: { min?: int, max?: int } }` | String length bounds |
| `custom` | `{ custom: "function_name" }` | User-provided validation function |

### 4.3 Implementation Options

#### Option A: Rule Engine — Forward Chaining (durable_rules / business-rules / pyknow)

Compile declarative YAML rules into a rule engine's native format. Execute as a forward-chaining ruleset against entity facts.

| Engine | Package | Best for |
|--------|---------|----------|
| `durable_rules` | `pip install durable-rules` | Forward-chaining, cross-field rules, when/then inference |
| `business_rules` | `pip install business-rules` | Lightweight, JSON/YAML-native, simple per-field rules |
| `pyknow` | `pip install pyknow` | Expert system with Fact/KnowledgeEngine model |

| Aspect | Detail |
|--------|--------|
| Strengths | Cross-field rules; state-dependent rules; rule composition |
| Weaknesses | Additional dependency; learning curve |
| Best for | Complex validation with field interdependencies |
| Configuration | `rule_engine: durable_rules` in node metadata |

### 4.4 Comparison Matrix

| Dimension | Option A (Rule Engine) | Option B (Predicate) | Option C (Pydantic) |
|-----------|----------------------|---------------------|---------------------|
| Cross-field rules | Yes (when/then) | No (manual) | Yes (root_validator) |
| State-dependent rules | Yes | No | No |
| External deps | 1 pip package | 0 | 1 pip package |
| Schema in YAML | Yes | Yes | No (code-only) |
| Dynamic schemas | Yes | Yes | Limited |
| Learning curve | Medium | Low | Low |
| Inference speed | Medium | Fast | Fast |

---

## 5. Transform Interface

### 5.1 Contract

```
Input:
  entities:          Map<string, string>  // raw values from Extract
  validation_errors: FieldError[]         // which fields failed validation
  transform_rules:   TransformRuleSchema[] // per-field transform rules

Output:
  entities:         Map<string, any>     // transformed values
  success:          boolean              // false if any field is unrecoverable
  transform_errors: TransformError[]     // unrecoverable errors
```

### 5.2 Transform Operation Types

| Operation | Description | Example |
|-----------|-------------|---------|
| `cast` | Type coercion | `"12/27" → Date(2027-12-01)` |
| `normalize` | String cleaning | `trim`, `lowercase`, `strip_symbols` |
| `parse` | Named parser | `parse_date`, `parse_currency`, `parse_phone` |
| `lookup` | Value mapping | `"BJ" → "Beijing"` |
| `default` | Fallback value when null | `null → 0.0` |
| `llm_correct` | LLM-assisted correction of near-valid values | `"Nisaan" → "Nissan"` |
| `llm_complete` | LLM-assisted inference of missing fields | infer postal code from address |
| `external` | Call external API/service | postal code → city lookup |

### 5.3 Implementation Options

#### Option A: Declarative Rule Pipeline

Transform rules execute as an ordered pipeline per field. Purely deterministic (no LLM). Operations `cast`, `normalize`, `parse`, `lookup`, `default`, `external`.

| Aspect | Detail |
|--------|--------|
| Strengths | Deterministic; auditable; no LLM cost |
| Weaknesses | Cannot handle ambiguous or implicit data |
| Best for | Type coercion, normalization, lookup tables |
| Dependencies | None (or external API for `external` operations) |

---

## 6. Node Metadata Schema

Each extraction node in the YAML carries its own `extraction_rules`, `validation_rules`, and `transform_rules`. These schemas are the **interface contract** consumed by all implementation options.

### 6.1 Extraction Rule Schema

```
ExtractionRuleSchema {
  field:              string              // field name
  description:        string              // guides LLM extraction
  type:               string              // expected type after transform
  required:           boolean             // triggers validation if null
  fallback_pattern?:  string              // regex for deterministic fallback
  fallback_keywords?: string[]            // keyword-triggered fallback
  examples?:          string[]            // few-shot examples for LLM prompt
}
```

### 6.2 Validation Rule Schema

```
ValidationRuleSchema {
  field:     string                // field name
  required?: boolean
  type?:     "int" | "float" | "string" | "date" | "boolean" | "enum"
  enum?:     string[]
  range?:    { min?: number, max?: number }
  regex?:    string
  length?:   { min?: int, max?: int }
  custom?:   string                // registered function name
}
```

### 6.3 Transform Rule Schema

```
TransformRuleSchema {
  field:  string              // field name
  rules:  TransformOperation[] // ordered list of operations
}

TransformOperation {
  type:   "cast" | "normalize" | "parse" | "lookup" | "default" | "llm_correct" | "llm_complete" | "external"
  config: Record<string, any>  // type-specific configuration
}
```

### 6.4 Full Node Example (YAML)

```yaml
extraction_nodes:
  collect_property_info_extract:
    extract_strategy: hybrid      # Option A: llm_primary | Option B: deterministic | Option C: hybrid
    validate_strategy: durable_rules  # Option A: durable_rules | business_rules | pyknow
                                      # Option B: native | Option C: pydantic
    transform_strategy: hybrid    # Option A: deterministic | Option B: llm_assisted | Option C: hybrid
    state_hint: >
      The user is providing property information for a home insurance quote.
      Address may include street, city, province, postal code.
      Building age is in years.
    context_window_size: 6
    max_transform_attempts: 2
    on_transform_failure: ask_missing_property_info

    extraction_rules:
      - field: property_type
        description: "Type of property (apartment, house, villa)"
        type: enum
        required: true
        fallback_keywords: [apartment, house, villa, condo, flat]
        examples: ["I live in a house", "a 3-bedroom apartment"]
      - field: postal_code
        description: "6-digit postal code"
        type: string
        required: true
        fallback_pattern: "\\b[0-9]{6}\\b"
      - field: building_age
        description: "Age of the building in years"
        type: int
        required: true
        examples: ["built in 2010", "15 years old"]
      - field: floor_area
        description: "Floor area in square meters"
        type: float
        required: false
        fallback_pattern: "\\b([0-9]+(?:\\.[0-9]+)?)\\s*(?:sqm|m2|square\\s*meters?)"

    validation_rules:
      property_type:
        required: true
        enum: [apartment, house, villa]
      postal_code:
        required: true
        regex: "^[0-9]{6}$"
      building_age:
        required: true
        type: int
        range: { min: 0, max: 200 }
      floor_area:
        type: float
        range: { min: 1, max: 100000 }

    transform_rules:
      property_type:
        - type: normalize
          config: { op: lowercase }
        - type: lookup
          config:
            mapping:
              condo: apartment
              flat: apartment
              "single family": house
      building_age:
        - type: cast
          config: { to: int }
        - type: llm_correct
          config:
            prompt: >
              Convert building age to integer years. "built in 2010" → current_year - 2010.
              "new" → 0. Current value: {value}
      floor_area:
        - type: cast
          config: { to: float }
```

### 6.5 Strategy Configuration Reference

```yaml
# Node-level strategy selection
extract_strategy:    llm_primary | deterministic | hybrid
validate_strategy:   durable_rules | business_rules | pyknow | native | pydantic
transform_strategy:  deterministic | llm_assisted | hybrid

# If rule engine selected, which one
rule_engine:   durable_rules | business_rules | pyknow   # only when validate_strategy = one of these

# Custom implementation
custom_engine:   my_package.MyEngine                      # user-provided RuleEngine implementation
```

---

## 7. Integration with Intent Classification

### 7.1 Layer 1 Data Flow

```
User Input
   |
   v
[Intent Classification]  →  ClassificationResult { intents: ClassifiedIntent[] }
   |
   v
[Intent Combination Validate]  →  rejects multiple complex intents (see Intent spec 4.3)
   |
   v
[State Machine]           →  determines which extraction node to activate
   |
   v
[Extract]                 →  ExtractionResult { msg_id, payloads: ExtractedIntentPayload[] }
   |                          (each intent → typed payload via INTENT_PAYLOAD_MAP)
   v
[Payload Guardrail]       →  fieldName existence check + non-empty check (Section 3.6)
   |
   v
[Validate]                →  entities_validated OR field_errors
   |
   v
[Transform] (conditional) →  entities_transformed (loop back to Validate)
   |
   v
Layer 2: DECIDE
```

### 7.2 Intent → Extraction Routing

1. **Intent gates the extraction node**: The state machine uses the primary intent label to select which extraction node to activate. `get_quote` routes to `collect_property_info_extract`; `file_claim` routes to `file_claim_extract`.

2. **Intent may skip extraction**: If the intent is `unrecognized_intent` or `ask_question`, extraction skips entirely and routes directly to a clarification or Q&A node.

3. **Multi-intent per message**: A single user message may carry multiple intents (e.g., `file_claim` + `provide_information`). The Extract node produces one `ExtractedIntentPayload` per intent. Simple intents (non-`complex`) may be combined freely; multiple complex intents in one message are rejected by the combination validator before extraction begins.

### 7.3 Design Decision: Why Separate Classify and Extract

**Decision:** Intent classification and entity extraction are separate nodes (two-stage), not a single combined LLM call.

**Rationale — accuracy over latency:**

| Metric | Two-Stage (separate) | Single-Stage (combined) |
|--------|---------------------|------------------------|
| **Accuracy** | High — each extract prompt only contains the schema for the matched intent(s) | Low — single prompt must include ALL intents' ALL field schemas, leading to cross-schema field confusion |
| **Cost** | 2x LLM calls | 1x LLM call |
| **Latency** | ~2x of single call | ~1x |

**Why accuracy wins:**

The extraction prompt must include field descriptions, validation rules, and few-shot examples for every field. In a combined call, the LLM faces the union of all schemas:

- `get_quote` has fields `{property_type, address, postal_code, building_age, floor_area}`
- `file_claim` has fields `{claim_type, damage_description, incident_date, incident_location}`
- `update_policy` has fields `{policy_number, coverage_amount, effective_date}`

A combined prompt containing all 3 schemas (~12+ fields) causes the LLM to:
1. Confuse field boundaries — extract `damage_description` into a `get_quote` payload
2. Miss narrow-schema fields amidst the noise
3. Produce ambiguous output for overlapping concept names ("address" could be property or incident)

Two stages eliminate this: classify first to scope the schema, extract with only that schema. Accuracy is the non-negotiable dimension — one wrong field can route the entire Layer 2 workflow incorrectly. The cost of an extra LLM call is negligible compared to the cost of a business-logic error.

**Future:** For small deployments with <5 intents and few fields, a `classify_and_extract_combined: true` configuration option may be added, but it is not the default.

---

## 8. Pattern: Two-Stage Extraction (Type-First)

For scenarios where the extraction schema depends on a prior decision (e.g., auto vs home insurance):

```
Stage 1:
  [Extract(type_classifier)] → [Validate] → state_machine selects extraction schema

Stage 2:
  [Extract(type_specific_fields)] → [Validate] → [Transform] → [Validate]
```

This mirrors the zelkim two-phase dynamic schema pattern. Stage 1 uses a minimal extraction schema (type only). Stage 2 uses the schema scoped to the classified type.

Each stage is an independent extract/validate/transform pipeline with its own strategy configuration.

---

## 9. Edge Cases

### 9.1 Partial Extraction

Extract returns some but not all required fields → Validate catches missing fields → Transform's `llm_complete` (Option B/C) may infer them. If unrecoverable → `on_transform_failure`.

### 9.2 Extraneous Information

User provides information for fields the current node does not request. Extract may still capture them. The framework stores extra data in the state graph for potential use by downstream nodes.

### 9.3 Field Value Correction Mid-Workflow

User corrects a previously filled field ("Wait, the address is not X, it's Y"). Conversation context in Extract captures the new value. The accumulated `collectedFields` is overwritten.

### 9.4 Ambiguous Values

When a raw value could map to multiple valid options (e.g., "basic" = `coverage_level` or `deductible`), the `state_hint` disambiguates. If ambiguity persists, Validate reports error → Transform corrects or fail node clarifies.

---

## 10. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should Transform maintain its own retry budget separate from `max_transform_attempts` for LLM-based operations? | Cost control |
| 2 | Should extraction results be cached per conversation turn to avoid re-extraction on replay/recovery? | Determinism, cost |
| 3 | For `llm_complete`, what's the acceptable inference boundary? Should it call external APIs to fill gaps? | Data accuracy, latency |
| 4 | Cross-field validation (e.g., `end_date > start_date`) — expressed in YAML schema or only via rule engine? | Rule expressiveness |
| 5 | Should the extracted + validated entities be persisted before Layer 2 consumes them? | Auditability, replay |
| 6 | LLM provider unavailable mid-extraction — fall back to Option B (deterministic) or queue? | Availability |
| 7 | Should the `ExtractionFactory` support fallback chains? (e.g., try Option C → if LLM timeout, fall back to Option B) | Resilience |

---

## 11. LLM Audit Record

Every LLM call within the extraction pipeline (and across the framework) produces an audit record. These records serve two purposes: (a) operational traceability — the raw input/output of every LLM interaction is persisted for debugging and compliance; (b) training data — accumulated records form a dataset for fine-tuning or eval improvement.

### 11.1 Audit Record Schema

```python
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class LLMAuditRecord:
    msg_id: str                  # from ExtractionResult.msg_id
    intent: str                  # which intent triggered this LLM call
    node: str                    # node name: extract / validate_llm / transform_llm / classify
    raw_input: str               # raw user message or serialized input payload
    llm_output: str              # raw JSON string returned by LLM
    parsed_result: dict          # JSON-parsed structured output
    timestamp: str               # ISO 8601 UTC
    model: str                   # e.g., "gpt-4o", "claude-sonnet-4"
    tokens_used: int             # total tokens consumed
```

### 11.2 Audit Flow

```
User Message
    │
    ├── msg_id generated (uuid4().hex)
    │
    ▼
[Intent Classification] ──(LLM call)──→ record to llm_audit
    │
    ▼
[Extract] ──(LLM call, per payload)──→ record to llm_audit
    │
    ▼
[Transform llm_correct/llm_complete] ──(LLM call)──→ record to llm_audit
```

Each LLM interaction is audited independently — one classification call + one extraction call per payload + any transform LLM calls all produce separate audit records under the same `msg_id`.

### 11.3 Storage

Audit records are persisted to the `llm_audit` table (or equivalent collection). The table is append-only and indexed by `msg_id` and `timestamp`.

| Field | Indexed | Purpose |
|-------|---------|---------|
| `msg_id` | Yes | Trace all LLM calls for a message |
| `timestamp` | Yes | Time-range queries |
| `intent` | Yes | Filter by intent type |
| `node` | Yes | Filter by pipeline stage |
| `raw_input` | No (blob) | Debugging, training data |
| `llm_output` | No (blob) | Debugging, training data |

### 11.4 Training Data Generation

The accumulated audit records serve as a labeled dataset:
- `raw_input` → user utterance
- `llm_output` → expected structured output (validated through guardrails)
- `intent` + `node` → task label

Periodic exports from `llm_audit` can feed into model fine-tuning pipelines or eval suite construction.

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent architecture document
- [Intent Classification Design](./2026-06-16-intent-classification-design.md) — Layer 1 intent classification
- [State Machine Design](./2026-06-16-state-machine-design.md) — state context injection, intent+state resolution
- [Home Insurance Workflow](../../examples/home-insurance/workflow.yaml) — reference extraction rules
- zelkim/langgraph-insurance-chatbot — two-phase dynamic schema + LLM-structured-output pattern
- Prodigal Payment Collection Agent — hybrid LLM + per-slot regex fallback pattern
