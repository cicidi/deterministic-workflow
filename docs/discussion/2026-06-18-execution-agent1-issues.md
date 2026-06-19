# Agent 1 — Web-Searching Contrarian Review: Execution Specs

> **Role:** Identify missed alternatives, wrong approaches, weak rationales, and outdated patterns by comparing against current industry practice.
> **Specs reviewed:** Routing & Execution, Response Generation, Tool Ecosystem, A2A Protocol, MCP API Protocol
> **Date:** 2026-06-18

---

## 1. missing_alternative — Custom A2A Format vs Google A2A Protocol Standard

**Affected:** `a2a-protocol.md` §2.2; `routing-execution-layer-design.md` §5

The spec defines a **custom A2A message format** (a2a_request/a2a_response YAML schemas with `goal`, `entities`, `constraints`). Meanwhile, the **Google A2A Protocol** (`github.com/a2aproject/A2A`, 24.4k stars, Apache 2.0, Linux Foundation project) defines a competing standard with:

- `AgentCard` for capability advertisement (not a custom registry schema)
- JSON-RPC 2.0 over HTTP (not custom wire format)
- `tasks/send`, `tasks/get`, `tasks/cancel` primitives (not `invoke` endpoint)
- `TaskStatus` with `working`, `input-required`, `completed`, `failed`, `canceled` states (different semantic model)
- Support for `Message` and `Part` types for multi-modal content
- Streaming via SSE (built into the protocol)

The spec references Google A2A in §References but **does not adopt its wire format**. Instead it invents a parallel format. The industry is coalescing around Google A2A — Anthropic, LangChain, CrewAI, and Cloudflare all announced A2A support. Building a custom A2A format means this framework will need an adapter layer to interoperate with the broader agent ecosystem.

**URLs:**
- https://github.com/a2aproject/A2A
- https://a2a-protocol.org/latest/specification/

**Recommendation:** Adopt Google A2A as the wire protocol; map sub-workflow definitions to AgentCards. The spec's custom format can serve as the internal canonical representation that maps to/from Google A2A at the boundary.

---

## 2. missing_alternative — Temporal.io Durability vs LangGraph Checkpoints

**Affected:** `routing-execution-layer-design.md` §1.2; `tool-ecosystem.md` §8

The spec builds its durability model on **LangGraph checkpoints** (postgres-backed). Temporal.io (`temporal.io`, 12k+ GitHub stars) provides a fundamentally different model:

- **Event sourcing + replay**: All workflow state is reconstructed by replaying deterministic code against an event history. This eliminates state snapshot consistency problems entirely.
- **Exactly-once execution**: Temporal guarantees activities execute exactly-once (not at-most-once or at-least-once), critical for financial operations.
- **Multi-year durability**: Workflows can pause for months and resume transparently. LangGraph checkpoints don't address this long-tail use case.
- **SDK in Go, Java, TypeScript, Python, .NET**: Multi-language, unlike Python-only LangGraph.

The spec's `copy-on-write + reducer merge` concurrency model (§1.2) assumes a single-process Python runtime. Temporal's model works across processes, services, and datacenters — **without needing custom reducer strategies or conflict detection**.

The spec never discusses why LangGraph checkpoints were chosen over Temporal's event-sourcing approach for durability. For fintech workflows (claims processing, payment collection), Temporal's exactly-once guarantee is a material advantage.

**URLs:**
- https://docs.temporal.io/workflows
- https://temporal.io/

**Recommendation:** Add a section comparing LangGraph checkpoint durability vs Temporal event-sourcing. If Temporal is out of scope, justify why and acknowledge the trade-off (simplicity of LangGraph integration vs durability guarantees).

---

## 3. missing_alternative — OpenAI Agents SDK Guardrails vs Custom Validation

**Affected:** `routing-execution-layer-design.md` §3, §7; `response-generation-layer-design.md` §3

The spec builds a custom permission model (§7) and decision eval framework (§3.4). The **OpenAI Agents SDK** (`github.com/openai/openai-agents-python`, 27.2k stars, MIT) provides:

- **Guardrails**: Configurable input/output validation with `allow`/`deny`/`require_review` semantics — directly mapping to the spec's `access_level` matrix and `errorNode` strategies.
- **Handoffs**: Agent-to-agent delegation as a first-class primitive (equivalent to sub-workflows + A2A).
- **Tracing**: Built-in, auto-instrumented (no LangSmith dependency required).
- **Sessions**: Automatic conversation history management (equivalent to the spec's conversation lifecycle).

The spec's permission model (§7) with `read | write | sensitive_data_read | dangerous_operation_write` is conceptually sound but **reimplements what the Agents SDK already provides** as guardrails. The same applies to the decision eval framework — the Agents SDK's tracing already captures decision paths.

The spec explicitly ties to LangGraph/LangChain but never evaluates whether the OpenAI Agents SDK (or similar provider-agnostic harnesses) could simplify the architecture. For organizations already using OpenAI APIs, adopting the Agents SDK's guardrail model would reduce custom code.

**URLs:**
- https://github.com/openai/openai-agents-python
- https://openai.github.io/openai-agents-python/guardrails/

**Recommendation:** Add a comparison between the custom permission/guardrail model and the OpenAI Agents SDK's guardrail primitives. Decide whether to adopt the SDK's guardrail model or justify the custom approach.

---

## 4. missing_alternative — CrewAI Role-Based Multi-Agent vs Sub-Workflow Model

**Affected:** `routing-execution-layer-design.md` §5; `a2a-protocol.md` §1

The spec models sub-workflows as complete StateGraph instances with their own domain models — a **structural decomposition** approach. **CrewAI** (`crewai.com`, used by 63% of Fortune 500, 100k+ developers) takes a **role-based decomposition** approach:

- **Agents have roles, goals, and backstories** — they reason about *what* to do, not *how* workflows are structured.
- **Tasks are described, not programmed** — the LLM determines execution strategy.
- **Manager agents** coordinate sub-agents dynamically.
- **No explicit state machine definition** — the agent's reasoning loop replaces the FSM.

The spec dismisses this approach implicitly by mandating deterministic rule engines and YAML-defined transitions. But for many regulated-industry use cases, role-based delegation with guardrails (a "manager agent" that enforces policies) may be more maintainable than hand-crafted state machines for every workflow variant.

The spec never addresses **when a role-based model might be preferable** to a state-machine model. For FAQ answering, a role-based agent with a knowledge base tool might be simpler than a full `rag_faq` sub-workflow with 4 states.

**URLs:**
- https://www.crewai.com/open-source
- https://docs.crewai.com/

**Recommendation:** Add a section discussing when role-based agent delegation is appropriate vs state-machine sub-workflows. The framework could support both models — sub-workflows for transactional flows, role-based agents for conversational/informational flows.

---

## 5. wrong_approach — All-Errors-to-`errorNode` as a Single Pattern

**Affected:** `routing-execution-layer-design.md` §6.1

> "No per-category dispatch. No multi-link escalation chain. All errors, all timeouts, all retry-exhausted failures — route to a single `errorNode` for unified handling."

This is stated as a core principle but **conflicts with industry practice** in both workflow engines and agent frameworks:

- **AWS Step Functions** uses `Retry` (same state, different input) and `Catch` (different state) as separate primitives. Retry-exhausted errors route to a `Catch` state — but that state can be **different per error type** (`States.ALL`, `States.Timeout`, `States.TaskFailed`, custom error names).
- **Temporal** uses `RetryPolicy` per activity and `Workflow.continueAsNew` for recovery. Errors are categorized and handled locally, not funneled to a single handler.
- **OpenAI Agents SDK** uses guardrail `tripwire_triggered` events with per-guardrail handlers, not a unified error node.

A single `errorNode` creates a **god object anti-pattern** — it must understand all possible error categories and recovery strategies, becoming the most complex node in the system. A `permission_error` from a tool call and a `validation_error` from Layer 1 have fundamentally different recovery paths (the former may need human escalation; the latter may need re-prompting).

The spec acknowledges this partly via per-node `error_node` overrides (§6.8) but still routes through the same conceptual node. The industry pattern is **stratified error handling** — handle locally where possible, escalate only when necessary.

**URLs:**
- https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html
- https://docs.temporal.io/encyclopedia/retry-policies

**Recommendation:** Replace "all errors → errorNode" with a stratified model: retry locally → escalate to node-level handler → escalate to workflow-level handler → human escalation. Keep `errorNode` as the **last resort**, not the first destination.

---

## 6. wrong_approach — Decision Nodes as Top-to-Bottom Rule Lists

**Affected:** `routing-execution-layer-design.md` §3.2

The `decision_rules` YAML format is a simple top-to-bottom, first-match-wins rule list. This is **equivalent to a chain of if-else statements** — the weakest form of rule engine.

Industry-standard rule engines offer richer semantics:

- **Drools / Red Hat Decision Manager** (the spec's `durable_rules` inspiration): Rete algorithm, forward-chaining inference, rule salience/priority, activation groups, ruleflow groups.
- **IBM ODM**: Decision tables, decision trees, ruleflow, BAL (Business Action Language) — used in insurance underwriting and claims processing.
- **AWS Step Functions Choice state**: Supports `And`, `Or`, `Not`, `StringEquals`, `NumericGreaterThan`, `TimestampLessThan` — composable boolean logic, not just flat condition strings.

The spec's rule format (`condition: "risk_score >= 0 AND risk_score <= 30"`) treats conditions as **strings to be parsed at runtime** — slow, error-prone, and impossible to statically analyze. The alternative is structured conditions:

```yaml
condition:
  and:
    - field: risk_score
      op: gte
      value: 0
    - field: risk_score
      op: lte
      value: 30
```

The spec references `durable_rules`, `business-rules`, and `pyknow` but then defines its own flat rule format that uses none of their capabilities. The `decision_rules` YAML is essentially a reimplementation of `business-rules` with less functionality.

**URLs:**
- https://www.drools.org/
- https://github.com/venmo/business-rules

**Recommendation:** Either adopt `business-rules` YAML format directly (it already supports structured conditions), or define a structured condition schema. Remove the custom flat rule format in favor of delegating to the chosen rule engine.

---

## 7. weak_rationale — LangGraph Lock-In Without Sufficient Justification

**Affected:** All specs; pervasive throughout

Every execution spec assumes LangGraph as the runtime. The routing layer (§5.7) explicitly lists LangGraph API support. The tool ecosystem (§2-4) is entirely LangChain/LangGraph/LangSmith. The concurrency model (§1.2) is "inherited from LangGraph's StateGraph semantics."

But the justification for LangGraph exclusivity is **never provided**. There is no comparison table, no discussion of alternatives, no migration path if LangGraph changes or is deprecated.

Key risks:
- **LangGraph is a LangChain product** (Series B startup). If LangChain pivots, is acquired, or changes licensing, the framework is locked in.
- **LangGraph's Python-only** runtime excludes TypeScript/Node.js ecosystems (the spec asks about runtime-agnostic abstraction in Open Question 4 of tool-ecosystem but never answers).
- **Competing orchestrators** (Temporal, AWS Step Functions, Google ADK, OpenAI Agents SDK) all offer overlapping capabilities with different trade-offs.

The spec should either:
1. Define a runtime-agnostic abstraction layer (as Open Question 4 hints), or
2. Provide a clear rationale for LangGraph exclusivity with explicit trade-off analysis

**URLs:**
- https://docs.langchain.com/oss/python/langgraph/overview
- https://github.com/google/adk-python (Google Agent Development Kit)

**Recommendation:** Add an Architecture Decision Record (ADR) justifying LangGraph. If the framework is meant to be "industry-agnostic," the runtime should not be single-vendor.

---

## 8. weak_rationale — Goal Checker as LLM-Based Without Discussing Deterministic Alternatives

**Affected:** `response-generation-layer-design.md` §4

The goal checker (§4.1) is described as "an LLM node" that produces `GoalCheckResult` JSON. The rationale is not provided. A deterministic goal checker is equally viable:

- Check `expected_entities` against `collectedFields` keys → deterministic
- Check `expected_outputs` against `outcomes` keys → deterministic
- Check `success_criteria` like "annual_premium is calculated" → can be deterministic (field presence check)

The LLM is only needed for `gap_analysis` (natural language reasoning about "what's missing") — which is a nice-to-have for audit, not a requirement for the 422 decision.

Using an LLM for goal checking introduces:
- **Cost**: Every workflow execution incurs an extra LLM call
- **Latency**: Adds 1-3 seconds at workflow end
- **Non-determinism**: Same inputs could produce different `completion_percentage` values
- **Calibration risk**: LLM may be lenient (overshoot) or strict (undershoot) depending on prompt

The spec should separate **deterministic goal verification** (field/output presence, numeric threshold checks) from **LLM gap analysis** (optional, for audit). The 422 decision should be driven by deterministic checks; the LLM provides explanation only.

**Recommendation:** Add a deterministic goal check mode (Option A) alongside the LLM-based mode (Option B). The 422 threshold should be evaluated deterministically; LLM gap analysis is supplementary.

---

## 9. outdated_pattern — YAML-Based Workflow Definition as Primary Authoring Method

**Affected:** All specs; YAML is the primary definition language

The spec defines everything in YAML — domain models, workflows, transitions, rules, permissions, tool configs. This follows the Infrastructure-as-Code pattern (Kubernetes, Ansible, Terraform). However, the agent framework industry is moving toward **code-first definitions**:

- **OpenAI Agents SDK**: Python classes (`Agent`, `Runner`, `Guardrail`) — IDE-friendly, type-checked, testable.
- **LangChain `create_agent`**: Python function composition with middleware — no YAML files needed.
- **Temporal**: Workflow code in Go/Java/TypeScript/Python — deterministic code, not config.
- **Google ADK**: Python `Agent` class with decorators.

The YAML approach has notable drawbacks:
- **No IDE support**: No autocomplete, no type checking, no refactoring tools for YAML
- **String-based references**: `execute: premium.calculate` is a module path string — renaming the function breaks the YAML silently
- **Limited composability**: YAML cannot express loops, conditionals, or function composition
- **Testing friction**: Unit-testing a YAML workflow requires loading the entire framework

The spec does include **Option A: Pure Functions** (§2.4) with code executors — but the workflow definition itself (states, transitions, permissions) remains YAML. A code-first approach where workflows are Python classes with decorators (think: pytest fixtures, FastAPI routes) would reduce the YAML burden.

The industry trend is clear: LangChain itself says "LangGraph [is] our low-level orchestration framework, for advanced needs combining deterministic and agentic workflows" — implying that LangGraph is for specialized cases, not the primary authoring surface. The spec inverts this by making LangGraph + YAML the default.

**URLs:**
- https://docs.langchain.com/oss/python/langchain/overview
- https://github.com/google/adk-python

**Recommendation:** Define workflows as **Python-first with YAML as a serialization/export format**, not the primary authoring surface. LangFlow can still export YAML, but developers should write Python classes.

---

## 10. missing_alternative — Response Streaming Not Addressed

**Affected:** `response-generation-layer-design.md` §3; `mcp-api-protocol.md`

The MCP spec mentions SSE transport for the server but streaming of the **generated response content to the end user** is never addressed. The Response Generation spec (§3) assumes a complete `ResponseMessage` is built and returned. Industry practice now includes:

- **Token-by-token streaming**: Users see responses as they're generated (ChatGPT, Claude Desktop, etc.)
- **MCP progress notifications**: The MCP 2025-06-18 spec supports `progress` notifications for long-running operations
- **OpenAI Agents SDK streaming**: `stream=True` with `RunResultStreaming` for real-time output

The spec's architecture (generate response + goal checker in parallel, then route) implies the response is held until the goal checker completes. This means the user waits for both generation AND verification before seeing any output — adding 1-3 seconds of perceived latency.

For chat UX, this is a regression from current AI chatbots that stream immediately.

**Recommendation:** Add streaming response delivery with late-binding goal check. Stream the response to the user immediately; if the goal checker later fails (422), append a correction message. This preserves UX while still enforcing quality.

---

## 11. missing_alternative — MCP Sampling & Elicitation Features

**Affected:** `mcp-api-protocol.md` §2.2

The spec's MCP capability advertisement (§2.2) lists only `tools` and `resources`. The MCP 2025-06-18 spec includes additional server-initiated features:

- **Sampling**: Server-initiated LLM requests (the server asks the client to run an LLM call). This enables patterns where the framework needs external LLM capability it doesn't have locally.
- **Roots**: Server-initiated filesystem boundary discovery (the server asks the client what directories it can access).
- **Elicitation**: Server-initiated requests for user input (the server asks the client to prompt the user).

These are relevant to the framework's use case: the `errorNode`'s `ask_clarify` strategy could use MCP elicitation; the framework's LLM routing could use sampling for decisions. The spec ignores these MCP capabilities.

**URLs:**
- https://modelcontextprotocol.io/specification/2025-06-18

**Recommendation:** Evaluate whether MCP sampling, roots, and elicitation should be supported. At minimum, document why they're excluded.

---

## Summary Table

| # | Tag | Issue | Severity |
|---|-----|-------|----------|
| 1 | missing_alternative | Custom A2A format vs Google A2A standard | High |
| 2 | missing_alternative | Temporal.io durability vs LangGraph checkpoints | High |
| 3 | missing_alternative | OpenAI Agents SDK guardrails vs custom permission model | Medium |
| 4 | missing_alternative | CrewAI role-based delegation vs structural sub-workflows | Medium |
| 5 | wrong_approach | All-errors-to-`errorNode` creates god object anti-pattern | High |
| 6 | wrong_approach | Flat rule list instead of structured conditions / Rete algorithm | Medium |
| 7 | weak_rationale | LangGraph lock-in without ADR or comparison | High |
| 8 | weak_rationale | LLM-based goal checker without deterministic alternative | Medium |
| 9 | outdated_pattern | YAML-first authoring vs industry code-first trend | Medium |
| 10 | missing_alternative | No response streaming, latency penalty from goal check blocking | Medium |
| 11 | missing_alternative | MCP sampling/elicitation/roots features ignored | Low |
