# Agent 2: Cross-Model Reviewer — Core Design Issues

> Internal consistency, correctness, completeness, clarity, trade-off honesty, and edge case analysis.
> Each issue is scoped to a specific file. Cross-references are noted where they span files.

---

## File A: HLD (2026-06-16-deterministic-workflow-framework-design.md)

### A.1 — consistency: `errorNode` referenced but not defined in HLD
- **Location:** Line 131, 168; Section 4.1 table row "Deterministic fallback"
- **Issue:** The HLD mentions `errorNode` as a pattern injected by the framework ("retry budgets → Per-node retry count + errorNode unified handling") but never defines what `errorNode` is. The definition is deferred to "Routing & Execution Spec Section 6," which was written after this HLD. A reader of the HLD alone cannot understand this critical architectural primitive.
- **Severity:** Low (cross-reference exists, but HLD should be self-contained for core concepts)

### A.2 — clarity: Context Hydration YAML example references undefined `application_service`
- **Location:** Line 73–78, YAML schema `on_phase_entry.collect_property_info`
- **Issue:** The example lists `source: application_service` as a hydration source. This source type is not defined in the Hydration Sources table (lines 107–112), which only lists Checkpoint DB, Session Store, Domain Entity API, and External Business API. There is no mapping from `application_service` to any of these four types. The reader cannot determine whether `application_service` is a Domain Entity API or an External Business API.
- **Severity:** Medium (example is misleading)

### A.3 — completeness: No definition of "phase" in the agent lifecycle
- **Location:** Entire document; `agentState.phase` mentioned at lines 96, 131, 133
- **Issue:** The term `phase` is used extensively but never formally defined in the HLD. It appears in the YAML example (`on_phase_entry`), in the architecture description (`agentState.phase`), and in the routing description ("phase-aware routing"). The State Machine design doc defines phase as a direct mapping from `StateDef.name` — but the HLD should establish this concept or at minimum state that it is defined in the SM spec. A reader of only the HLD would find the concept opaque.

### A.4 — trade_off_gap: No trade-off analysis for Context Hydration's overhead
- **Location:** Section 2.1–2.2
- **Issue:** The spec states Context Hydration is "selective" and avoids loading unrelated entities. However, it does not analyze the latency trade-off: even selective loading requires an API call (or DB query) before Layer 1 begins. In a synchronous HTTP chatbot, this is added to the user-perceived latency. The spec should acknowledge that hydration adds latency and discuss caching strategies (e.g., staleness tolerances, TTL-based refresh vs. always-fresh).
- **Severity:** Medium (operational concern for production deployment)

### A.5 — consistency: `ToolMeta.type` enum includes `a2a` and `sdk` — no definition in HLD
- **Location:** Line 177, changelog entry 0.9.0
- **Issue:** Version 0.9.0 adds `a2a` and `sdk` to the `ToolMeta.type` enum but neither concept is defined in the HLD body. The A2A Protocol spec and Tool Ecosystem spec are external documents. A reader of the HLD has no basis for understanding what these tool types mean or how they differ from `api` or `mcp`.
- **Severity:** Low (cross-references exist)

### A.6 — missing_edge_case: What happens when hydration fails?
- **Location:** Section 2.1–2.2
- **Issue:** The spec describes what Context Hydration loads but not what happens when a hydration source is unavailable. If `checkpoint_db` is down, `session_store` is unreachable, or `application_service` returns 500 — the framework's behavior is undefined. Does it retry? Fall back to stale state? Route to errorNode? Halt the conversation? The stateless design (YAML declares dependencies) needs a failure contract.
- **Severity:** High (production reliability concern for regulated industries)

### A.7 — clarity: "Framework as Interface + Pattern Injection" — no interface contracts defined
- **Location:** Section 4.1, line 139
- **Issue:** The spec says "The developer implements `ExtractionNode.execute()`, `ValidatorNode.validate()`, `TransformNode.transform()`" but none of these interfaces are defined in the HLD. The Extraction Layer spec defines Extract/Validate/Transform interfaces, but the HLD itself does not link to them or define the contracts. The reader is told the framework handles "everything around it" without knowing what the boundary is.
- **Severity:** Medium (interface contracts should be at least summarized in the HLD)

---

## File B: State Machine Design (2026-06-16-state-machine-design.md)

### B.1 — missing_edge_case: What happens when both `exit_guard_blocked` and `context_incomplete` are true?
- **Location:** §3.3 meta-variables list, §3.4 guard expression
- **Issue:** Both `exit_guard_blocked` and `context_incomplete` are framework-generated meta-variables. If a state has both an exit_guard that fails AND context is incomplete, which meta-variable takes priority? The spec's priority ordering (§6.3) says "higher priority value is checked first" — but if both self-loop (`context_incomplete`) and an exit_guard rejection transition have the same priority, the first match wins based on YAML document order. This is fragile and undocumented.
- **Severity:** High (non-deterministic behavior at runtime)

### B.2 — correctness: SCXML section references in mapping table are wrong/inconsistent
- **Location:** §1.0 SCXML ↔ YAML Mapping table
- **Issue:** The mapping table references specific SCXML sections (e.g., `§3.3.2` for `<onentry>`, `§4.4` for `<assign>`). Cross-checking against the actual W3C SCXML Recommendation (https://www.w3.org/TR/scxml/):
  - `<onentry>` is defined in §3.8, not §3.3.2 (which is `<state>` children)
  - `<assign>` is defined in §5.4, matching the table. But `§4.4` is `<elseif>` in executable content, not `<assign>` in data model.
  - This error propagates — the `<onexit>` reference to `§3.3.2` is also wrong (should be §3.9)
  - The `<if>`, `<elseif>`, `<else>` references to `§4.7` are correct, but `§4.3`, `§4.4`, `§4.5` would be `§4.7` if/elseif/else — the actual sections are 4.3 `<if>`, 4.4 `<elseif>`, 4.5 `<else>`
- **Impact:** If used for compliance/audit, incorrect section references undermine the claim of SCXML alignment.

### B.3 — consistency: "exit_guard" used in §3.3 field reference but mapped to guard expression syntax
- **Location:** §3.3 field reference: `exit_guard: "boolean expression evaluated on exit"`
- **Issue:** The `exit_guard` field is described as a "boolean expression" in §3.3 but the comparison matrix in §3.2 says exit_guard "routes to alternate branch" on failure, not "blocks transition." The behavior description in §3.2 (diagram) shows exit_guard causing a "route elsewhere" — which implies it's a branching mechanism, not just a boolean gate. These are semantically different: a boolean gate says "pass/fail," a branch says "if A → target1, if B → target2." The guard expression syntax (§3.4) only supports boolean expressions, not value-based routing.
- **Severity:** Medium (semantic confusion)

### B.4 — missing_edge_case: No specification of the transition evaluation order when exit_guard blocks but context is also incomplete
- **Location:** §3.5 execution order, §6.3 conflict resolution
- **Issue:** The execution order diagram in §3.5 shows: on_exit.set_field → evaluate exit_guard → on_take.set_field → checkpoint → on_entry.set_field → execute main logic. But what if the exit_guard leads to a transition that routes to a state whose entry_guard fails? The spec covers entry_guard failure (routes to errorNode) but not the case where the transition target is invalid because entry_guard fails. The entry_guard is evaluated at step 5 (after checkpoint), which means the checkpoint has already committed the transition before discovering it's invalid.
- **Severity:** High (state inconsistency — partially committed transition)

### B.5 — correctness: `multipleOf` referenced in §2.3 advanced patterns but not defined in domain model
- **Location:** §2.3 (Domain Model), key patterns table row "`multipleOf`" (line 260)
- **Issue:** The domain model's §2.3 says `multipleOf` is a key pattern: "Numeric step constraint (coverage in $100 increments)." But the Domain Model spec (2026-06-17-domain-model-design.md) does not list `multipleOf` anywhere in the "Every field must define two core parameters" table (§3), which only lists `required` and `regex`. The `multipleOf` keyword is part of JSON Schema (and OpenAPI 3.1) but the framework's auto-generation logic (§9 step 3b) does not mention processing `multipleOf` into a ValidationRule. This means the advertised feature has no implementation path.
- **Severity:** High (broken feature claim)

### B.6 — missing_edge_case: `on_take` transitions that target the same state as source
- **Location:** §3.5 State Lifecycle Actions
- **Issue:** The execution order diagram shows on_take.set_field executing between checkpoint and on_entry.set_field. For a self-loop transition (`from: A, to: A, guard: ...`), this means: on_exit(A) → evaluate exit_guard → on_take(transition) → checkpoint → on_entry(A) → execute A's main logic. But §6.2 says self-loops "stay in current state." Does the state re-execute its on_entry? The spec is ambiguous. If yes, the self-loop has different semantics than staying (it re-initializes state-local variables). If no, the on_entry.set_field should not execute for self-loops.
- **Severity:** Medium (semantic ambiguity for self-loops)

### B.7 — clarity: Guard expression syntax mixes `AND`/`OR` with `and`/`or`
- **Location:** §3.4 Guard Expression Syntax: "Boolean operators: `AND`, `OR`, `NOT`, `and`, `or`, `not`"
- **Issue:** Allowing both uppercase and lowercase boolean operators creates two syntaxes for the same concept. If a guard expression uses `AND` and another developer uses `and`, are they equivalent? If the expression is evaluated via Python `eval()`, `AND` is not valid Python and must be preprocessed. If evaluated via a custom parser, the dual syntax doubles the parsing surface. The spec should pick one canonical form.
- **Severity:** Low (style inconsistency, parser ambiguity)

### B.8 — completeness: `on_take` field mutations are defined as per-transition but not integrated with the transition schema
- **Location:** §3.5, compare with workflow.yaml transition schema
- **Issue:** §3.5 defines `on_take` with `set_field` as a per-transition lifecycle hook. However, the transition definition schema in §2 (and the examples in §6.4) do not include `on_take` or `set_field` as fields of the transition object. The field reference in §3.3 only lists state-level fields (`on_entry`, `on_exit`), not transition-level fields (`on_take`). This means the feature is described but not wired into the data schema.
- **Severity:** Medium (incomplete schema)

---

## File C: Intent Classification (2026-06-16-intent-classification-design.md)

### C.1 — missing_edge_case: What happens when LLM Gateway is entirely unavailable?
- **Location:** §2.4, §3.4
- **Issue:** The classification flow (§3.4) says: "If confidence < threshold or LLM fails (retries exhausted) → return unrecognized_intent." But what if the LLM Gateway is completely unavailable (network partition, provider outage, quota exhaustion)? Every message would produce `unrecognized_intent` → clarification → same failure → infinite clarification loop. The spec has no circuit breaker or degraded-mode behavior.
- **Severity:** High (system-wide failure mode)

### C.2 — consistency: `complex` field is now always `false` for all system intents — why define it?
- **Location:** §2.1 table, line 56 note: "All system intents are complex: false"
- **Issue:** The note says "All system intents are `complex: false`" and the table confirms this for all 17 intents. If the `complex` field is always `false` for system intents, its presence in the table is dead weight. The field has meaning only for custom intents. The spec should either remove it from the system intent table or explain why it's included despite being invariant.

### C.3 — correctness: Intent combination rules allow `1 complex + N simple` but don't define ordering
- **Location:** §4.3 conflict resolution
- **Issue:** "1 complex + N simple intents → Yes → Process together (simple intents ride on the complex workflow)." But which simple intent's extraction runs first? If the user says "I want a quote for my house at 123 Main St, and by the way what's my current deductible?", the complex intent is `get_quote` and the simple intent is `ask_question`. The spec says both process together, but these intents map to different agents (state machine vs. ReadOnlyAgent). The ordering of extraction and response matters — do we answer the question before collecting quote data, or vice versa? The spec does not define priority or ordering for combined intents.
- **Severity:** Medium (undefined behavior for multi-intent handling)

### C.4 — missing_edge_case: Intent "drift" detection has no concrete design
- **Location:** §5.5
- **Issue:** The spec raises the question: "In long-running conversations (20+ turns), user intent may shift gradually without an abrupt topic switch. Should the framework detect intent drift via a windowed confidence trend?" This is listed as an open question with no answer. For a deterministic framework targeting regulated industries, silent intent drift is a compliance risk — the bot could continue processing a quote when the user has gradually shifted to asking about a claim. The spec should either define a drift detection mechanism or explicitly state that the state machine's per-state intent policy is the sole mechanism.
- **Severity:** Medium (compliance risk for regulated industries)

### C.5 — consistency: `agentState.phase` used in classification but phase values cross-reference SM doc without synchronization
- **Location:** §3.1, line 270 note
- **Issue:** The note says "Intent classification input also includes `agentState.phase` (e.g., `quoting`, `claims`, `onboarding`)." But the SM spec defines phases as state names like `collect_property_info`, `collect_coverage_needs`, `assess_risk` — not high-level categories like `quoting`, `claims`, `onboarding`. The example phase values in the intent doc do not match the phase naming convention in the SM doc. This creates confusion about whether phase is a state name or a category name.
- **Severity:** Medium (cross-spec inconsistency)

### C.6 — trade_off_gap: No cost analysis for 17 system intents in every classification prompt
- **Location:** §3.3 prompt construction
- **Issue:** The classification prompt includes "a list of all intents with their descriptions" plus "few-shot examples for each intent." With 17 system intents + N custom intents, and ≥3 examples per intent (per §5.7), the classification prompt could be: 17 system intents × (description + 3 examples) + N custom intents × (description + 3 examples). At ~50 tokens per example, this is 17 × (10 + 150) + N × (10 + 150) = 2,720 + 160N tokens of prompt overhead per classification call. For workflows with 10 custom intents, that's ~4,300 tokens per message — purely for classification. The spec does not analyze this cost or propose prompt compression strategies.
- **Severity:** Medium (cost at scale)

---

## File D: Domain Model (2026-06-17-domain-model-design.md)

### D.1 — correctness: `$ref` reference `#/components/schemas/PropertyInfo` not defined in example
- **Location:** §2.2 line 133–134: `$ref: "#/components/schemas/PropertyInfo"` and `$ref: "#/components/schemas/CoverageInfo"`
- **Issue:** The HomeInsurance schema example references `PropertyInfo` and `CoverageInfo` via `$ref` but neither schema is defined in the example or anywhere in the document. The `Address`, `UserInfo`, `HomeInsurance`, and `QuoteRequest` schemas are shown, but `PropertyInfo` and `CoverageInfo` are referenced without definition. An OpenAPI validator would reject this as an unresolvable `$ref`. While the text says "For the complete concrete example, see home-insurance.yaml," the inline example should be consistent or note that referenced schemas are defined elsewhere.
- **Severity:** Low (cross-reference exists but example is incomplete)

### D.2 — missing_edge_case: Cross-entity guard evaluation — field name collision
- **Location:** §11.1 Cross-Entity Data
- **Issue:** The spec says "the framework evaluates the guard against the accumulated collectedFields across all entities." But what if two entities define the same field name with different types? For example, `Address` has `postal_code: string` and `ClaimLocation` also has `postal_code: string`. A guard expression `postal_code != null` would be ambiguous — which entity's field does it reference? The spec defines `fieldTo` in AgentState (§10.1) as a mapping "Maps each field name to its target entity name" — but this mapping is a dict with unique keys. If two entities share a field name, only one entry survives.
- **Severity:** High (data collision for shared field names across entities)

### D.3 — consistency: OpenAPI 3.1 adoption not reflected in framework extensions
- **Location:** §3 extension definitions, §9 framework consumption flow
- **Issue:** Version 0.5.0 adopts OpenAPI 3.1 Schema as the canonical format. However, §3 defines `x-fallback`, `x-transform`, `x-examples` extensions using a custom format. OpenAPI 3.1 supports `examples` natively (as a standard JSON Schema keyword). The `x-examples` extension duplicates a standard feature. The framework consumption flow (§9 step 3a) says it consumes `x-examples` but does not mention the standard `examples` keyword. If a developer uses the standard `examples` field, will the framework ignore it?
- **Severity:** Medium (duplicate feature with unclear resolution)

### D.4 — completeness: Domain model versioning (§8.1) has no migration semantics
- **Location:** §8.1 Versioning
- **Issue:** The spec says "Workflows pin to a version: `home-insurance@1.2.0`" and "Breaking changes require a major version bump." But it does not define what constitutes a breaking change beyond "field removal, type change." Adding a required field is also breaking. Changing an enum value is breaking. Changing a regex pattern is breaking. The spec should enumerate the complete set of breaking vs. non-breaking changes for domain model versioning.
- **Severity:** Medium (incomplete contract for versioning)

### D.5 — trade_off_gap: No discussion of domain model size vs. LLM prompt token budget
- **Location:** Entire document
- **Issue:** The domain model's "full OpenAPI schema" is used as the LLM 2 (broad scan) prompt context (per Extraction Layer §2.6). For a complex domain like home insurance with 30+ entities, the full schema could be 5,000–15,000 tokens. The spec does not discuss how domain model size impacts extraction latency, cost, or accuracy. There is no guidance on schema trimming, and no analysis of how many entities can fit within a model's context window.
- **Severity:** Medium (scale limitation not acknowledged)

### D.6 — missing_edge_case: `collected_fields` partial correctness invariant vs. checkpoint rollback
- **Location:** §10.1 key invariant
- **Issue:** The invariant states: `collected_fields` never contains unverified data. But LangGraph checkpoints persist state at every transition. If a field passes Extract→Validate→Transform and is written to `collected_fields`, the checkpoint captures this. If a later transform attempt (max retries exhausted) routes to errorNode, what happens to the `collected_fields`? Does the errorNode execution count as a transition that commits the (now-invalid) checkpoint? Or does the framework roll back the checkpoint to before the failed extraction?
- **Severity:** Medium (checkpoint consistency during error recovery)

---

## File E: Extraction Layer (2026-06-17-extraction-layer-design.md)

### E.1 — correctness: Confidence matrix in §2.6 has an undefined cell
- **Location:** §2.6, resolution matrix, row "LLM 1 ≥ 0.7, LLM 2 ≥ 0.7" → "Use LLM 1 (if conf1 ≥ conf2) or LLM 2"
- **Issue:** The matrix cell says: "Use LLM 1 (if conf1 ≥ conf2) or LLM 2." But "or LLM 2" without its condition is ambiguous. It should say "Use LLM 1 if conf1 ≥ conf2, else use LLM 2." The decision tree above the matrix (lines 178–185) is slightly clearer but uses a different threshold logic (0.7 vs. "LLM 1 confidence ≥ LLM 2 confidence"). The matrix and the decision tree should be identical in semantics.
- **Severity:** Low (minor ambiguity, but deterministic behavior requires unambiguous rules)

### E.2 — missing_edge_case: What happens when LLM 1 succeeds but LLM 2 fails entirely?
- **Location:** §2.6, merge-resolve flow
- **Issue:** The parallel extraction runs two LLM calls concurrently. If LLM 2 (broad scan) fails entirely (timeout, provider error, malformed output), does the pipeline continue with only LLM 1's results? The "Fallback" row in §3.2 Option A says "On LLM failure → return partial results with lower confidence; merge still proceeds with available results." But the merge flow in §2.6 assumes both LLMs produce results. If LLM 2 produces no output, the LLM 2-only field confirmation step has no data to confirm. The spec should define the degraded-mode behavior explicitly.
- **Severity:** Medium (degraded mode undefined)

### E.3 — consistency: `on_transform_failure` node name references across documents
- **Location:** §2.2, §2.3, §6.4
- **Issue:** The spec references `on_transform_failure` as the node to route to on failure. In the HLD, this concept is called `errorNode`. The extraction layer routes to `on_transform_failure` which "ultimately routes to errorNode." But the YAML example in §6.4 uses `ask_missing_property_info` as the `on_transform_failure` value — which is a domain-specific node, not a framework-level error node. The relationship between `on_transform_failure`, `ask_missing_*`, and `errorNode` is a three-level cascade that is never diagrammed or described as a complete flow.
- **Severity:** Medium (error routing ambiguity)

### E.4 — trade_off_gap: No analysis of the LLM 2 (broad scan) false positive rate
- **Location:** §2.6 design decisions table
- **Issue:** The design decisions table lists 10 decisions with rationales, but none address the false positive risk of LLM 2's broad scanning. LLM 2 scans the full schema with "relaxed matching" — this means it will inevitably produce false positives (extracting "Toronto" as an email field, mapping phrases to wrong entities). The user confirmation step mitigates this for LLM 2-only fields, but the cost in user experience (being asked to confirm irrelevant data) is not analyzed. A metric for expected false positive rate or a calibration strategy is absent.
- **Severity:** Medium (UX degradation from false positives)

### E.5 — missing_edge_case: Same user message produces conflicting extractions in LLM 1 and LLM 2 with equal confidence
- **Location:** §2.6 resolution matrix
- **Issue:** The resolution matrix has a cell for "LLM 1 ≥ 0.7 AND LLM 2 ≥ 0.7" → "Use LLM 1 (if conf1 ≥ conf2) or LLM 2." But what if conf1 == conf2 exactly? The spec doesn't define the tiebreaker. In a deterministic framework, every edge case must have a defined behavior. If the default is "use LLM 1" (narrow scope trumps), that should be stated explicitly.
- **Severity:** Low (edge case but deterministic behavior must be unambiguous)

### E.6 — correctness: `ExtractedIntentPayload.msg_id` generation conflicts with classifier `msg_id`
- **Location:** §3.5 base class: `msg_id: str = field(default_factory=lambda: uuid4().hex)`
- **Issue:** The ExtractionResult references `msg_id` as a unique per-message identifier. But §1 of the LLM Audit Record schema (§11.1) says the audit record uses `msg_id` from `ExtractionResult.msg_id`. If both the classifier and the extractor generate their own `msg_id` via `uuid4().hex`, they will produce different IDs for the same user message. The intent classification result and extraction result will have different `msg_id` values, making audit correlation impossible unless the framework overrides the extractor's `msg_id` with the classifier's `msg_id`.
- **Severity:** High (broken audit trail correlation)

### E.7 — clarity: "last 3 user + 3 agent messages" — what happens on turn 1?
- **Location:** §2.6: "Input window: last 3+3 messages"
- **Issue:** On the first turn, there are no prior messages. The spec doesn't define what "last 3 user + 3 agent messages" means for turn 1 (empty history). Does it send an empty context window? Does it pad with a special token? Does it use a shorter window? The behavior at conversation start is undefined.
- **Severity:** Low (edge case but affects every first-turn classification and extraction)

### E.8 — missing_edge_case: Field extracted by LLM 2 but already exists in `collected_fields` from a previous turn
- **Location:** §2.6 confirmation step
- **Issue:** LLM 2 may "discover" a field that was already collected and validated in a previous turn. The spec says "LLM 2-only fields require user confirmation." But if the user already provided their phone number in turn 2, and LLM 2 "finds" it again in turn 5's context window, asking the user to confirm it again is poor UX. The spec should define how LLM 2 results are deduplicated against already-collected fields in `agentState.collected_fields`.
- **Severity:** Medium (UX degradation for repeated confirmation of known data)

### E.9 — completeness: `payloads: list[ExtractedIntentPayload]` has no size limit
- **Location:** §3.1 contract: `ExtractionResult { payloads: ExtractedIntentPayload[] }`
- **Issue:** A single user message could theoretically map to many intents (e.g., "I want a quote for 123 Main St, my phone is 555-0000, I'm 35 years old, what's my current deductible, also I filed a claim last week, and by the way can I add flood coverage"). The classifier could produce 6+ intents, each spawning an ExtractedIntentPayload. The extraction node has no upper bound on the number of payloads. At some point, the LLM prompt becomes too large or the processing time exceeds SLA.
- **Severity:** Low (edge case, but resource unbounded)

---

## Cross-File Consistency Issues

### X.1 — `agentState.phase` naming: intent-classification uses categories, state-machine uses state names
- **Files:** Intent Classification §3.1 (line 270) vs. State Machine §4.4 (line 415) vs. Domain Model §4.4
- **Issue:** Intent classification says phase examples are `quoting`, `claims`, `onboarding` (high-level categories). State Machine and Domain Model say phase = `StateDef.name` (e.g., `collect_property_info`). The two conventions are incompatible. If the classifier receives a categorical phase and the state machine uses a specific state name, the phase-aware prompting will receive a value the classifier wasn't designed for.
- **Severity:** High (runtime data mismatch)

### X.2 — `errorNode` definition is spread across 4 documents with inconsistent specificity
- **Files:** HLD §4.1, State Machine §3.1, Domain Model §6.5, Extraction Layer §2.2
- **Issue:** Each document defines `errorNode` differently:
  - HLD: "errorNode unified handling" (vague)
  - SM: "provides unified error handling, defined in Routing & Execution spec Section 6" (deferred)
  - DM: "Always reachable. Framework-level primitive. Do not declare." (most specific)
  - EL: "on_transform_failure node → ultimately routes to errorNode" (nested reference)
  - There is no single canonical definition. The Routing & Execution spec Section 6 is referenced as the authority but does not exist in the document tree (the spec file is `2026-06-17-routing-execution-layer-design.md`).
- **Severity:** High (no single source of truth for a critical safety primitive)

### X.3 — Domain model states vs. workflow states: separate but overlapping definitions
- **Files:** Domain Model §4 vs. State Machine §3.3 vs. workflow.yaml
- **Issue:** The Domain Model defines `StateDef` with `name`, `entity`, `state_hint`. The State Machine defines states in YAML with `executor`, `intent_policy`, `action`, `on_entry`, `on_exit`, `input_schema`, etc. These are two different state definition formats that must be merged at framework startup (§7). But the merge strategy is never specified in terms of what wins on conflict. If the domain model says `entity: property_info` and the workflow YAML says `input_schema: {coverage_type: int}`, which takes precedence? The merge flow diagram (§7.1) just shows "merge" as an arrow.
- **Severity:** High (undefined merge semantics between two overlapping state definitions)

### X.4 — `collectedFields` / `collected_fields` naming inconsistency
- **Files:** Domain Model §10.1 uses `collected_fields`, Domain Model §11.1 uses `collectedFields` (camelCase), State Machine §3.5 uses `collectedFields`
- **Issue:** The field name varies between `collected_fields` (Python/schema convention) and `collectedFields` (JavaScript/code convention) across documents. While the Domain Model's AgentState schema uses `collected_fields`, the prose in other sections uses `collectedFields`. If code generation produces both forms in different contexts, it creates naming confusion.
- **Severity:** Low (naming inconsistency)

---

## Summary Statistics

| Category | Count | Files Most Affected |
|----------|-------|---------------------|
| correctness | 6 | B (SCXML refs), D ($ref), E (matrix, msg_id) |
| completeness | 5 | A (hydration), C (drift), D (versioning), E (broad scan) |
| clarity | 4 | A (errorNode, phase), B (exit_guard), E (turn 1) |
| consistency | 7 | A (tool types), C (phase values), D (examples), E (error routing), X.1–X.4 |
| trade_off_gap | 3 | A (hydration overhead), C (prompt token cost), E (false positive rate) |
| missing_edge_case | 11 | B (conflict resolution, self-loops), C (LLM outage), D (field collision), E (LLM 2 fail, tiebreaker, dedup) |

**Most concerning cross-file issue:** X.1 — the `agentState.phase` value format mismatch between Intent Classification (categories) and State Machine (state names) would cause runtime failures in phase-aware prompting.
