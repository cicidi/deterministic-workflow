# Agent 0: Vision Alignment + Cross-Document Review

**Date:** 2026-06-18
**Scope:** All 19 spec files checked against VISION.md and against each other.

---

## Vision Violations

### VIOL-1: Implementation code in extraction spec
- **File:** `docs/specs/2026-06-17-extraction-layer-design.md:325-369`
- **Issue:** Contains Python dataclass definitions (`ExtractedIntentPayload`, `ConfirmIntentPayload`, `DeclineIntentPayload`, `ProvideInformationIntentPayload`, `GetQuoteIntentPayload`, `FileClaimIntentPayload`, `ExtractionResult`) with full `@dataclass` decorators and implementation details.
- **Vision conflict:** VISION.md §4.1 "No implementation code yet. Spec-first. Schemas + samples only." AD 7 "Spec-first + Python reference impl."
- **Fix:** Replace Python dataclass code with YAML schema definitions. The dataclass shapes can be expressed as JSON/YAML schema objects (matching AD 29 OpenAPI 3.1 standard).

### VIOL-2: Implementation code in extraction spec (validation)
- **File:** `docs/specs/2026-06-17-extraction-layer-design.md:385-401`
- **Issue:** Contains Python function `validate_payload_fields` with a hardcoded `VALID_AGENT_FIELDS` set and guardrail logic.
- **Vision conflict:** Same as VIOL-1 — implementation logic, not schema.
- **Fix:** Describe the guardrail contract in YAML schema; remove the Python function body.

### VIOL-3: Implementation code in extraction spec (factory)
- **File:** `docs/specs/2026-06-17-extraction-layer-design.md:408-426`
- **Issue:** Contains `INTENT_PAYLOAD_MAP` dictionary and `build_extraction_result` function with full implementation logic.
- **Vision conflict:** Same as VIOL-1.
- **Fix:** Replace with YAML mapping schema describing intent→payload relationships.

### VIOL-4: Implementation code in extraction spec (audit)
- **File:** `docs/specs/2026-06-17-extraction-layer-design.md:846-859`
- **Issue:** Contains Python dataclass `LLMAuditRecord` with full implementation.
- **Vision conflict:** Same as VIOL-1.
- **Fix:** Express as YAML schema. The audit record shape is already partially covered in Domain Model §10.4; cross-reference instead.

### VIOL-5: Implementation code in agent-types spec
- **File:** `docs/specs/2026-06-18-agent-types.md:170-181`
- **Issue:** Contains Python function `dispatch_agent` with implementation logic (hardcoded intent→agent mapping).
- **Vision conflict:** Same as VIOL-1 — not a schema, not an interface, it's executable logic.
- **Fix:** Replace with a YAML mapping table showing intent→agent dispatch rules. The `agent_map` pattern is a declarative mapping, not execution logic — express it declaratively.

### VIOL-6: RAG interface spec uses Python Protocol classes
- **File:** `docs/specs/2026-06-18-rag-interface.md` (entire Sections 2.1–2.5)
- **Issue:** Defines interfaces using Python `Protocol` classes and `@dataclass` with full Python syntax throughout (Document, DocumentStore, TextEmbedder, DocumentEmbedder, Retriever, Reranker, RAGPipeline).
- **Severity:** Low/medium. `Protocol` classes are interface definitions, not implementations. However, VISION requires YAML schemas only, not Python code of any form (AD 7). The spec also explains that "Backend implementations are adapted from existing open-source solutions."
- **Fix:** Express all interfaces as YAML schemas with method signatures described as contracts, not as Python Protocol classes with `def ... -> ...` and `...` bodies. Backend adapter mapping table (§4) is excellent and should be preserved.

### VIOL-7: agent-types spec uses Python Protocol classes
- **File:** `docs/specs/2026-06-18-agent-types.md` (Sections 2.1–2.2)
- **Issue:** Defines `ReadOnlyAgent`, `EscalationAgent` as Python `Protocol` classes with `@dataclass` result types.
- **Severity:** Same as VIOL-6.
- **Fix:** Express agent contracts as YAML schemas with method signatures described declaratively.

### VIOL-8: intent-classification spec lacks multiple implementation options
- **File:** `docs/specs/2026-06-16-intent-classification-design.md`
- **Issue:** VISION.md §3.2 requires "At least 2 implementation options per interface" with a comparison matrix. The intent classification spec was simplified in v0.6.0 to remove the keyword fallback, leaving only LLM-first as the single strategy.
- **Vision conflict:** VISION §3.2 item #2.
- **Fix:** Either (a) add a second implementation option (e.g., fine-tuned model vs. prompt-engineered model, or local model vs. cloud model), or (b) document that the single-strategy decision was made explicit with rationale, and note that the "two options" requirement is met by the LLM Gateway's alternative validation strategies (Option A/B/C for provider handling).

### VIOL-9: domain-model spec lacks alternative implementation options
- **File:** `docs/specs/2026-06-17-domain-model-design.md`
- **Issue:** The domain model adopts OpenAPI 3.1 Schema Objects as the single approach (AD 29). No alternative schema format is presented with a comparison matrix.
- **Severity:** Low. The decision to use OpenAPI 3.1 was an Architecture Decision with rationale. The spec could add a brief comparison: "Custom FieldDef (rejected — no tooling ecosystem)" vs. "JSON Schema Draft 2020-12 (rejected — less mature than OpenAPI 3.1 subset)" vs. "OpenAPI 3.1 (chosen)."
- **Fix:** Add a comparison table for schema format options, even if only to document why alternatives were rejected.

---

## Duplications

### DUP-1: Tool classification schema duplicated across three specs
- **Canonical owner:** **HLD §4.4** (`ToolMeta` schema) — this is the first definition and the broadest.
- **Duplicates:**
  - `docs/specs/2026-06-17-routing-execution-layer-design.md:825-857` (§7.3 Tool Classification) — full tool metadata YAML
  - `docs/specs/2026-06-17-tool-ecosystem.md:436-503` (§7.2 Tool Registration) — full tool registration YAML
- **Issue:** All three define `type: api | mcp | command | llm | a2a | sdk` and `access_level` with the same semantics. Routing §7.3 and Tool Ecosystem §7.2 add endpoint/timeout details that HLD §4.4 omits, but the core type enum and access_level taxonomy are triplicated.
- **Fix:** HLD §4.4 defines the canonical `ToolMeta.type` enum and `access_level` taxonomy. Routing §7.3 and Tool Ecosystem §7.2 should cross-reference HLD §4.4 and only add layer-specific detail (endpoints, timeouts, A2A/SDK specifics).

### DUP-2: errorNode strategies defined in two specs
- **Canonical owner:** **Routing & Execution §6.5**
- **Duplicates:**
  - `docs/specs/2026-06-17-routing-execution-layer-design.md:717-741` — 5 strategies with full descriptions
  - `docs/specs/2026-06-17-tool-ecosystem.md:527-548` (§7.4) — same 5 strategies (clarify, escalate, terminate) with tool-specific context
- **Issue:** The strategy enum and behavioral descriptions are repeated. Tool Ecosystem §7.4 adds tool-specific timeout/fallback configs which is fine as extension, but the strategy descriptions should cross-reference Routing §6.5.
- **Fix:** Tool Ecosystem §7.4 to reference Routing §6.5 for strategy definitions, only keeping tool-specific failure handling extensions.

### DUP-3: AgentState fields defined in multiple locations
- **Canonical owner:** **Domain Model §10.1** (full OpenAPI 3.1 AgentState schema)
- **Duplicates/partials:**
  - `docs/specs/2026-06-17-routing-execution-layer-design.md:408-415` (§4.2) — partial AgentState with phase and phase_stack
  - `docs/specs/2026-06-17-conversation-lifecycle.md:237-266` (§4.2) — checkpoint schema with agent_state_snapshot
- **Issue:** Not a direct duplication but fragmented mentions. The canonical AgentState is Domain Model §10.1, but other specs define subsets without cross-referencing.
- **Fix:** Ensure all AgentState mentions point to Domain Model §10.1 as the canonical definition.

### DUP-4: PII processing design split across two specs
- **Canonical owner:** **Response Generation §8** (post-generation scrubbing, prompt filtering, PII rules)
- **Duplicates:**
  - `docs/specs/2026-06-17-tool-ecosystem.md:1097-1111` (§9) — PII detection via Presidio
- **Issue:** This is correctly deduplicated (Tool Ecosystem §9 cross-references Response Generation §8 as "authoritative"), but the Domain Model spec mentions "PII rules (defined in domain model)" at §8 without pointing to Response Generation §8.2 where those rules are actually defined.
- **Fix:** Domain Model spec should cross-reference Response Generation §8.2 for PII rules.

---

## Semantic Conflicts

### CONF-1: Naming discrepancy between AD 30 "Three-pass" and extraction spec "Two-pass"
- **AD 30 (VISION.md:116):** "Three-pass per-state extraction scope: Pass 1 targeted extraction, Pass 2 global history scan, Pass 3 user confirmation."
- **Extraction spec §2.5:** Labels the approach as "Two-pass parallel extraction algorithm" where both LLMs run concurrently as "Pass 1" (narrow + broad), then "Pass 2: Merge & Resolve" (which includes confirmation).
- **Analysis:** Same algorithm, different counting. AD 30 counts the confirmation step as a separate pass (3 total). Extraction spec subsumes confirmation into Pass 2 (2 total). Users reading both will be confused.
- **Fix:** Align terminology. Use "Three-pass" everywhere (Pass 1: LLM 1 narrow, Pass 2: LLM 2 broad/scan, Pass 3: merge + confirm) OR rename AD 30 to match extraction spec's "two parallel + merge" terminology.

### CONF-2: Domain model §4.3 uses pre-OpenAPI field format
- **File:** `docs/specs/2026-06-17-domain-model-design.md:378-402` (§4.3 Example)
- **Issue:** The state definition example uses `entity: property_info` (flat custom FieldDef format), but AD 29 (VISION §6) states the domain model uses OpenAPI 3.1 Schema Objects. The correct format is shown in §2.2 with `x-state-bindings`.
- **Narrative:** After the OpenAPI migration (v0.5.0), the §4.3 example wasn't updated. It still shows the old flat format that was superseded.
- **Fix:** Update §4.3 to use the OpenAPI format: replace `entity: property_info` with `entity: PropertyInfo` (referencing `components/schemas/PropertyInfo`), and add `x-state-bindings`.

### CONF-3: Extraction spec ValidationRuleSchema not aligned with OpenAPI migration
- **File:** `docs/specs/2026-06-17-extraction-layer-design.md:593-604` (§6.2)
- **Issue:** `ValidationRuleSchema` uses a custom flat type system: `type: "int" | "float" | "string" | "date" | "boolean" | "enum"`. But AD 29 says validation should be derived from JSON Schema keywords (`type: integer/number/string/boolean`, `enum`, `minimum`/`maximum`, `pattern`, etc.).
- **Impact:** Two competing validation type systems in the framework: one defined in domain model (JSON Schema), another defined in extraction spec (custom flat types).
- **Fix:** Unify on JSON Schema types. The extraction spec should derive `ValidationRuleSchema` from the domain model's OpenAPI Schema Objects, not define a parallel type system.

### CONF-4: Eval threshold mismatch — VISION vs. CI/CD
- **VISION.md:148** (LLM Rules): "LLM decisions need evals — input/output test cases, ≥95% pass rate"
- **CI/CD spec gate thresholds:** `intent_accuracy >= 0.90`, `goal_check_pass_rate >= 0.85`, `schema_violation_rate <= 0.05`
- **Analysis:** The CI/CD gates are at 90%/85%, but VISION requires ≥95% pass rate. This is a direct conflict — the CI/CD pipeline would pass changes that violate the vision's quality bar.
- **Fix:** Either (a) raise CI/CD thresholds to match VISION (95%), (b) lower VISION's requirement to match CI/CD (90%), or (c) document that VISION's 95% is aspirational and CI/CD's thresholds are the current enforcement level, with a path to increase them.

---

## Naming Drift

### DRIFT-1: `collectedFields` (camelCase) vs `collected_fields` (snake_case)
- **CamelCase occurrences:**
  - `state-machine-design.md` §3.5: "collectedFields" in lifecycle execution order and set_field vs action table
  - `routing-execution-layer-design.md` §4.2: "collectedFields" in phase_stack example
  - `domain-model-design.md` §11.1: "collectedFields" in cross-entity data description
- **Snake_case occurrences:**
  - `domain-model-design.md:742-786` (§10.1 AgentState): "collected_fields" in OpenAPI schema definition
  - `extraction-layer-design.md:816`: "collectedFields" in edge case description
- **Canonical:** AD 29 adopts OpenAPI 3.1 Schema — all field names should follow JSON Schema conventions (snake_case or camelCase consistently). The AgentState schema uses `collected_fields`, `fieldExtractedList`, `last_active_at`. This is a mix of snake_case and camelCase within the same entity definition.
- **Fix:** Standardize on one convention for framework-level schemas. Recommendation: `snake_case` for all AgentState fields (matches Python convention and OpenAPI examples).

### DRIFT-2: `return_stack` vs `phase_stack` vs "phase return stack"
- **HLD §4.1:134-135:** "return stack tracks parent context"
- **Routing §4.1, §4.2:** "phase return stack" / `phase_stack`
- **State Machine §4.2:** `phase_stack` field name
- **Issue:** HLD calls it "return stack" without "phase" prefix. All other specs use "phase_stack" or "phase return stack." This is a fragment/abbreviation in the HLD that loses precision.
- **Fix:** Change HLD §4.1 to say "phase return stack" consistently.

### DRIFT-3: `goal_check` vs `goal_checker` vs `goal_check_422`
- **Response Generation §4:** Uses `goal_check` (config key), `goalChecker` (node name), `GoalCheckResult` (schema name)
- **Observability §3.3:** Uses `goal_check_422_rate` (metric name)
- **Issue:** The concept is the same but three naming patterns coexist: `goal_check`, `goalChecker`, `GoalCheck`. This is not confusing but is inconsistent.
- **Fix:** Standardize: use `goal_check` for configuration keys, `goal_checker` for node identification, `GoalCheckResult` for data schemas. Document the convention.

### DRIFT-4: `errorNode` vs `ErrorNode` (resolved)
- **Status:** Fully resolved. All specs now use `errorNode` (camelCase) consistently after v0.5.0 updates.
- **Evidence:** Routing §6.5, State Machine §3.1, Tool Ecosystem §2.2, LLM Gateway §8 all use `errorNode`.
- **No action needed.**

### DRIFT-5: `extract_strategy` value names
- **Extraction spec §6.5:** `extract_strategy: llm_primary | deterministic | hybrid`
- **LLM Gateway spec Option descriptions:** Uses "LLM-Primary", "Deterministic", "Hybrid" in comparison matrices
- **Issue:** YAML values use `llm_primary` (snake_case), prose uses "LLM-Primary" (title case with hyphen). Consistent but could be confusing when searching.
- **Fix:** Document the canonical YAML value names in the comparison matrix headers.

---

## Version Skew

### SKEW-1: Domain model spec not fully migrated to OpenAPI 3.1
- **File:** `docs/specs/2026-06-17-domain-model-design.md`
- **Migrated (v0.5.0):** Section 2 (Domain Model Schema), Section 2.2 (Home Insurance example), Section 3 (Entity Definition)
- **Not migrated:** Section 4.3 (State example) still uses `entity: property_info` flat format. Section 5.1 (IntentDef) still uses flat field format without OpenAPI alignment.
- **Fix:** Update Sections 4.3 and 5.1 to use `$ref` references to `components/schemas/` entities.

### SKEW-2: Extraction spec still references pre-OpenAPI extraction rules
- **File:** `docs/specs/2026-06-17-extraction-layer-design.md`
- **Issue:** Section 6.1 (ExtractionRuleSchema) uses `fallback_pattern`, `fallback_keywords`, `examples` as flat fields. After AD 29, these should be derived from `components/schemas/` properties with `x-fallback`, `x-transform`, `x-examples` extensions as defined in Domain Model §3.
- **Fix:** Update ExtractionRuleSchema to reference Domain Model §3 for how rules are derived from OpenAPI Schema Objects.

### SKEW-3: VISION.md document tree does not include new specs
- **File:** `docs/VISION.md:216-242` (§9 Document Tree)
- **Missing:** `2026-06-18-rag-interface.md` and `2026-06-18-agent-types.md` are not listed in the VISION document tree, even though both files exist and reference the HLD.
- **Fix:** Add rag-interface and agent-types to VISION §9.

### SKEW-4: HLD Related Design Documents missing new specs
- **File:** `docs/specs/2026-06-16-deterministic-workflow-framework-design.md:190-209` (§5)
- **Missing:** `2026-06-18-rag-interface.md` and `2026-06-18-agent-types.md` are not listed in Related Design Documents, even though they're in the Document Tree (§8).
- **Fix:** Add both specs to §5. The Document Tree (§8:261-262) was updated in v0.9.0 but §5 was not.

### SKEW-5: VISION §3.1 task list missing new deliverables
- **File:** `docs/VISION.md:36-44` (§3.1)
- **Missing:** RAG Interface and Agent Types are not checked off in the tasks list. Both specs exist in the `docs/specs/` directory.
- **Fix:** Add `[x] RAG Interface`, `[x] Agent Types` to VISION §3.1.

---

## Missing Cross-References

### XREF-1: HLD §5 does not list rag-interface or agent-types
- **File:** `docs/specs/2026-06-16-deterministic-workflow-framework-design.md:190-209`
- **Issue:** RAG and Agent Types specs exist and are children of HLD but are not cross-referenced in §5 Related Design Documents.
- **Fix:** Add entries for both specs.

### XREF-2: RAG interface spec does not cross-reference Agent Types
- **File:** `docs/specs/2026-06-18-rag-interface.md`
- **Issue:** The RAG pipeline is the primary backend for `ReadOnlyAgent` (agent-types.md:55-57 explicitly states this), but rag-interface.md does not cross-reference agent-types.md.
- **Fix:** Add "Agent Types" to rag-interface References section.

### XREF-3: Agent Types spec does not cross-reference Tool Ecosystem explicitly
- **File:** `docs/specs/2026-06-18-agent-types.md`
- **Issue:** Agent permission model (§4) references tool allowlists without pointing to Tool Ecosystem §7.5 (A2A tool type) and §7.6 (SDK tool type), which are the mechanisms for registering agent-capability tools.
- **Fix:** Add Tool Ecosystem reference to §4 and References.

### XREF-4: Domain Model PII reference is imprecise
- **File:** `docs/specs/2026-06-17-domain-model-design.md:581`
- **Issue:** Says "PII rules (defined in domain model)" but the actual PII rules are in Response Generation §8.2, not in the domain model spec itself.
- **Fix:** Change to "PII rules (see Response Generation §8.2)" and clarify that PII field annotations are defined alongside entity properties in the domain model's `pii_rules` section.

### XREF-5: Rate limiting spec missing LLM Gateway cross-reference
- **File:** `docs/specs/2026-06-17-rate-limiting.md`
- **Issue:** §2.4 defines per-tool rate limits for `llm_call` but doesn't reference LLM Gateway §4 (progressive model escalation) which also manages LLM call budgets.
- **Fix:** Add cross-reference: "LLM Gateway §4 manages per-call model escalation; this section manages aggregate call frequency limits."

### XREF-6: Widget Templates spec missing Environment Config cross-reference
- **File:** `docs/specs/2026-06-17-widget-templates.md`
- **Issue:** Theme configuration (§2.5) defines colors, fonts, etc. without referencing how these differ across dev/e2e/prod environments.
- **Fix:** Add cross-reference to Environment Config for per-environment UI theme overrides.

---

## Missing Coverage (Vision requirements not in any spec)

### COV-1: No dedicated LLM eval framework spec
- **Vision requirement:** VISION.md §6.3 "LLM decisions need evals — input/output test cases, ≥95% pass rate"
- **Current coverage:** Partial. CI/CD spec §4 defines eval gates and mock/real strategies. Observability spec defines metrics. Response Gen spec §3.3 defines prompt eval cases.
- **Gap:** There is no dedicated spec that defines:
  - How eval test cases are authored and structured
  - How the ≥95% pass rate is measured at a per-decision-node level (not just intent accuracy)
  - What constitutes a "pass" for extraction decisions vs. routing decisions vs. classification decisions
  - How eval datasets are maintained alongside workflow definitions
- **Severity:** Medium. The CI/CD pipeline enforces thresholds, but the EVAL FRAMEWORK — the contracts, schemas, and methodology — is distributed across multiple specs without a single canonical definition.

### COV-2: Human-in-the-loop approval UI not defined
- **Vision reference:** HLD §Appendix A.3 lists "Approval UI design" and "Approval timeout" as open questions (lines 296-298).
- **Coverage status:** Permission model (§7.3 in Routing) mentions `requires_approval: true` and `await_human_approval`. But there is no spec defining:
  - What the approver sees (the `review_prompt` schema)
  - What data the approver can modify
  - Approval timeout behavior
  - Delegation chain
- **Severity:** Low. Deferred in HLD appendix as open questions. But if the framework is to be adopted in regulated industries, approval workflows are critical.
- **Recommendation:** Either (a) create a short spec for Human-in-the-Loop interfaces, or (b) explicitly mark this as out-of-scope for framework v1.0.

### COV-3: Multi-tenant isolation architecture not defined
- **Vision reference:** HLD §Appendix A.5 lists "Multi-tenant isolation" as an open question (line 313).
- **Current coverage:** Auth spec §6 mentions flagging tenant_id from JWT claims. Conversation lifecycle scopes checkpoints to tenant. But no spec defines:
  - How tenant isolation is enforced at the engine level (separate LangGraph instances? namespace partitioning?)
  - Resource quotas per tenant
  - Cross-tenant data leakage prevention
- **Severity:** Medium. For SaaS deployments, this is critical. Currently scattered across auth, lifecycle, and deployment configs.

### COV-4: VISION document tree in §9 does not include all spec files
- **Issue:** VISION.md §9 lists 17 files but `rag-interface.md` and `agent-types.md` exist under `docs/specs/`. The VISION as master reference is incomplete.
- **Fix:** Update VISION §9 with all current files.

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Vision Violations | 9 |
| Duplications | 4 |
| Semantic Conflicts | 4 |
| Naming Drift | 5 |
| Version Skew | 5 |
| Missing Cross-References | 6 |
| Missing Coverage | 4 |
| **Total** | **37** |

### Priority Ranking

1. **CRITICAL (block implementation):**
   - CONF-4: Eval thresholds don't match VISION (90% vs 95%)
   - CONF-2: Domain model uses pre-OpenAPI format in examples
   - VIOL-1/2/3/4: Implementation code in extraction spec

2. **HIGH (causes confusion):**
   - CONF-1: Three-pass vs two-pass naming in AD 30
   - CONF-3: Two competing validation type systems
   - SKEW-1: Domain model not fully migrated to OpenAPI
   - SKEW-3: VISION tree missing new specs

3. **MEDIUM (cleanup needed):**
   - DUP-1/2/3: Duplication across specs
   - DRIFT-1: camelCase vs snake_case in AgentState
   - COV-1: No eval framework spec

4. **LOW (nice to have):**
   - XREF-1 through XREF-6: Missing cross-references
   - DRIFT-2 through DRIFT-5: Minor naming inconsistencies
