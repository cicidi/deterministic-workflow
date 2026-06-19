# Domain Model Specification

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Domain model as the single source of truth for entities, states, and transitions.
> **This spec defines schemas and interfaces — not a single solution.**

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial domain model spec: Entity + State + Transition schema |
| 2026-06-17 | 0.2.0 | Add implementation options (flat vs nested vs code-first); agentState.phase mapping; errorNode as standard transition target |
| 2026-06-17 | 0.3.0 | Add Section 1.1: Implementation Approaches (Flat YAML vs Nested/Hierarchical vs Code-First) |
| 2026-06-18 | 0.5.0 | Adopt OpenAPI 3.1 Schema as the data model definition standard; replace custom FieldDef format with JSON Schema; add HomeInsurance/UserInfo/Address/QuoteRequest/QuoteResponse examples; add downstream API schema patterns | |

---

## 1. Role

The Domain Model is the **single source of truth** for a deterministic workflow. It defines *what* the workflow operates on — data entities, valid states, and transition rules — independent of *how* the framework executes extraction, validation, or routing.

```
Domain Model (WHAT)               Workflow Config (HOW)
────────────────────────          ──────────────────────
Entities + fields + types         extraction_strategy
States + state_hint                validate_strategy
Transitions + guards              transform_strategy
                                   context_window_size
                                   max_transform_attempts
                                   on_transform_failure
```

**Separation principle:** The Domain Model is reusable across workflows and products. The workflow configuration adds runtime strategy selection on top. This separation enables:

1. **Cross-workflow reuse** — a `property_info` entity used in both `home_insurance_quote` and `home_insurance_refinance`
2. **Product-agnostic models** — same domain model across different implementations
3. **Skill-driven generation** — a downstream skill can interview a developer to fill in the domain model, then the framework provides sensible defaults for the how

### 1.1 Implementation Approaches

Three architectural options for authoring domain models. All three share the same entity/state/transition schema; they differ in *how* the entity field definitions are authored and consumed.

#### Option A: OpenAPI Schema (Recommended)

Entity fields are defined using [OpenAPI 3.1 Schema Objects](https://spec.openapis.org/oas/latest.html#schema-object) (JSON Schema dialect). The framework reads `components/schemas/` directly — no translation layer needed.

```yaml
# domain-models/home-insurance.yaml — OpenAPI components/schemas
components:
  schemas:
    Address:
      type: object
      required: [street, city, province, postal_code]
      properties:
        street:
          type: string
          minLength: 3
        city:
          type: string
        province:
          type: string
          enum: [ON, QC, BC, AB, MB, SK, NS, NB, NL, PE, NT, YT, NU]
        postal_code:
          type: string
          pattern: "^[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]$"

    UserInfo:
      type: object
      required: [first_name, last_name, email]
      properties:
        first_name: { type: string, minLength: 1 }
        last_name:  { type: string, minLength: 1 }
        email:      { type: string, format: email }
        phone:      { type: string, pattern: "^\\+?1?\\d{10}$" }
        date_of_birth: { type: string, format: date }

    HomeInsurance:
      description: "Complete home insurance application"
      type: object
      required: [owner, home_address, property_info, coverage_info]
      properties:
        owner:
          $ref: "#/components/schemas/UserInfo"
        home_address:
          $ref: "#/components/schemas/Address"
        property_info:
          $ref: "#/components/schemas/PropertyInfo"
        coverage_info:
          $ref: "#/components/schemas/CoverageInfo"

    QuoteRequest:
      description: "Downstream API request for submitting a quote"
      type: object
      required: [applicant, property, coverage, quote_id]
      properties:
        quote_id:  { type: string, format: uuid }
        applicant: { $ref: "#/components/schemas/UserInfo" }
        property:
          type: object
          required: [address, property_info]
          properties:
            address: { $ref: "#/components/schemas/Address" }
            property_info: { $ref: "#/components/schemas/PropertyInfo" }
        coverage:  { $ref: "#/components/schemas/CoverageInfo" }
        requested_at: { type: string, format: date-time }

  # Framework state bindings
  x-state-bindings:
    collect_policyholder_info:
      entity: HomeInsurance
      fields: [owner]
    collect_property_address:
      entity: HomeInsurance
      fields: [home_address]
    submit_quote:
      entity: QuoteRequest
```

**Pros:** Industry-standard format (JSON Schema). Full ecosystem: validators, code generators, IDE auto-complete for YAML/JSON. `$ref` enables schema composition without duplication. OpenAPI tooling produces interactive docs (Swagger UI). Downstream API contracts are defined in the same format as domain entities.

**Cons:** Slightly more verbose than flat YAML for simple schemas. Requires understanding of `$ref` resolution rules for nested schemas.

#### Option B: Flat YAML Domain Model

Entities are defined as flat field lists using a custom YAML dialect. Every field is a top-level key with framework-specific annotations (`deterministic_fallback`, `transform`, `examples`).

```yaml
entities:
  property_info:
    fields:
      property_type: { type: enum, values: [apartment, house, villa], required: true }
      address:       { type: string, required: true, min_length: 5 }
      postal_code:   { type: string, pattern: "^[0-9]{6}$" }
      building_age:  { type: int, range: { min: 0, max: 200 } }
```

**Pros:** Simple to read and write. LLM extraction prompts map 1:1 to field descriptions.

**Cons:** Custom format — no tooling ecosystem. No `$ref` for schema reuse. No compound field support. Framework must maintain a translation layer from custom dialect to JSON Schema for downstream consumption.

#### Option C: Code-First Pydantic Models

Entities are defined as Python Pydantic models. The YAML domain model is auto-generated.

```python
from pydantic import BaseModel, Field
from typing import Literal

class Address(BaseModel):
    street: str = Field(min_length=3)
    city: str
    province: str
    postal_code: str = Field(pattern=r"^[A-Z]\d[A-Z]\s?\d[A-Z]\d$")

class UserInfo(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: str
    phone: str | None = Field(pattern=r"^\+?1?\d{10}$")
```

**Pros:** Full IDE support. JSON Schema export built into Pydantic v2+.

**Cons:** Requires code-generation step. Non-Python developers cannot author directly.

```yaml
# Auto-generated domain model YAML
entities:
  property_info:
    fields:
      property_type: { type: enum, values: [apartment, house, villa], required: true }
      address:       { type: string, required: true, min_length: 5 }
      postal_code:   { type: string, required: true, pattern: "^\\d{6}$" }
      building_age:  { type: int, required: true, range: { min: 0, max: 200 } }
```

**Pros:** Full IDE support (autocomplete, type-checking, refactoring). Validation logic is native Python. Pydantic's built-in serialization produces structured outputs suitable for LangGraph state.

**Cons:** Requires a code-generation step. Non-Python developers cannot author or review the domain model. Generated YAML may be less readable than hand-crafted YAML.

### Comparison Matrix

| Dimension | Option A: OpenAPI Schema | Option B: Flat YAML | Option C: Code-First |
|-----------|------------------------|-------------------|----------------------|
| **Tooling Ecosystem** | High — validators, codegen, Swagger UI, IDE plugins | Low — custom parsing only | High — Pydantic ecosystem, IDE support |
| **Schema Composition** | High — `$ref` across schemas | Low — flat field lists, no reuse | High — Python inheritance + composition |
| **Compound Fields** | High — native `object` type + `$ref` | Low — flat only, no nesting | High — Pydantic nested models |
| **Human Readability** | High — standard JSON Schema, widely recognized | High — simple YAML | Low — source is Python, not YAML |
| **Industry Standard** | High — OpenAPI is an industry standard | Low — custom format | Medium — JSON Schema export available |
| **LLM Structured Output** | Direct — auto-generate JSON Schema for LLM output guardrails | Indirect — framework translates custom format | Direct — Pydantic `.model_json_schema()` |

**Default recommendation: Option A (OpenAPI Schema).** The domain model definition format is OpenAPI 3.1 Schema (JSON Schema). This provides an industry-standard, toolchain-rich foundation that serves both internal data modeling AND downstream API contracts. Option C (Code-First) is available for teams that prefer Python-native development — Pydantic v2+ can export JSON Schema for downstream consumption. Option B (Flat custom YAML) is no longer recommended for new workflows.

## 2. Domain Model Schema

A Domain Model is defined in an OpenAPI 3.1-compliant YAML file:

**Top-level structure:**

```yaml
openapi: "3.1.0"

info:
  title: <domain name>        # e.g., "Home Insurance Domain Model"
  version: <semantic version>
  description: <human-readable domain description>

components:
  schemas:                    # ⇐ entity definitions (OpenAPI Schema Objects)
    EntityName:
      type: object
      required: [field1, field2]
      properties:
        field1: { type: string, ... }
        field2:
          $ref: "#/components/schemas/OtherEntity"  # cross-reference

  x-state-bindings:           # ⇐ framework extension: maps states to entities
    state_name:
      entity: <schema_ref>    # which entity this state collects
      fields: [field1, ...]   # fields active in this state (subset)
      state_hint: <prompt>    # LLM context for extraction
```

**Framework consumes:**
- `components/schemas/` → auto-generate extraction rules, validation rules, LLM structured output schemas
- `$ref` → resolve referenced schemas, expand compound fields into flat extraction targets
- `x-state-bindings` → per-state field visibility, state-specific LLM prompts

### 2.1 File Location

```
docs/domain-models/
  home-insurance.yaml          # Primary: HomeInsurance, UserInfo, Address, QuoteRequest, etc.
```

For the complete concrete example, see [home-insurance.yaml](../../domain-models/home-insurance.yaml).

---

## 3. Entity Definition

### 3.1 EntityDef Schema

```
EntityDef {
  name:        string              // entity name (e.g., "property_info")
  description: string              // guides LLM extraction + documentation
  fields:      Map<string, FieldDef> // ordered field definitions
}
```

### 3.2 FieldDef Schema

```
FieldDef {
  type:        string              // "string" | "int" | "float" | "date" | "boolean" | "enum" | "list"
  required:    boolean             // true → null triggers validation error
  description: string              // guides LLM extraction
  values?:     string[]            // valid values (for type: enum)
  range?:      { min?: number, max?: number }  // (for type: int, float)
  pattern?:    string              // regex pattern (for type: string)
  min_length?: int                 // minimum string length
  deterministic_fallback?: {       // deterministic extraction fallback
    keywords?: string[]
    regex?:    string
    priority?: "llm_wins" | "regex_wins"
  }
  transform?:  TransformOp[]       // type coercion / normalization pipeline
  examples?:   string[]            // few-shot examples for LLM prompt
}

TransformOp {
  type:   "cast" | "normalize" | "parse" | "lookup" | "default" | "external"
  config: Record<string, any>      // type-specific configuration
}
```

### 3.3 Type System

| Type | Validation | Transform (default) |
|------|-----------|---------------------|
| `string` | non-empty if required | `trim` |
| `int` | integer, optional range | `cast: int` |
| `float` | numeric, optional range | `cast: float` |
| `date` | ISO 8601 format | `parse: date` |
| `boolean` | true/false/yes/no/1/0 | `cast: boolean` |
| `enum` | must be in `values[]` | `normalize: lowercase` + `lookup` |
| `list` | array of items | `split: ","` |

### 3.4 Example: home-insurance domain

```yaml
domain: home_insurance
version: 1.0.0
description: "Home insurance quote, claim, and policy management"

entities:
  property_info:
    description: "Property information for home insurance"
    fields:
      property_type:
        type: enum
        values: [apartment, house, villa]
        required: true
        description: "Type of property being insured"
        examples: ["I live in a house", "3-bedroom apartment", "my villa"]
        deterministic_fallback:
          keywords: [apartment, house, villa, condo, flat]
        transform:
          - type: normalize
            config: { op: lowercase }
          - type: lookup
            config:
              mapping:
                condo: apartment
                flat: apartment
                "single family": house

      address:
        type: string
        required: true
        description: "Full address including street, city, province, postal code"
        min_length: 5

      postal_code:
        type: string
        required: true
        description: "6-digit postal code"
        pattern: "^[0-9]{6}$"
        deterministic_fallback:
          regex: "\\b[0-9]{6}\\b"
          priority: regex_wins

      building_age:
        type: int
        required: true
        description: "Age of the building in years"
        range: { min: 0, max: 200 }
        examples: ["built in 2010", "15 years old", "brand new"]
        transform:
          - type: cast
            config: { to: int }

      floor_area:
        type: float
        required: false
        description: "Floor area in square meters"
        range: { min: 1, max: 100000 }
        transform:
          - type: cast
            config: { to: float }

      construction_material:
        type: enum
        values: [brick, concrete, wood_frame, steel]
        required: false
        description: "Primary construction material"

  coverage_needs:
    description: "Coverage requirements for a quote"
    fields:
      coverage_type:
        type: enum
        values: [building_only, contents_only, both]
        required: true
        description: "What type of coverage the user wants"

      building_coverage:
        type: float
        required: true
        description: "Coverage amount for building (CNY)"
        range: { min: 0 }

      contents_coverage:
        type: float
        required: false
        description: "Coverage amount for contents (CNY)"
        range: { min: 0 }

      deductible:
        type: enum
        values: [low, standard, high]
        required: true
        description: "Deductible preference"

      riders:
        type: list
        required: false
        description: "Additional rider coverage (fire, theft, water_damage, earthquake, liability)"

  claim_details:
    description: "Claim filing information"
    fields:
      incident_type:
        type: enum
        values: [fire, water_damage, theft, natural_disaster, other]
        required: true
        description: "Type of incident being claimed"

      incident_date:
        type: date
        required: true
        description: "Date the incident occurred"

      damage_description:
        type: string
        required: true
        description: "Description of the damage"

      estimated_loss:
        type: float
        required: true
        description: "Estimated loss amount (CNY)"
        range: { min: 0 }
```

---

## 4. State Definition

### 4.1 StateDef Schema

```
StateDef {
  name:         string    // state name (e.g., "collect_property_info")
  description:  string    // human-readable description of what this state expects
  entity:       string    // which entity this state extracts (references EntityDef.name)
  state_hint:   string    // disambiguation hint injected into LLM extraction prompt
  max_retries?: int       // max retries before escalating (default: from framework config)
}
```

### 4.2 State → Entity Binding

Each state binds to exactly one entity. The framework uses this binding to:

1. Generate `ExtractionRule[]` from the entity's `FieldDef[]`
2. Generate `ValidationRule[]` from field types, required flags, patterns, and ranges
3. Generate `TransformRule[]` from field `transform` declarations
4. Inject `state_hint` into the LLM prompt when extracting data in this state

### 4.3 Example

```yaml
states:
  collect_property_info:
    description: "Collect property details from the user"
    entity: property_info
    state_hint: >
      The user is providing property information for a home insurance quote.
      Address may include street, city, province, postal code.
      Building age is in years. "Brand new" or "newly built" means age 0.

  collect_coverage_needs:
    description: "Collect coverage preferences"
    entity: coverage_needs
    state_hint: >
      The user is choosing coverage type and amount.
      Deductible options: low (500 CNY), standard (2000 CNY), high (5000 CNY).

  file_claim:
    description: "File a new claim"
    entity: claim_details
    state_hint: >
      The user is reporting an incident for a claim.
      Incident type must be one of: fire, water_damage, theft, natural_disaster, other.
      Date should be in YYYY-MM-DD format.
```

### 4.4 State Name → agentState.phase Mapping

At runtime, the framework maps each `StateDef.name` to the `agentState.phase` field on the shared state object. This mapping is direct and automatic:

```
# Domain model state definition
states:
  collect_property_info:
    ...

# Runtime behavior
agentState.phase = "collect_property_info"
```

The `agentState.phase` value is used by:
- **LangGraph conditional edges** — route to the correct node based on current phase
- **Sub-workflow dispatch** — match the current phase to a sub-workflow handler
- **Audit/logging** — record which phase the conversation is in at each step
- **Resumption** — when resuming a conversation, the stored phase determines which state to re-enter

No explicit mapping configuration is needed. The framework derives the phase value from `StateDef.name` during domain model loading (step 3 of the framework consumption flow).

---

## 5. Transition Definition

### 5.1 TransitionDef Schema

```
TransitionDef {
  from:      string    // source state name
  to:        string    // target state name
  guard:     string    // guard expression (see Section 6)
  priority?: int       // higher = checked first (for conflict resolution)
  label?:    string    // optional label for documentation / conditional edge naming
}
```

### 5.2 Transition Semantics

- **Self-loop**: `from: collect_property_info, to: collect_property_info, guard: "context_incomplete"` — stay in current state until all required fields are filled
- **Advance**: `from: collect_property_info, to: assess_risk, guard: "property_type != null AND address != null AND building_age != null"` — move forward when entity fields are complete
- **Conditional branch**: multiple transitions from the same state with non-overlapping guards decide the next state

### 5.3 Conflict Resolution

When multiple transitions from the same state have guards that could both be true:

1. **Priority ordering** — higher `priority` value is checked first
2. **First-match wins** — the first guard that evaluates true determines the transition
3. **Unreachable fallback** — if all guards fail, the framework uses the `on_nomatch` transition (explicitly defined or `on_transform_failure` node)

### 5.4 Example

```yaml
transitions:
  # Quote flow
  - from: collect_property_info
    to: collect_coverage_needs
    guard: "property_type != null AND address != null AND building_age != null"
    label: "property_info_complete"
    priority: 10

  - from: collect_property_info
    to: collect_property_info
    guard: "context_incomplete"
    label: "still_collecting"
    priority: 5

  - from: collect_coverage_needs
    to: assess_risk
    guard: "coverage_type != null AND building_coverage != null"
    label: "coverage_needs_complete"

  - from: collect_coverage_needs
    to: collect_coverage_needs
    guard: "context_incomplete"

  # Claim flow
  - from: file_claim
    to: validate_claim
    guard: "incident_type != null AND incident_date != null AND estimated_loss != null"

  - from: file_claim
    to: file_claim
    guard: "context_incomplete"
```

### 5.5 Reserved Transition Target: `errorNode`

The transition target name `errorNode` is reserved for error handling. Behavior:

- **Always reachable**: Any state can transition to `errorNode` regardless of its explicit transition allowlist. No transition rule with `to: errorNode` needs to be declared in the domain model.
- **Automatic routing**: When extraction, validation, or transformation fails and retries are exhausted, the framework automatically routes the conversation to the `errorNode`.
- **Escalation path**: The `errorNode` serves as a catch-all escalation path. It can be configured per-workflow (e.g., hand off to a human agent, log the failure, terminate gracefully).
- **Do not declare**: Do not declare `errorNode` as a state in the domain model. It is a framework-level primitive, not a domain state.

```yaml
# NO need to declare this in transitions:
# transitions:
#   - from: collect_property_info
#     to: errorNode       # ← NOT needed; errorNode is always reachable
```

The `errorNode` is resolved by the framework (step 6 of the consumption flow) and injected into the LangGraph state machine alongside the domain-defined states.

---

## 6. Guard Expression Syntax

Guards are boolean expressions evaluated against the current entity state. The **authoritative guard expression syntax** — including boolean operators, comparison operators, list membership, null checks, framework-generated meta-variables, and natural language fallback — is defined in [State Machine Design §3.4 Guard Expression Syntax](./2026-06-16-state-machine-design.md).

The domain model uses guards in `TransitionDef` entries to determine which state the workflow enters next. The framework evaluates guards at runtime using the state machine's expression evaluator. For complex business rules, guards can delegate to custom guard functions or rule engines (see State Machine Design §3.4).

---

## 7. Relationship with Workflow YAML

### 7.1 Merge Strategy

At framework startup, the domain model and workflow config are merged:

```
Domain Model (entity/state/transition schemas)
         +
Workflow Config (strategy choices, runtime params)
         ↓
Framework resolves to concrete ExtractionNode / ValidateNode / TransformNode instances
```

### 7.2 What the Workflow Config Adds

| Configured By | Domain Model | Workflow Config |
|---------------|-------------|-----------------|
| Entity field schemas | ✅ | — |
| State definitions | ✅ | — |
| Transition guards | ✅ | — |
| State hints | ✅ | — |
| Extraction strategy | — | ✅ |
| Validation strategy | — | ✅ |
| Transform strategy | — | ✅ |
| Rule engine selection | — | ✅ |
| Context window size | — | ✅ |
| Max transform attempts | — | ✅ |
| On-failure routing | — | ✅ |

### 7.3 Example: Referencing a Domain Model

```yaml
# workflow_home_insurance_quote.yaml
workflow: home_insurance_quote
domain_model: home-insurance        # loads docs/domain-models/home-insurance.yaml

nodes:
  collect_property_info_extract:
    entity: property_info
    extract_strategy: hybrid
    validate_strategy: durable_rules
    transform_strategy: hybrid
    context_window_size: 6
    max_transform_attempts: 2
    on_transform_failure: ask_missing_property_info

  collect_coverage_needs_extract:
    entity: coverage_needs
    extract_strategy: hybrid
    validate_strategy: durable_rules
    transform_strategy: hybrid
    on_transform_failure: ask_missing_coverage
```

---

## 8. Cross-Workflow Reuse

A domain model is globally registered. Multiple workflows can reference it, with different strategy configurations.

```
domain-models/home-insurance.yaml
    ├── workflow_home_insurance_quote.yaml     (extract_strategy: hybrid)
    ├── workflow_home_insurance_refinance.yaml  (extract_strategy: llm_primary)
    └── workflow_home_insurance_renewal.yaml    (extract_strategy: deterministic)
```

### 8.1 Versioning

Domain models use semantic versioning. Workflows pin to a version:

```yaml
domain_model: home-insurance@1.2.0
```

Breaking changes to entity schemas (field removal, type change) require a major version bump.

### 8.2 Namespacing

When two domain models define entities with the same name, the framework disambiguates by domain prefix:

```yaml
entity: home_insurance.property_info
```

---

## 9. Framework Consumption Flow

When the framework loads a workflow that references a domain model:

```
1. Load domain model YAML → parse entities, states, transitions
2. Load workflow YAML → parse nodes, strategy configs
3. For each state → look up bound entity → expand FieldDef[] to:
   a. ExtractionRule[]  (from field name, type, description, deterministic_fallback, examples)
   b. ValidationRule[]  (from field required, type, pattern, range, min_length)
   c. TransformRule[]   (from field transform)
4. Merge with node-level overrides (context_window_size, max_transform_attempts, etc.)
5. Instantiate Extract / Validate / Transform nodes via ExtractionFactory(strategy)
6. Generate LangGraph nodes + conditional edges from transition definitions
```

### 9.1 Entity → Rules Expansion

The framework performs automatic expansion. For example, given the `property_type` field:

```yaml
# Domain model entity field
property_type:
  type: enum
  values: [apartment, house, villa]
  required: true
  description: "Type of property"
  deterministic_fallback:
    keywords: [apartment, house, villa, condo, flat]
  transform:
    - type: normalize
      config: { op: lowercase }
    - type: lookup
      config: { mapping: { condo: apartment, flat: apartment, "single family": house } }
```

The framework auto-generates:

```
ExtractionRule {
  field: "property_type"
  description: "Type of property (apartment, house, villa)"
  type: "enum"
  required: true
  fallback_keywords: ["apartment", "house", "villa", "condo", "flat"]
}

ValidationRule {
  field: "property_type"
  required: true
  enum: ["apartment", "house", "villa"]
}

TransformRule {
  field: "property_type"
  rules: [
    { type: "normalize", config: { op: "lowercase" } },
    { type: "lookup", config: { mapping: { condo: "apartment", flat: "apartment", "single family": "house" } } }
  ]
}
```

---

## 10. Edge Cases

### 10.1 Optional vs. Required Fields

Fields marked `required: false` are extracted and validated if present, but `context_complete` evaluates true even if they are null. Optional fields do not block state transition.

### 10.2 Cross-Entity Data

When a state collects `coverage_needs` but the transition guard references a field from `property_info` (collected in a previous state), the framework evaluates the guard against the accumulated `collectedFields` across all entities. This enables guards like `"building_age > 10 AND building_coverage > 500000"`.

### 10.3 Dynamic Entity Selection

For scenarios where the entity schema depends on a prior decision (e.g., auto vs home insurance), use two-stage domain models:

```yaml
# Stage 1 entity
insurance_type:
  fields:
    product_type:
      type: enum
      values: [auto, home, life]
      required: true

# Stage 2 — dynamic entity binding
states:
  classify_product:
    entity: insurance_type  # Stage 1

  collect_property_details:
    entity: property_subtype_info   # Selected only if product_type == "home"

  collect_coverage_details:
    entity: coverage_info           # Selected after property details complete
```

The transition guard on the classify state determines which entity is used next:

```yaml
transitions:
  - from: classify_product
    to: collect_property_details
    guard: "product_type == 'home'"
  - from: collect_property_details
    to: collect_coverage_details
    guard: "context_complete"
```

---

## 11. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should entities support nested/compound fields (e.g., `address: { street, city, postal_code }`)? | Schema complexity |
| 2 | Should domain models support inheritance (e.g., `homeowner_policy extends base_policy`)? | Reuse granularity |
| 3 | For guard expressions — how much expressiveness before we defer to rule engines? | Language complexity vs. power |
| 4 | Should the domain model include computed fields (fields populated by code, not by user extraction)? | Entity purity |
| 5 | Cross-workflow entity references — should an entity in `home_insurance_quote` reference an entity in `home_insurance_claims`? | Modularity |
| 6 | Migration strategy when a domain model version changes while conversations are in-flight? | Deployment safety |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent architecture document
- [Extraction Layer Design](./2026-06-17-extraction-layer-design.md) — Extract/Validate/Transform interfaces
- [State Machine Design](./2026-06-16-state-machine-design.md) — guard expression base, intent+state resolution
- [Home Insurance Workflow](../../examples/home-insurance/workflow.yaml) — reference domain model instantiation
- zelkim/langgraph-insurance-chatbot — two-stage dynamic entity selection (auto vs home vs life)
