# A2A (Agent-to-Agent) Protocol

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: How sub-workflows become agent-to-agent communication — A2A message format, discovery, sync/async semantics, relationship with MCP, and the A2A runtime protocol.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial A2A protocol spec: message format, discovery, sync/async, MCP comparison |
| 2026-06-18 | 0.1.1 | Add cross-reference to [Tool Ecosystem §7.5](./2026-06-17-tool-ecosystem.md) for `type: a2a` tool integration (A2A agents as node-level tools with multi-turn conversations); sync with Decision 24 |

---

## 1. Role

A company's business flows are all interconnected — one workflow is another's sub-workflow. The architecture is fundamentally Agent-to-Agent.

Sub-workflows are **NOT** just function calls. They are agent-to-agent interactions — each sub-workflow is itself a complete, autonomous agent with its own domain model, permission model, retry budgets, and routing. When a parent workflow invokes a sub-workflow, it is delegating a goal to another agent, not calling a subroutine.

```
Parent Workflow (Agent A)
    │
    │  "I need a FAQ answer for this question"
    │  A2A: entities + goal → Agent B
    │
    ▼
Sub-Workflow (Agent B: rag_faq)
    │
    │  executes: search → generate → return
    │  A2A: results + audit → Agent A
    │
    ▼
Parent Workflow resumes with Agent B's output
```

This spec defines **A2A as the runtime communication protocol** between agents. Sub-workflows (see Routing & Execution spec §5) are the **definition language** — they define the agent's domain model, states, transitions, permissions, and retry budgets. A2A is **how agents talk to each other at runtime**.

### 1.1 Key Insight: Every Sub-Workflow is an Agent

| Concept | Sub-Workflow Spec | A2A Protocol |
|---------|-------------------|--------------|
| **Role** | Definition language — what this agent can do | Runtime protocol — how agents communicate |
| **Artifact** | `rag_faq.yaml` — entities, states, transitions, permissions | A2A messages — input/output over the wire |
| **When used** | Design time (workflow authoring) | Runtime (agent-to-agent invocation) |
| **Analogy** | Class definition | Method invocation |

### 1.2 What A2A Does NOT Cover

- **Sub-workflow definition** → Routing & Execution spec §5
- **MCP tool invocation** → Tool Ecosystem spec §7
- **OAuth / user identity** → Auth Token Verification spec
- **Response generation** → Response Generation spec

> **New (2026-06-18):** The A2A protocol is also available as a **tool type** (`type: a2a`) — any node can call another agent as one of its `tool_allowlist` tools, with multi-turn conversation support. See [Tool Ecosystem §7.5](./2026-06-17-tool-ecosystem.md) for A2A tool registration, multi-turn A2A conversations, and the A2A-tool-vs-sub-workflow comparison matrix.

---

## 2. A2A Protocol Contract

### 2.1 Core Semantics

```
A2A Call (Agent A → Agent B):
  Input:   entities + goal + correlation_id
  Output:  results + audit + correlation_id
```

The protocol is intent-based, not function-call-based. Agent A sends *what it wants to accomplish* (goal + relevant entities), not *how to do it*. Agent B decides how to achieve the goal using its own internal workflow.

### 2.2 A2A Message Format

Every A2A message carries a standard envelope:

```yaml
# A2A Request — sent by caller agent to target agent
a2a_request:
  # --- Routing ---
  agent_id: string                   # target agent identifier (registered in registry)
  correlation_id: string             # UUID — ties request to response across async boundaries

  # --- Context ---
  caller:
    agent_id: string                 # caller agent identifier
    workflow_id: string              # which workflow instance is calling

  # --- Payload ---
  goal:
    summary: string                  # what the caller wants the target to accomplish
    expected_outputs: string[]       # which outputs are expected back

  entities:                          # relevant entity data passed to target agent
    <entity_name>: <entity_data>

  constraints:
    deadline_ms: integer             # optional — hard deadline for response
    priority: low | normal | high | critical

  # --- Protocol ---
  mode: sync | async                 # caller expects to wait or continue
  version: string                    # A2A protocol version (e.g., "1.0.0")
```

```yaml
# A2A Response — sent by target agent back to caller
a2a_response:
  # --- Routing ---
  correlation_id: string             # matches the request's correlation_id

  # --- Status ---
  status: completed | failed | partial | timeout

  # --- Payload ---
  results:                           # structured output from the target agent
    <output_name>: <output_data>

  # --- Audit ---
  audit:
    agent_id: string                 # which agent produced this response
    steps_completed: string[]        # states traversed within the target agent
    duration_ms: integer
    attempts: integer                # retries used (including LLM +1)

  # --- Error (if status != completed) ---
  error:
    category: llm_error | api_error | tool_error | validation_error | permission_error | business_rule_error
    message: string
    gap_analysis: string             # what goal criteria were not met
```

### 2.3 A2A vs Sub-Workflow Input Mapping

The A2A protocol is the wire format. Sub-workflow `input_mapping` (Routing & Execution spec §5.6) defines how parent state maps to A2A request fields:

```yaml
# parent workflow YAML — sub-workflow invocation
states:
  handle_question_in_quote:
    executor: sub_workflow
    sub_workflow: rag_faq
    mode: sync
    input_mapping:                        # these map to A2A request
      goal:
        summary: "Answer user's FAQ question"
        expected_outputs: [answer]
      entities:
        question_input:
          question: "{{state.last_user_message}}"
          conversation_context: "{{state.conversation_history}}"
      constraints:
        deadline_ms: 10000
    on_return: collect_property_info
```

The framework auto-generates the A2A envelope from this mapping. The developer never writes A2A messages manually.

---

## 3. Two API Formats the Framework Exposes

The framework exposes two protocol families. Both are JSON-based, stateless at the transport layer, and carry correlation IDs — but serve different use cases.

| | MCP | A2A |
|---|-----|-----|
| **Role** | External tool invocation | Internal agent delegation |
| **Consumer** | External systems (Claude Desktop, IDE, CLI) | Internal agents (parent workflows) |
| **Semantics** | Function-call: "execute this tool with these params" | Intent-based: "achieve this goal with these entities" |
| **State** | Stateless tool execution | Agent has its own state machine, permissions, retry |
| **Discovery** | MCP `list_tools` | Agent Registry `discover` |
| **Response** | ToolResult { success, data } | AgentResult { status, results, audit } |
| **Auth** | MCP server-level auth | Inherited from caller's UserContext |
| **Example** | `calculate_premium(params)` | "Process a claim for this policy → agent_claims" |

```
┌─────────────────────────────────────────────────────────┐
│                   FRAMEWORK BOUNDARY                      │
│                                                           │
│  External                    Internal                     │
│  ┌──────────┐               ┌──────────────────┐         │
│  │  MCP     │──────────────→│  Tool Execution  │         │
│  │  Client  │  function-call│  (stateless)     │         │
│  │ (Claude, │               └──────────────────┘         │
│  │  IDE)    │                                            │
│  └──────────┘               ┌──────────────────┐         │
│                              │  Agent Registry  │         │
│  ┌──────────┐               │       │          │         │
│  │  Agent A │──────────────→│  A2A  │  Agent B │         │
│  │ (Parent  │  intent-based │       │  (Sub-   │         │
│  │  Workflow│               │       │  workflow)│         │
│  └──────────┘               └──────────────────┘         │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Same Protocol Family, Different Use Case

MCP and A2A share a common design philosophy:
- Both carry `correlation_id` for traceability
- Both are JSON-structured
- Both support sync and async patterns
- Both are registered and discovered via a registry

They differ in **semantic level**: MCP is tool-level ("do this operation"), A2A is agent-level ("achieve this goal").

```yaml
# framework.yaml — protocol configuration
protocols:
  mcp:
    enabled: true
    servers:                          # see Tool Ecosystem spec §7
      knowledge_base: ...
      claims_gateway: ...

  a2a:
    enabled: true
    version: "1.0.0"
    agents:
      discovery: registry             # registry | static_list
      registry:
        backend: postgresql           # postgresql | file | consul
        connection_string: "${A2A_REGISTRY_DSN}"
```

---

## 4. Agent Discovery

### 4.1 Agent Registry

Parent workflows discover available A2A agents via a registry. The registry answers: *"Which agents are available, what can they do, and how do I talk to them?"*

```yaml
# Agent Registry entry for rag_faq
agent_registry:
  agents:
    - agent_id: rag_faq
      version: "1.0.0"
      description: "Answer user questions using RAG knowledge base"
      capability: faq_answering
      expected_inputs:
        - question_input                    # entity: question + conversation context
      expected_outputs:
        - answer_output                     # entity: answer + sources
      modes: [sync, async]
      max_concurrency: 50
      health_endpoint: "/a2a/health"
      invoke_endpoint: "/a2a/invoke"
      status: active                        # active | degraded | offline
```

### 4.2 Discovery Flow

```
Parent Workflow Boot
    │
    ├── 1. Query registry: "find agent for capability=faq_answering"
    │
    ├── 2. Registry returns: [rag_faq (active, v1.0.0)]
    │
    ├── 3. Framework validates:
    │       ✓ agent is active
    │       ✓ agent supports requested mode (sync/async)
    │       ✓ agent version is compatible
    │
    └── 4. Framework caches agent descriptor for workflow duration
```

### 4.3 Static vs Dynamic Discovery

```yaml
# framework.yaml
a2a:
  discovery:
    mode: dynamic                     # dynamic | static
    registry:                         # used when mode=dynamic
      backend: consul                 # consul | postgresql | etcd
      endpoint: "${CONSUL_HTTP_ADDR}"
      refresh_interval_sec: 30        # how often to re-sync agent list
    static_agents:                    # used when mode=static
      - agent_id: rag_faq
        endpoint: "http://localhost:8001"
        health_check_path: "/health"   # GET endpoint, must return 200
      - agent_id: claims_processor
        endpoint: "http://localhost:8002"
        health_check_path: "/health"
      - agent_id: property_verification
        endpoint: "http://localhost:8003"
        health_check_path: "/health"
    health_check_interval_sec: 10      # how often to probe agent health
```

| Mode | Use Case | Trade-off |
|------|----------|-----------|
| **Dynamic** | Multi-service deployments; agents scale independently | Requires service discovery infra (Consul, etcd) |
| **Static** | Monolith / single-process; simple deployments | No dynamic scaling; manual reconfiguration |

---

## 5. Sync vs Async A2A

### 5.1 Semantics

The same sync/async semantics defined in the sub-workflow spec (Routing & Execution §5.4) apply at the A2A protocol level — but now with full agent semantics:

```yaml
# Sync A2A invocation
states:
  answer_faq_question:
    executor: a2a_invoke
    agent: rag_faq
    mode: sync
    timeout_ms: 10000
    on_return: collect_property_info

# Async A2A invocation
states:
  background_verification:
    executor: a2a_invoke
    agent: property_verification
    mode: async
    on_complete: risk_result_received         # callback when async agent finishes
    on_timeout: proceed_without_risk_check    # fallback if async agent doesn't respond
```

### 5.2 Sync Flow

```
Agent A                        Agent B
  │                              │
  ├── A2A Request ──────────────→│
  │                              ├── Execute workflow
  │   (blocks, waits)            │   search → generate → validate
  │                              │
  │←── A2A Response ────────────┤
  │    status: completed          │
  ├── Resume parent workflow      │
```

### 5.3 Async Flow

```
Agent A                        Agent B
  │                              │
  ├── A2A Request ──────────────→│
  │   mode: async                 ├── Execute workflow
  │                              │   ...
  ├── Continue parent workflow    │
  │   ...                         │
  │                              ├── A2A Response (callback)
  │   [on_complete triggered] ←──┤
  ├── Process result              │
```

### 5.4 Async Callback Patterns

```yaml
# framework.yaml — async A2A callback configuration
a2a:
  async:
    callback:
      strategy: webhook | polling | message_queue
      webhook:
        endpoint: "/a2a/callback/{correlation_id}"
        retry_on_failure: true
        max_retries: 3
      polling:
        interval_ms: 1000
        max_polls: 30
      message_queue:
        backend: redis           # redis | rabbitmq | kafka
        channel: "a2a.responses"
```

---

## 6. A2A Execution Flow

### 6.1 Full Lifecycle

```
1. Parent workflow reaches a2a_invoke node
2. Framework resolves agent_id → queries registry → gets agent descriptor
3. Framework validates:
     ✓ Agent is active
     ✓ Agent supports requested mode
     ✓ Caller has permission to invoke this agent
4. Framework constructs A2A request:
     - Maps parent state → A2A request payload via input_mapping
     - Generates correlation_id
     - Sets deadline from constraints
5a. [Sync] Framework sends A2A request, blocks, waits for response
5b. [Async] Framework sends A2A request, continues parent workflow immediately
6. Target agent receives A2A request → executes its own state machine
7. Target agent returns A2A response
8a. [Sync] Parent receives response → resumes workflow at on_return
8b. [Async] Parent's on_complete callback fires → processes response
9. Audit: both sides log the A2A interaction with correlation_id
```

### 6.2 Permission Model for A2A

Agents may restrict which callers can invoke them:

```yaml
# Agent registry entry with caller allowlist
agent_registry:
  agents:
    - agent_id: claims_processor
      allowed_callers:
        - home_insurance_quote              # only this workflow can invoke
      deny_all_others: true
    - agent_id: rag_faq
      allowed_callers: ["*"]                # any agent can invoke
```

### 6.3 A2A Error Handling

When an A2A invocation fails, the error routes to `errorNode` following the same pattern as all other errors (Routing & Execution spec §6):

```yaml
# Per-node A2A error configuration
states:
  handle_claim:
    executor: a2a_invoke
    agent: claims_processor
    mode: sync
    on_error:
      route_to: errorNode
      fallback_on_timeout: queue_for_retry
      max_retries: 2
```

| A2A Error | Handling |
|-----------|----------|
| Agent unreachable (network) | Retry with backoff → errorNode |
| Agent timeout | errorNode (fallback_value or escalate) |
| Agent returns `status: failed` | errorNode with agent's gap_analysis |
| Agent returns `status: partial` | Decision: accept partial or trigger errorNode |
| Permission denied (caller not allowed) | Immediate errorNode — no retry |

---

## 7. Comparison: MCP vs A2A

### 7.1 Side-by-Side

| Dimension | MCP | A2A |
|-----------|-----|-----|
| **Semantic level** | Tool ("execute operation") | Agent ("achieve goal") |
| **State** | Stateless | Stateful (agent has its own FSM) |
| **Input** | Tool name + parameters | Entities + goal + constraints |
| **Output** | ToolResult { success, data } | AgentResult { status, results, audit } |
| **Discovery** | `list_tools` via MCP handshake | Agent Registry query |
| **Retry** | Simple: retry tool call | Complex: agent-level retry within its own budget |
| **Permission** | Tool-level access_level | Agent-level + inherited UserContext |
| **Audit** | Tool invocation recorded | Full sub-workflow trace recorded |
| **Protocol version** | MCP spec version | A2A spec version |
| **Consumer** | External clients | Internal workflows |
| **Example** | `search_documents(query)` | "Answer this FAQ question → rag_faq agent" |

### 7.2 When to Use Which

```
Decision tree:

Is the consumer an external system (IDE, Claude Desktop, CLI)?
  └─ Yes → MCP
  └─ No → Continue

Does the task require its own state machine, permissions, and retry?
  └─ Yes → A2A (it's an agent)
  └─ No → Continue

Is the task a single operation with clear input/output?
  └─ Yes → MCP tool (simpler)
  └─ No → A2A (needs agent-level autonomy)
```

### 7.3 Coexistence

An agent can expose BOTH MCP tools AND A2A endpoints simultaneously:

```yaml
# rag_faq agent — dual protocol exposure
rag_faq:
  a2a:
    endpoint: "/a2a/invoke"
    capability: faq_answering
  mcp:
    tools:
      - search_knowledge_base
      - get_document
```

This means:
- **Parent workflows** invoke `rag_faq` via A2A (delegate the full FAQ workflow)
- **External tools (like Claude Desktop)** can also call `rag_faq.search_knowledge_base` via MCP (use its individual capabilities)

---

## 8. Sub-Workflow Spec Cross-Reference Update

The A2A protocol complements the existing sub-workflow spec (Routing & Execution §5) as follows:

| Sub-Workflow Spec § | A2A Relationship |
|---------------------|------------------|
| §5.1 Concept — "complete, standalone workflows" | A2A formalizes this as agent independence |
| §5.2 Full Workflow Structure — domain model, entities, states | These are the agent's internal definition (not exposed via A2A) |
| §5.3 Node Orchestration — serial, parallel, DAG | Internal execution — invisible to caller |
| §5.4 Sync vs Async | A2A protocol carries this as `mode` field |
| §5.5 Sub-Workflow Nesting | Recursive A2A: Agent A → Agent B → Agent C |
| §5.6 Invocation from Parent — input_mapping | Input_mapping generates A2A request payload |

**New: A2A adds to sub-workflow spec:**
- Wire format (A2A request/response envelope)
- Agent registry + discovery
- Caller permission model
- Async callback mechanisms
- Correlation ID across agent boundaries

---

## 9. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should A2A support streaming responses (agent streams partial results as they're produced), or only complete responses? | Long-running agent UX |
| 2 | Should the agent registry support version negotiation (caller requests agent v1.2, registry returns latest compatible)? | Agent evolution |
| 3 | For async A2A: if the parent workflow terminates before the async agent responds, what happens to the correlation? | Resource cleanup |
| 4 | Should A2A support bidirectional communication (agent B can ask agent A for clarification mid-execution)? | Complex agent interactions |
| 5 | How should the agent registry handle agent health (heartbeats, degraded status propagation)? | Production resilience |
| 6 | Should A2A messages be persisted to an event log for replay/debugging (event sourcing pattern)? | Audit and debugging |
| 7 | Can A2A agents be deployed as separate services (microservices), and if so, what is the service mesh integration surface? | Deployment architecture |
| 8 | Should A2A support a "conversation" pattern where agents exchange multiple messages before completing (not just request/response)? | Complex multi-step delegation |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — framework architecture, permission model
- [Routing & Execution Layer](./2026-06-17-routing-execution-layer-design.md) — sub-workflow spec (§5), retry (§6), permission (§7)
- [Tool Ecosystem](./2026-06-17-tool-ecosystem.md) — MCP server integration (§7), tool registration
- [Auth Token Verification](./2026-06-17-auth-token-verification.md) — UserContext injection
- [Google A2A Protocol](https://github.com/google/A2A) — Google's Agent-to-Agent protocol (conceptual reference)
