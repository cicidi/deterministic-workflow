# Mega Review Summary — All 20 Spec Files

- **Date:** 2026-06-18
- **Scope:** 20 spec files, 5 agents (Agent 0 Vision + Agent 1 Contrarian + Agent 2 Reviewer × 3 batches)
- **Total issues:** 161

---

## Issue Distribution by Agent

| Agent Batch | Files | Issues |
|-------------|-------|--------|
| Agent 0 (Vision + Cross-Doc) | ALL 20 | 37 |
| Agent 1 Core Design | 5 (HLD, State Machine, Intent, Domain Model, Extraction) | 15 |
| Agent 2 Core Design | 5 | 35 |
| Agent 1 Execution | 5 (Routing, Response, Tools, A2A, MCP) | 11 |
| Agent 2 Execution | 5 | 18 |
| Agent 1 Ops/Remaining | 9 (Env Config, Auth, Conv, Obs, CI/CD, Rate Limit, Widgets, RAG, Agent Types) | 17 |
| Agent 2 Ops/Remaining | 9 | 28 |
| **Total** | | **161** |

---

## Critical Issues (must fix now)

### C1: Implementation code in extraction spec (Agent 0 VIOL-1–4)
- **File:** `extraction-layer-design.md:325-426, 846-859`
- **Problem:** Contains Python `@dataclass` definitions, `validate_payload_fields` function, `INTENT_PAYLOAD_MAP` dict, `build_extraction_result` function, `LLMAuditRecord` dataclass. Violates VISION.md §4.1 "No implementation code yet."
- **Fix:** Replace all Python code with YAML/OpenAPI schema declarations.

### C2: agentState.phase value mismatch (Agent 2 Core Design)
- **File:** `intent-classification-design.md` vs `state-machine-design.md`
- **Problem:** Intent Classification uses categories like `quoting` for `agentState.phase`; State Machine uses state names like `collect_property_info`. This would cause runtime failures — the state machine can't find a state named `quoting`.
- **Fix:** Align phase values. Either have Intent Classification output state-machine-navigable phase names, or add a phase→state mapping layer.

### C3: errorNode has no single canonical definition (Agent 2 Core Design)
- **Files:** Defined in 4 different specs with slightly different descriptions
- **Problem:** Routing §6.5 lists 5 strategies; Tool Ecosystem §7.4 lists same 5 but with different wording; LLM Gateway §8 shows audit structure; State Machine §3.1 shows routing logic.
- **Fix:** Choose one owner (Routing §6.5). All others must cross-reference.

### C4: Eval threshold mismatch — VISION vs CI/CD (Agent 0 CONF-4)
- **VISION.md:** "≥95% pass rate"
- **CI/CD:** `intent_accuracy >= 0.90`, `goal_check_pass_rate >= 0.85`
- **Problem:** CI/CD pipeline passes changes that violate VISION's quality bar.
- **Fix:** Raise CI/CD thresholds to 95% or document the gap as aspirational vs. current.

### C5: Domain model §4.3 not migrated to OpenAPI (Agent 0 CONF-2)
- **File:** `domain-model-design.md:378-402`
- **Problem:** Still uses old flat `entity: property_info` format after OpenAPI migration (AD 29).
- **Fix:** Update to `$ref` references to `components/schemas/PropertyInfo`.

### C6: Parallel 2x LLM extraction unsupported by evidence (Agent 1 Core Design)
- **File:** `extraction-layer-design.md`
- **Problem:** The "two-pass parallel extraction" runs 2 LLM calls simultaneously on every extraction. No research cited showing this doubles accuracy or reduces latency. Cost is 2x for uncertain benefit.
- **Evidence:** Agent 1 found no industry pattern using parallel LLMs for the same extraction task.
- **Fix:** Add evidence citation or make parallel extraction optional/configurable.

---

## Semantic Conflicts

| # | Docs | Problem |
|---|------|---------|
| CONF-1 | VISION vs Extraction | "Three-pass" (AD 30) vs "Two-pass parallel" naming |
| CONF-2 | Domain Model | §4.3 uses pre-OpenAPI format, rest of spec migrated |
| CONF-3 | Extraction vs Domain Model | `ValidationRuleSchema` uses custom types vs JSON Schema types |
| CONF-4 | VISION vs CI/CD | 95% vs 90%/85% eval thresholds |
| CONF-5 | Routing vs Tools | Reducer rule contradiction — Routing says "best wins", Tools says "first match" |

## Duplications

| # | Canonical Owner | Duplicated In |
|---|----------------|---------------|
| DUP-1 | HLD §4.4 `ToolMeta` | Routing §7.3, Tool Ecosystem §7.2 |
| DUP-2 | Routing §6.5 errorNode strategies | Tool Ecosystem §7.4 |
| DUP-3 | Domain Model §10.1 AgentState | Routing §4.2, Conversation Lifecycle §4.2 |
| DUP-4 | Response Generation §8 PII | Domain Model §8 (incorrect pointer) |

## Naming Drift

| Concept | Variants | Recommended |
|---------|----------|-------------|
| collected fields | `collectedFields`, `collected_fields` | `collected_fields` (snake_case) |
| return stack | `return_stack`, `phase_stack`, "phase return stack" | `phase_stack` |
| goal check | `goal_check`, `goalChecker`, `GoalCheckResult` | `goal_check` (config), `goal_checker` (node) |
| extract strategy | `llm_primary`, "LLM-Primary" | `llm_primary` (YAML), "LLM-Primary" (prose) |

## Version Skew

| # | File | Problem |
|---|------|---------|
| SKEW-1 | Domain Model §4.3, §5.1 | Pre-OpenAPI format not updated |
| SKEW-2 | Extraction §6.1 | Pre-OpenAPI extraction rules |
| SKEW-3 | VISION §9 | Missing rag-interface and agent-types |
| SKEW-4 | HLD §5 | Missing rag-interface and agent-types |
| SKEW-5 | VISION §3.1 | Task list missing RAG and Agent Types |

## Missing Cross-References

| # | From | Should Reference |
|---|------|-----------------|
| XREF-1 | HLD §5 | rag-interface, agent-types |
| XREF-2 | RAG Interface | Agent Types |
| XREF-3 | Agent Types | LLM Gateway |
| XREF-4 | Rate Limiting | LLM Gateway (escalation impact) |
| XREF-5 | A2A Protocol | Tool Ecosystem (A2A as tool type) |
| XREF-6 | LLM Gateway errorNode | Routing §6.5 (canonical strategies) |

## Agent 1 Key Findings (Alternatives from Web)

| # | File | Best Alternative Found |
|---|------|----------------------|
| 1 | State Machine | CrewAI Flows as LangGraph alternative |
| 2 | Intent Classification | Cascade (keyword-first, LLM second) as cheaper alternative |
| 3 | Routing/Execution | Temporal.io for durable execution (vs LangGraph checkpoints) |
| 4 | Permissions | OPA/OpenFGA for fine-grained authorization (vs custom allowlists) |
| 5 | Extraction | Instructor library for Pydantic-based validation |
| 6 | Domain Model | Pydantic v2 as Python-native alternative to OpenAPI |
| 7 | Env Config | 12-factor app config patterns |
| 8 | CI/CD | Trunk-Based Development (Google, Facebook standard) |
| 9 | A2A | Google A2A open standard (vs custom protocol) |
| 10 | Observability | OpenTelemetry standard (vs LangSmith-only) |

## Agent 2 Key Findings (Correctness/Completeness)

| # | File | Issue |
|---|------|-------|
| 1 | State Machine | Reducer rule contradiction (best wins vs first match) |
| 2 | Routing | Missing conversation-level retry budget |
| 3 | Routing | Sub-workflow deadlock risk (circular invocation) |
| 4 | Response Generation | PII bypass in raw messages |
| 5 | Tool Ecosystem | `tool_allowlist` vs `allowed_tools` naming conflict |
| 6 | Conversation | Checkpoint race condition on concurrent updates |
| 7 | Auth | Token verification order undefined (JWT before OAuth?) |
| 8 | Observability | Missing metric for escalation rate per tier |
| 9 | Rate Limiting | No per-LLM-provider quota tracking |
| 10 | Widget Templates | No accessibility/ARIA requirements |

---

## Files by Review Completeness

| File | Agent 0 | Agent 1 | Agent 2 | Issues Found |
|------|---------|---------|---------|-------------|
| HLD | partial | done | done | VIS issues, ref gaps |
| State Machine | partial | done | done | Reducer conflict, SCXML concern |
| Intent Classification | done | done | done | phase mismatch, single-option |
| Domain Model | done | done | done | OpenAPI migration incomplete |
| Extraction Layer | done | done | done | **Implementation code**, parallel LLM |
| Routing/Execution | done | done | done | errorNode dup, sub-workflow deadlock |
| Response Generation | done | done | done | PII bypass, goal check naming |
| LLM Gateway | done | done (v0.3.1) | done (v0.3.1) | Already reviewed |
| Tool Ecosystem | done | done | done | ToolMeta dup, tool_allowlist naming |
| A2A Protocol | done | done | done | Custom vs Google A2A standard |
| MCP Protocol | done | done | done | Missing agent types ref |
| Environment Config | done | done | done | 12-factor gaps |
| Auth/Token | done | done | done | Verification order |
| Conversation Lifecycle | done | done | done | Checkpoint race condition |
| Observability | done | done | done | Missing escalation metric |
| CI/CD Jenkins | done | done | done | Threshold mismatch |
| Rate Limiting | done | done | done | Per-provider quota |
| Widget Templates | done | done | done | No accessibility reqs |
| RAG Interface | done | done | done | Python Protocol classes |
| Agent Types | done | done | done | Implementation code, missing refs |

---

## Recommended Fix Order

1. **Immediate (blocking):** C1 (remove Python code from extraction spec), C2 (fix phase value mismatch)
2. **High (cross-document):** C3 (canonical errorNode), C4 (eval thresholds), CONF-1 through CONF-5, DUP-1 through DUP-4
3. **Medium (improvements):** Naming drift fixes, version skew updates, missing cross-references
4. **Low (deferred):** Agent 1 alternative suggestions (Pydantic, Temporal, OpenTelemetry, etc.)
