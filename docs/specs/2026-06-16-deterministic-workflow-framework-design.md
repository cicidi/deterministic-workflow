# Deterministic Workflow Framework — High-Level Design

**Design Scope:** Architecture discussions only. No implementation code.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | Initial three-layer architecture |
| 2026-06-16 | 0.2.0 | Reset to minimal version for step-by-step discussion |
| 2026-06-16 | 0.3.0 | Add cross-reference to state machine design; translate appendix to English |
| 2026-06-16 | 0.4.0 | Add examples reference; unify all examples under home insurance domain |
| 2026-06-17 | 0.5.0 | Add framework design principles (conventions, JSON guardrails, permission model) |
| 2026-06-17 | 0.6.0 | Term consistency: errorNode, phase-aware routing; add YAML schema overview; mark resolved open questions |
| 2026-06-17 | 0.7.0 | Add Context Hydration layer: pre-processing step loads history, state, session, external entities before three-layer execution |
| 2026-06-17 | 0.8.0 | Update Related Design Documents with all child specs; add Document Tree section; fill missing table cell |
| 2026-06-18 | 0.9.0 | Update `ToolMeta.type` enum to include `a2a` and `sdk` per Decision 24; sync document tree with latest specs |

---

## 1. Problem Statement

Enterprise chatbots in regulated industries (finance, health, insurance) need to be auditable and predictable—but users speak natural language. A purely rule-based system can't understand users; a purely LLM-driven system can't guarantee correctness.

## 2. Core Architecture: Context Hydration + Three Layers

Every workflow interaction begins with a **Context Hydration** step that loads the latest data relevant to the current business state. It does NOT call all APIs blindly — it selectively refreshes `AgentState` with data the current task actually needs.

```
User Input
   |
   v
+-----------------------+
| Context Hydration      |  -> "What data does this task need right now?"
| Selectively refresh    |     Load only business-relevant data:
| AgentState data        |     e.g., insurance application form data
+-----------+-----------+     to determine the next task step
            v
+-----------------------+
| Layer 1: UNDERSTAND   |  -> "What does the user want?"
| Intent + Entities     |
+-----------+-----------+
            v
+-----------------------+
| Layer 2: DECIDE        |  -> "What should we do?"
| Routing + Execution    |
+-----------+-----------+
            v
+-----------------------+
| Layer 3: RESPOND       |  -> "What do we say back?"
| Message Generation     |
+-----------------------+
```

- **Context Hydration** selectively loads the latest data needed by the current business task — refreshing `AgentState` with current application form data, claim status, or payment history — so the framework knows exactly what the next step should be. It does NOT load unrelated CRM entities or exhaust all available APIs.
- **Layer 1** extracts intent and structured entities from free-form user input.
- **Layer 2** decides the next state, validates data, and performs deterministic business logic.
- **Layer 3** produces the user-visible response.

### 2.1 YAML Schema Overview (Context Hydration + Three Layers)

```yaml
workflow:
  context_hydration:
    always_load:           # always refreshed every turn
      - source: checkpoint_db
        fields: [conversation_history, persisted_agentState]
      - source: session_store
        fields: [user_profile, oauth_scopes]
    on_phase_entry:        # refreshed when entering this phase
      collect_property_info:
        - source: application_service   # load current application form
          fields: [property_type, address, building_age, floor_area]
      process_claim_payment:
        - source: claims_gateway
          fields: [claim_amount, coverage_details]
  layers:
    understand:
      nodes: [classify_intent, extract_entities]
    decide:
      nodes: [route, validate, execute, fallback]
    respond:
      nodes: [generate_response]
  mode: deterministic
```

### 2.2 Context Hydration — How It Works

Context Hydration is **selective** — it only refreshes data that the current business task depends on. The framework determines what to load based on the current `agentState.phase` and the entity bindings in the domain model.

**Example (insurance quote):**

```
agentState.phase = "collect_coverage_needs"
    → domain model state binds entity: "property_info"
    → load current application form data for property_info
    → detect: property_type = "house", building_age = 5, address = null
    → determine next task: ask for address
```

**Not loaded:** CRM history, payment data, claim records — irrelevant to the quote task. Only the application form fields for the current phase are refreshed.

**Hydration Sources:**

| Source | When Loaded | What's Hydrated |
|--------|------------|-----------------|
| **Checkpoint DB** | Every turn | Conversation history + persisted `AgentState` |
| **Session Store** | Every turn | User profile, OAuth scopes |
| **Domain Entity API** | On phase entry | Current entity data for the bound entity (e.g., application form state) |
| **External Business API** | Conditional | Only when a node's code executor declares a dependency (e.g., `claims_gateway` in `process_claim_payment` state) |

## 3. Key Insight: Per-Node Control, Not Per-Layer

The LLM/deterministic decision is not made at the layer level. Each individual node within each layer independently chooses whether to use LLM or deterministic rules.

For example, within Layer 2, a routing node might be a pure `switch` statement (deterministic), while the node next to it might use LLM for semantic validation (LLM). Layers describe *what* happens; nodes describe *how*.

## 4. Framework Design Principles

### 4.1 Framework as Interface + Pattern Injection

The framework exposes clean interfaces for developers to implement business logic. Internally, it injects proven patterns that handle the "dirty work" — so the developer focuses on business logic, not infrastructure:

| Framework Concern | Patterns Injected |
|-------------------|-------------------|
| LLM guardrails | JSON schema validation, field presence check, type coercion |
| Permission enforcement | Per-node tool allowlist + transition allowlist |
| Retry budgets | Per-node retry count + errorNode unified handling |
| Audit trail | Every decision, extraction, and transition logged |
| Deterministic fallback | Regex/keyword fallback for every extractable field |
| State awareness | Current FSM state injected into every LLM prompt |
| Phase-aware routing + phase return stack | Current FSM phase injected into routing decisions; phase return stack tracks parent context when sub-workflows complete, enabling seamless resume |
| Sub-workflow reuse | Shared capabilities defined once, invoked from any state |

All LLM interactions produce structured JSON output with framework-enforced guardrails (schema check, field presence, type coercion). Free-text generation is limited to Layer 3.

**Interface philosophy:** The developer implements `ExtractionNode.execute()`, `ValidatorNode.validate()`, `TransformNode.transform()`, etc. The framework handles everything around it.

### 4.2 Code Conventions

- Every method ≤ **50 lines**
- Every file ≤ **1000 lines**
- Executors are small, composable, and single-responsibility
- Complex sub-workflows split across files and sub-workflows
- Reusable logic extracted into shared modules

### 4.3 LLM Output is JSON — Always

All LLM interactions produce **structured JSON output**. The framework enforces output validation guardrails:

1. **Schema check** — output must match the declared JSON schema
2. **Field presence** — required fields must be present and non-null
3. **Type coercion** — `"123"` → `123` when schema expects `int`
4. **Retry on violation** — invalid output auto-retries (within retry budget)

Free-text generation is limited to **Layer 3 (Response)**. Layer 1 and Layer 2 LLM outputs are always structured JSON.

### 4.4 Permission Model (Overview)

Every node has a permission set defining what it can access:

```
NodePermission {
  allowed_tools:      string[]    // which tools this node can call
  allowed_transitions: string[]   // which nodes this node can transition to
  max_retries:        int         // retry budget for this node
}
```

Tools are categorized with metadata:

```
ToolMeta {
  name:        string
  type:        "api" | "mcp" | "command" | "llm" | "a2a" | "sdk"
  access_level: "read" | "write" | "sensitive_data_read" | "dangerous_operation_write"
  execute():   Result        // tool execution method
}
```

Permission enforcement happens at two levels:

1. **Config-level** — statically declared in workflow YAML (node/tool allowlists)
2. **OAuth / Role-based** — dynamic enforcement based on authenticated user's role at runtime

Detailed permission design in [Routing & Execution Layer](./2026-06-17-routing-execution-layer-design.md).

## 5. Related Design Documents

- **[State Machine Design](./2026-06-16-state-machine-design.md)** — Detailed FSM layer design: transitions + LangGraph fusion, state metadata (preconditions, guards, invariants), intent+state resolution, and FSM-specific open questions.
- **[Intent Classification Design](./2026-06-16-intent-classification-design.md)** — Layer 1 intent classification strategy: LLM-first, confidence threshold, 17 system intents, multi-intent detection.
- **[Extraction Layer Design](./2026-06-17-extraction-layer-design.md)** — Layer 1 entity extraction: Extract/Validate/Transform pipeline with multiple implementation options.
- **[Domain Model Design](./2026-06-17-domain-model-design.md)** — Single source of truth: Entity + State + Transition schemas, cross-workflow reuse.
- **[Routing & Execution Layer Design](./2026-06-17-routing-execution-layer-design.md)** — Layer 2 routing and execution: business logic, decision nodes, phase-aware routing, retry budgets, sub-workflow reuse, permission model.
- **[Response Generation Layer Design](./2026-06-17-response-generation-layer-design.md)** — Layer 3 response generation: message composition, widget rendering, PII scrubbing.
- **[LLM Gateway](./2026-06-17-llm-gateway.md)** — Gatekeeper for all LLM calls: schema validation, retry, timeout, cost tracking, provider routing.
- **[Tool Ecosystem](./2026-06-17-tool-ecosystem.md)** — Visual editor (LangFlow), rule engines, MCP servers, PII detection (Presidio), LLM providers, pycasbin permission enforcement.
- **[Environment Config](./2026-06-17-environment-config.md)** — Multi-environment configuration: dev, e2e, prod settings, secrets management, feature flags.
- **[Auth & Token Verification](./2026-06-17-auth-token-verification.md)** — Authentication and token verification: OAuth scopes, session tokens, role-based access.
- **[MCP API Protocol](./2026-06-17-mcp-api-protocol.md)** — MCP API protocol specification: tool discovery, invocation patterns, server lifecycle.
- **[A2A Protocol](./2026-06-17-a2a-protocol.md)** — Agent-to-Agent protocol: inter-agent communication, message routing, agent coordination.
- **[Conversation Lifecycle](./2026-06-17-conversation-lifecycle.md)** — Conversation lifecycle management: creation, pause/resume, checkpoint, archival, termination.
- **[Observability & Monitoring](./2026-06-17-observability-monitoring.md)** — Metrics, tracing, alerting, Grafana dashboards, LangSmith integration.
- **[CI/CD Pipeline](./2026-06-17-cicd-jenkins-pipeline.md)** — Automated validation, evaluation, build, and deployment pipeline with gated environment promotion.
- **[Rate Limiting](./2026-06-17-rate-limiting.md)** — Rate limiting strategy: per-user, per-workflow, per-LLM-provider throttling.
- **[Widget Templates](./2026-06-17-widget-templates.md)** — Widget template system: structured UI components for Layer 3 responses.
- **[RAG Interface](./2026-06-18-rag-interface.md)** — Retrieval-Augmented Generation abstraction: Document, DocumentStore, Embedder, Retriever, RAGPipeline interfaces with backend adapters.
- **[Agent Types](./2026-06-18-agent-types.md)** — Specialized execution agents (ReadOnlyAgent, EscalationAgent) dispatched by the state machine for specific intent categories.
- **[Home Insurance Examples](../examples/home-insurance/)** — Complete workflow definition (`workflow.yaml`), intent catalog, end-to-end scenarios, and audit log sample.

## 6. Downstream: Skill-Assisted Spec Generation

This spec document suite serves a dual purpose:

1. **Framework design reference** — documents the deterministic workflow architecture and design decisions
2. **Interview template** — a downstream skill loads these specs and, through guided Q&A, helps a developer produce a complete product-specific deterministic AI agent specification, ready for code implementation planning

```
Developer describes their product (e.g., "insurance claims chatbot")
    → Skill loads framework specs as interview template
    → Skill asks product-specific, spec-by-spec questions
    → Skill outputs a complete, product-specific spec
    → Developer proceeds to implementation planning
```

The framework specs are designed with clear decision boundaries: **"framework decision"** (reused across all products) vs. **"user decision"** (asked by the skill per product). The interview flow will be formalized after all spec documents are complete.

---

## 7. References

1. LangGraph — State graph execution framework (runtime substrate). *github.com/langchain-ai/langgraph*
2. Rasa CALM — "The LLM understands; the code enforces." *rasa.com*
3. zelkim/langgraph-insurance-chatbot — LangGraph.js insurance quote chatbot. *github.com/zelkim/langgraph-insurance-chatbot*
4. Prodigal Payment Collection Agent — Python FSM payment agent. *github.com/AvnishChitrigi/Prodigal-Assignment-Production-Ready-Payment-Collection-AI-Agent*

---

## 8. Document Tree

```
docs/
├── specs/
│   ├── 2026-06-16-deterministic-workflow-framework-design.md  ← This document (HLD)
│   ├── 2026-06-16-state-machine-design.md
│   ├── 2026-06-16-intent-classification-design.md
│   ├── 2026-06-17-extraction-layer-design.md
│   ├── 2026-06-17-domain-model-design.md
│   ├── 2026-06-17-routing-execution-layer-design.md
│   ├── 2026-06-17-response-generation-layer-design.md
│   ├── 2026-06-17-llm-gateway.md
│   ├── 2026-06-17-tool-ecosystem.md
│   ├── 2026-06-17-environment-config.md
│   ├── 2026-06-17-auth-token-verification.md
│   ├── 2026-06-17-mcp-api-protocol.md
│   ├── 2026-06-17-a2a-protocol.md
│   ├── 2026-06-17-conversation-lifecycle.md
│   ├── 2026-06-17-observability-monitoring.md
│   ├── 2026-06-17-cicd-jenkins-pipeline.md
│   ├── 2026-06-17-rate-limiting.md
│   ├── 2026-06-17-widget-templates.md
│   └── zh/
├── examples/
│   └── home-insurance/
└── skills/
    └── (skill definitions for downstream spec generation)
```

---

## Appendix: Implementation Planning — Open Questions (Non-State-Machine)

> Questions identified during design but deferred for implementation planning.
> For state machine specific questions, see [State Machine Design](./2026-06-16-state-machine-design.md) Appendix C.

### A.1 LLM Integration

| # | Question | Impact |
|---|----------|--------|
| 1 | LLM node error handling — recovery strategies for timeout, hallucination, tool call failure | Conversation continuity |
| 2 | LLM node testing — how to verify behavior without real LLM calls | Test stability, CI speed |
| 3 | LLM scope enforcement — how to ensure LLM only handles Layer 1 (understanding) and Layer 3 (response), not Layer 2 (decisions) | Addressed by Decision 5: per-node granularity, not per-layer enforcement |
| 4 | Context filtering — what data can be passed to LLM, sensitive field masking rules | PII/GDPR compliance |

### A.2 Security & Compliance

| # | Question | Impact |
|---|----------|--------|
| 5 | Tool permissions — who can call what tool in which state, allowlist granularity and management | Prevent LLM overreach |
| 6 | PII handling — tokenization, encryption in transit, storage strategy | PCI DSS / SOC2 / GDPR |

### A.3 Human-in-the-Loop

| # | Question | Impact |
|---|----------|--------|
| 7 | Approval UI design — what the approver sees, whether they can modify data | Approval effectiveness |
| 8 | Approval timeout — auto-approve, reject, or delegate when approver is unavailable | Business continuity |
| 9 | Approval delegation chain — who to escalate to and in what order | Organizational fit |

### A.4 Testing & Quality

| # | Question | Impact |
|---|----------|--------|
| 10 | Deterministic node (code executor) unit testing strategy | Core business logic correctness |
| 11 | Generated graph integration testing — how to verify auto-generated LangGraph behavior | End-to-end correctness |

### A.5 Deployment & Operations

| # | Question | Impact |
|---|----------|--------|
| 12 | Blue-green deployment — routing conversations when old and new workflows coexist | Zero-downtime updates |
| 13 | Multi-tenant isolation — how to isolate workflow instances across customers | Security, resource management |
| 14 | Audit log storage — format, retention period, query API | Regulatory compliance review |
