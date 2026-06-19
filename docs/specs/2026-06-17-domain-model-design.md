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

### 1.1 Implementation Approach

Domain entities are defined using [OpenAPI 3.1 Schema Objects](https://spec.openapis.org/oas/latest.html#schema-object) (JSON Schema dialect), an industry-standard format with full ecosystem support — validators, code generators, IDE auto-complete, Swagger UI. The framework reads `components/schemas/` directly with no translation layer needed. `$ref` enables schema composition without duplication, and downstream API contracts are defined in the same format as domain entities. For a complete concrete example, see [Section 2.2](#22-complete-example--home-insurance) or [home-insurance.yaml](../../domain-models/home-insurance.yaml).

#### Alternative Schema Formats (Context)

| Format | Why Rejected |
|--------|-------------|
| Custom FieldDef (flat YAML) | No tooling ecosystem; no code generators; no standard validators |
| JSON Schema Draft 2020-12 | Less mature tooling than OpenAPI 3.1 subset; no native Swagger UI integration |
| Pydantic BaseModel | Python-only; not language-agnostic; would violate spec-first principle |
| OpenAPI 3.1 Schema Object | **Chosen** (AD 29) — industry standard, rich tooling, $ref composition, x- extensions |

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

### 2.2 Complete Example — Home Insurance

The schema above instantiates into a concrete domain model like this:

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

### 2.3 Advanced Schema Patterns

OpenAPI/JSON Schema provides composition and constraint keywords that produce richer, more precise schemas than flat field lists:

**Polymorphism (`oneOf` + `discriminator`) —** when a field's type depends on a runtime value:

```yaml
IncidentReport:
  type: object
  required: [incident_type, details]
  properties:
    incident_type:
      type: string
      enum: [fire, water_damage, theft]
    details:
      oneOf:
        - $ref: "#/components/schemas/FireIncidentDetail"
        - $ref: "#/components/schemas/WaterDamageDetail"
        - $ref: "#/components/schemas/TheftDetail"
      discriminator:
        propertyName: incident_type
        mapping:
          fire: "#/components/schemas/FireIncidentDetail"
          water_damage: "#/components/schemas/WaterDamageDetail"
          theft: "#/components/schemas/TheftDetail"
```

**Composition (`allOf`) —** merge a base schema with extensions:

```yaml
PremiumEstimate:
  allOf:
    - $ref: "#/components/schemas/QuoteRequest"
    - type: object
      required: [monthly_premium, annual_premium]
      properties:
        monthly_premium: { type: number, minimum: 0 }
        annual_premium:  { type: number, minimum: 0 }
```

**Conditional validation (`if`/`then`/`else`) —** validate one field based on another's value:

```yaml
CoverageInfo:
  type: object
  required: [coverage_type]
  properties:
    coverage_type:
      type: string
      enum: [building_only, contents_only, both]
    building_coverage:
      type: number
    contents_coverage:
      type: number
  if:
    properties:
      coverage_type:
        enum: [building_only, both]
    required: [coverage_type]
  then:
    required: [building_coverage]
  if:
    properties:
      coverage_type:
        enum: [contents_only, both]
    required: [coverage_type]
  then:
    required: [contents_coverage]
```

**Arrays with constraints —** structured lists with size bounds, uniqueness, and item schema:

```yaml
ClaimHistory:
  type: object
  properties:
    prior_claims:
      type: array
      minItems: 0
      maxItems: 50
      uniqueItems: true
      items:
        $ref: "#/components/schemas/PriorClaim"
  additionalProperties: false       # reject unknown fields
```

**Key patterns for the framework:**

| Pattern | Use Case |
|---------|----------|
| `oneOf` + `discriminator` | Entity subtype selection (fire claim vs water claim) |
| `allOf` | Extend a base entity with derived fields |
| `if`/`then`/`else` | Conditional required fields (only ask contents_coverage when coverage_type is `both`) |
| `minItems`/`maxItems`/`uniqueItems` | Bounded lists (max 50 claims, no duplicates) |
| `multipleOf` | Numeric step constraint (coverage in $100 increments) |
| `additionalProperties: false` | Strict schema — reject unrecognized LLM output fields |

---

## 3. Entity Definition

An Entity is an OpenAPI 3.1 Schema Object defined under `components/schemas/`. The framework consumes standard JSON Schema keywords directly — `type`, `required`, `enum`, `pattern`, `minLength`/`maxLength`, `minimum`/`maximum`, `format`, `description`, `$ref` — and generates ExtractionRule, ValidationRule, and TransformRule from them automatically.

**Every field must define two core parameters:**

| Parameter | JSON Schema Keyword | Purpose |
|-----------|---------------------|---------|
| **Required** | `required` (schema-level array) | Declares whether the field must be non-null; drives `context_complete` guard evaluation |
| **Regex** | `pattern` | Regex pattern for string validation; the primary deterministic validation rule |

A field without `required` defaults to optional (does not block transitions). A field without `pattern` has no regex validation — other JSON Schema keywords (`enum`, `minLength`, `minimum`/`maximum`) may still apply.

Framework-specific behavior that JSON Schema does not cover is added via `x-` prefixed extensions:

```yaml
# OpenAPI Schema Object with framework extensions
property_type:
  type: string
  enum: [apartment, house, villa]
  description: "Type of property being insured"
  x-fallback:                         # Framework: deterministic extraction fallback
    keywords: [apartment, house, villa, condo, flat]
    regex: null
    priority: llm_wins
  x-transform:                        # Framework: type coercion pipeline
    - op: normalize
      config: { to: lowercase }
    - op: lookup
      config:
        mapping:
          condo: apartment
          flat: apartment
  x-examples:                         # Framework: few-shot examples for LLM prompt
    - "I live in a house"
    - "3-bedroom apartment"
```

| Extension | Purpose |
|-----------|---------|
| `x-fallback` | Deterministic extraction fallback when LLM confidence is low: `{ keywords?: string[], regex?: string, priority: "llm_wins" \| "regex_wins" }` |
| `x-transform` | Type coercion / normalization pipeline: `[{ op: "cast" \| "normalize" \| "parse" \| "lookup" \| "default" \| "external", config: object }]` |
| `x-examples` | Few-shot examples injected into LLM extraction prompt: `string[]` |

All other validation (type checking, enum matching, pattern regex, length/range bounds) is derived directly from the entity's standard JSON Schema keywords — the framework needs no additional configuration for them.

The framework auto-generates ExtractionRule, ValidationRule, and TransformRule from each field. For example, given:

```yaml
property_type:
  type: string
  enum: [apartment, house, villa]
  description: "Type of property"
  x-fallback:
    keywords: [apartment, house, villa, condo, flat]
  x-transform:
    - op: normalize
      config: { to: lowercase }
    - op: lookup
      config:
        mapping:
          condo: apartment
          flat: apartment
```

The framework produces:

```
ExtractionRule {
  field: "property_type"
  type: "string"
  description: "Type of property (apartment, house, villa)"
  fallback_keywords: ["apartment", "house", "villa", "condo", "flat"]
}

ValidationRule {
  field: "property_type"
  type: "string"
  required: true
  enum: ["apartment", "house", "villa"]
}

TransformRule {
  field: "property_type"
  rules: [
    { op: "normalize", config: { to: "lowercase" } },
    { op: "lookup", config: { mapping: { condo: "apartment", flat: "apartment" } } }
  ]
}
```

---

## 4. State Definition

### 4.1 StateDef Schema

```
StateDef {
  name:         string    // state name (e.g., "collect_property_info")
  description:  string    // human-readable description of what this state expects
  entity:       string    // which entity this state extracts (references a schema name under components/schemas/)
  state_hint:   string    // disambiguation hint injected into LLM extraction prompt
  max_retries?: int       // max retries before escalating (default: from framework config)
}
```

### 4.2 State → Entity Binding

Each state binds to exactly one entity (an OpenAPI Schema Object). The framework reads the entity's schema to auto-generate extraction, validation, and transform rules (see [Section 9 — Framework Consumption Flow](#9-framework-consumption-flow) for the full pipeline).

### 4.3 Example

```yaml
states:
  collect_property_info:
    description: "Collect property details from the user"
    entity: $ref: "#/components/schemas/PropertyInfo"
    state_hint: >
      The user is providing property information for a home insurance quote.
      Address may include street, city, province, postal code.
      Building age is in years. "Brand new" or "newly built" means age 0.
    x-state-bindings:                # per-state extraction scope (see §3)
      property_type: {}
      address: {}
      building_age: {}
      floor_area: {}
      construction_type: {}

  collect_coverage_needs:
    description: "Collect coverage preferences"
    entity: $ref: "#/components/schemas/CoverageInfo"
    state_hint: >
      The user is choosing coverage type and amount.
      Deductible options: low (500 CNY), standard (2000 CNY), high (5000 CNY).
    x-state-bindings:
      coverage_type: {}
      coverage_amount: {}

  file_claim:
    description: "File a new claim"
    entity: $ref: "#/components/schemas/ClaimDetails"
    state_hint: >
      The user is reporting an incident for a claim.
      Incident type must be one of: fire, water_damage, theft, natural_disaster, other.
      Date should be in YYYY-MM-DD format.
    x-state-bindings:
      claim_type: {}
      damage_description: {}
      incident_date: {}
      incident_location: {}
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

## 5. Intent Model

The Intent Model defines the contract between **what the user says** (Layer 1 — NLU) and **what the system does** (Layer 2 — Routing). Every user utterance maps to an intent, which maps to an entry state.

### 5.1 IntentDef Schema

```yaml
intents:
  get_home_insurance_quote:
    name: get_home_insurance_quote
    description: "User wants a home insurance quote"
    confidence_threshold: 0.7
    entry_state: collect_property_info
    examples:
      - "I need home insurance for my house"
      - "How much is home insurance?"
      - "Get me a quote for my apartment"
    fallback_intent: general_inquiry

  file_insurance_claim:
    name: file_insurance_claim
    description: "User wants to file an insurance claim"
    confidence_threshold: 0.8
    entry_state: file_claim
    examples:
      - "My house flooded, I need to file a claim"
      - "There was a fire at my property"
    fallback_intent: general_inquiry

  general_inquiry:
    name: general_inquiry
    description: "General question not matching specific intents"
    confidence_threshold: 0.0
    entry_state: handle_general_inquiry
```

| Field | Type | Purpose |
|-------|------|---------|
| `name` | string | Unique intent identifier |
| `description` | string | Guides LLM classification prompt |
| `confidence_threshold` | float (0.0–1.0) | Minimum confidence to match; below threshold → `fallback_intent` |
| `entry_state` | string | State the workflow enters when this intent matches |
| `examples` | string[] | Few-shot examples for LLM classification |
| `fallback_intent` | string | Intent to use when confidence is below threshold |

### 5.2 Intent → State Routing

The intent model is the **deterministic entry point** into the state machine:

```
User Input: "I need home insurance"
    │
    ▼
Intent Classifier (Layer 1)
    │  confidence: 0.92 → get_home_insurance_quote
    │
    ▼
Route to entry_state: collect_property_info
    │
    ▼
State Machine starts executing transitions from collect_property_info
```

The framework uses `entry_state` to set `agentState.phase` on first turn, then transitions take over. If the classifier returns an intent below `confidence_threshold`, the framework routes to the `fallback_intent`'s `entry_state` instead.

### 5.3 Multi-Intent Sessions

A single conversation may match multiple intents over its lifetime:

```
Turn 1: "I need insurance"     → intent: get_home_insurance_quote  → state: collect_property_info
Turn 2: "Also, I had a fire"   → intent: file_insurance_claim      → state: file_claim (re-routes)
```

When a new intent arrives mid-conversation, the framework evaluates whether to **re-route** (switch to new entry_state) or **continue** (stay in current state). The default behavior is to re-route unless the current state's transition rules explicitly prevent it.

---

## 6. Transition Definition

Transitions define valid paths between states. Guards are boolean expressions evaluated against the current entity state. The **authoritative guard expression syntax** is defined in [State Machine Design §3.4](./2026-06-16-state-machine-design.md).

### 6.1 TransitionDef Schema

```
TransitionDef {
  from:      string    // source state name
  to:        string    // target state name
  guard:     string    // guard expression (see Section 6)
  priority?: int       // higher = checked first (for conflict resolution)
  label?:    string    // optional label for documentation / conditional edge naming
}
```

### 6.2 Transition Semantics

- **Self-loop**: `from: collect_property_info, to: collect_property_info, guard: "context_incomplete"` — stay in current state until all required fields are filled
- **Advance**: `from: collect_property_info, to: assess_risk, guard: "property_type != null AND address != null AND building_age != null"` — move forward when entity fields are complete
- **Conditional branch**: multiple transitions from the same state with non-overlapping guards decide the next state

### 6.3 Conflict Resolution

When multiple transitions from the same state have guards that could both be true:

1. **Priority ordering** — higher `priority` value is checked first
2. **First-match wins** — the first guard that evaluates true determines the transition
3. **Unreachable fallback** — if all guards fail, the framework uses the `on_nomatch` transition (explicitly defined or `on_transform_failure` node)

### 6.4 Example

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

### 6.5 Reserved Transition Target: `errorNode`

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
3. For each state → look up bound entity → expand OpenAPI Schema Object properties to:
   a. ExtractionRule[]  (from field name, type, description, x-fallback, x-examples)
   b. ValidationRule[]  (from required, type, pattern, enum, minLength/maxLength, minimum/maximum)
   c. TransformRule[]   (from x-transform)
4. Merge with node-level overrides (context_window_size, max_transform_attempts, etc.)
5. Instantiate Extract / Validate / Transform nodes via ExtractionFactory(strategy)
6. Generate LangGraph nodes + conditional edges from transition definitions
```

---

## 10. Persistence Schema

The Domain Model also defines what gets persisted — the runtime data structures consumed by checkpoint storage, audit logging, and code generation. These schemas live alongside business entities in `components/schemas/`.

### 10.1 AgentState

The shared state object persisted at every turn checkpoint:

```yaml
AgentState:
  type: object
  required: [conversation_id, user_id, phase, fieldTo, fieldExtractedList, collectedFields]
  properties:
    conversation_id:
      type: string
      format: uuid
    user_id:
      type: string
      description: "trace_id — same as user_id per tracing model"
    phase:
      type: string
      description: "Current state name (matches StateDef.name)"

    # --- Field → Entity routing ---
    fieldTo:
      type: object
      additionalProperties: { type: string }
      description: >
        Maps each field name to its target entity name.
        Derived from x-state-bindings at domain model load time.
        Example: { "street": "Address", "first_name": "UserInfo",
                   "monthly_premium": "QuoteRequest" }

    # --- Extraction tracking ---
    fieldExtractedList:
      type: array
      items: { type: string }
      description: >
        List of field names that passed Extract → Validate → Transform
        successfully. Only fields in this list are written into
        collectedFields (the DomainModel entity).
        Fields that failed validation or transformation are NOT added here.

    # --- DomainModel entity values (successfully collected only) ---
    collectedFields:
      type: object
      additionalProperties: true
      description: >
        Accumulated field values that passed all three stages
        (Extract → Validate → Transform). Structured per-entity:
        { "Address": { "street": "123 Main", "city": "Toronto" },
          "UserInfo": { "first_name": "Alice" } }
        This IS the DomainModel entity state — only verified values live here.

    lastIntent:
      type: string
      description: "Last classified intent name"
    intentConfidence:
      type: number
      minimum: 0
      maximum: 1
    turnNumber:
      type: integer
      minimum: 0
    lifecycleState:
      type: string
      enum: [created, active, paused, completed, abandoned, timeout, archived]
    createdAt:
      type: string
      format: date-time
    lastActiveAt:
      type: string
      format: date-time
```

**Key invariant:**

```
Extract → Validate → Transform passes for field X
  → X is added to fieldExtractedList
  → X's value is written into collected_fields[fieldTo[X]]
  → context_complete guard checks collected_fields[entity].required fields

Extract → Validate → Transform fails for field Y
  → Y is NOT added to fieldExtractedList
  → Y is NOT written into collected_fields
  → collected_fields is PARTIAL but always CORRECT
```

`collected_fields` is the single source of truth for what has been successfully collected. If a user provides address AND phone, but phone fails validation, only address is in `collected_fields` — the DomainModel entity never contains unverified data.

### 10.2 Checkpoint Record

LangGraph checkpoint enriched with domain metadata:

```yaml
Checkpoint:
  type: object
  required: [checkpoint_id, conversation_id, agent_state]
  properties:
    checkpoint_id:
      type: string
      format: uuid
    conversation_id:
      type: string
      format: uuid
    agent_state:
      $ref: "#/components/schemas/AgentState"
    context:
      type: object
      properties:
        extraction_result: { type: object }
        routing_decision:  { type: object }
        response_data:     { type: object }
    messages:
      type: array
      maxItems: 20
      items:
        $ref: "#/components/schemas/ConversationMessage"
    audit:
      type: object
      properties:
        state_transitions:
          type: array
          items:
            $ref: "#/components/schemas/LifecycleAuditEntry"
        llm_calls:
          type: array
          items:
            $ref: "#/components/schemas/LLMCallRecord"
```

### 10.3 Conversation History

```yaml
ConversationMessage:
  type: object
  required: [message_id, turn_number, role, content, timestamp]
  properties:
    message_id:
      type: string
    turn_number:
      type: integer
    role:
      type: string
      enum: [user, agent, system]
    content:
      type: string
      maxLength: 10000
    extracted:
      type: object
      description: "Fields extracted from this message (Layer 1 output)"
    intent:
      type: string
    confidence:
      type: number
    components:
      type: array
      description: "Widget components rendered in this message"
    masked:
      type: boolean
      description: "Whether PII was scrubbed before storage. The authoritative PII rules definition is in [Response Generation §8](./2026-06-17-response-generation-layer-design.md)."
    timestamp:
      type: string
      format: date-time
```

### 10.4 Audit Records

```yaml
LifecycleAuditEntry:
  type: object
  required: [timestamp, conversation_id, previous_state, new_state, trigger]
  properties:
    timestamp:      { type: string, format: date-time }
    conversation_id: { type: string }
    user_id:         { type: string }
    previous_state:  { type: string }
    new_state:       { type: string }
    trigger:         { type: string }
    turn_number:     { type: integer }
    checkpoint_id:   { type: string }

LLMCallRecord:
  type: object
  required: [timestamp, model, latency_ms, tokens_used]
  properties:
    timestamp:    { type: string, format: date-time }
    model:        { type: string }
    provider:     { type: string }
    latency_ms:   { type: integer }
    tokens_used:
      type: object
      properties:
        input:  { type: integer }
        output: { type: integer }
    schema_violation: { type: boolean }
    retry_attempt:    { type: integer }
```

### 10.5 Code Generation Contract

The framework consumes these schemas to generate:

| Generated Artifact | Source Schema |
|--------------------|--------------|
| `AgentState` Python dataclass / TypeScript interface | `AgentState` schema |
| `Checkpoint` serialization/deserialization code | `Checkpoint` schema |
| `ConversationMessage` DTO | `ConversationMessage` schema |
| Database migration (checkpoint store DDL) | `AgentState` + `Checkpoint` schemas |
| Audit log query API | `LifecycleAuditEntry` + `LLMCallRecord` schemas |
| Intent classifier training data format | `IntentDef` entries |

---

## 11. Edge Cases

### 11.1 Cross-Entity Data

When a state collects `coverage_needs` but the transition guard references a field from `property_info` (collected in a previous state), the framework evaluates the guard against the accumulated `collectedFields` across all entities. This enables guards like `"building_age > 10 AND building_coverage > 500000"`.

### 11.2 Dynamic Entity Selection

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

## 12. Open Questions

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
