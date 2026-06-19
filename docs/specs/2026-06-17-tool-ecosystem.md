# Tool Ecosystem Integration

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Visual editor, graph debugger, rule engines, MCP servers, and all third-party tools that integrate with the framework.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial tool ecosystem spec |
| 2026-06-17 | 0.2.0 | Replace Python code blocks with YAML config examples; add errorNode failure routing (Section 6.4); add Open Questions (Section 13) |
| 2026-06-17 | 0.3.0 | Section 2.2 LangFlow mapping table: change "Error Handler" → "ErrorNode"; add Section 6 Permission Enforcement (pycasbin) |
| 2026-06-17 | 0.4.0 | Fix section numbering for §7–§10 sub-sections; change ErrorNode to errorNode (camelCase) in LangFlow mapping table |
| 2026-06-18 | 0.5.0 | Add `a2a` tool type (§7.5): nodes can call other agents as tools via A2A protocol; add `sdk` tool type (§7.6): nodes can call OpenCode/Claude SDK as tools |
| 2026-06-18 | 0.5.1 | Deduplicate §9 PII Detection: trim to catalog entry, cross-reference authoritative [Response Generation §8](./2026-06-17-response-generation-layer-design.md); sync cross-references with a2a-protocol.md and mcp-api-protocol.md |

---

## 1. Tool Stack Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DEVELOPER WORKFLOW                        │
├───────────────┬───────────────────┬─────────────────────────┤
│   Design      │   Debug / Test    │   Deploy / Monitor      │
├───────────────┼───────────────────┼─────────────────────────┤
│  LangFlow     │  LangGraph CLI    │  LangSmith Studio       │
│  (drag-drop   │  (graph view +    │  (trace, eval,          │
│   visual edit)│   hot reload)     │   prompt engineering)    │
├───────────────┴───────────────────┴─────────────────────────┤
│                    RUNTIME ENGINE                             │
├───────────────┬───────────────────┬─────────────────────────┤
│  LangGraph    │  Rule Engines     │  Tool Servers           │
│  (state graph │  durable_rules    │  MCP servers            │
│   execution)  │  business-rules   │  API endpoints          │
│               │  pyknow           │  Claude Desktop         │
├───────────────┴───────────────────┴─────────────────────────┤
│                    DETERMINISTIC FRAMEWORK                    │
│  (domain model, extraction, routing, response, permission)   │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| **Visual Editor** | LangFlow | Drag-and-drop graph building, node configuration |
| **Dev Server** | LangGraph CLI (`langgraph dev`) | Local dev with hot reload + graph visualization |
| **Debug & Monitor** | LangSmith Studio | Trace execution, time-travel debug, eval datasets |
| **State Machine** | `transitions` | Deterministic FSM definition + Graphviz export |
| **Graph Runtime** | LangGraph | State graph execution, checkpoint, streaming |
| **Rule Engines** | durable_rules, business-rules, pyknow | Validation + decision rules |
| **Tool Servers** | MCP servers, REST APIs, CLI commands | External capability integration |
| **A2A Agent Tools** | Agent Registry, A2A protocol endpoints | Delegate to other agents as tools |
| **SDK Tools** | OpenCode CLI, Claude SDK, OpenAI SDK | AI coding assistant as a tool |
| **LLM Providers** | OpenAI, Anthropic (Claude), local models | NLU, extraction, response generation |
| **PII Detection** | Presidio, spaCy, custom NER | Sensitive data detection, redaction |

---

## 2. LangFlow — Visual Editor

### 2.1 Role

Drag-and-drop visual builder for LangGraph workflows. Developers can:
- Visually design graph topology (nodes + edges)
- Configure node parameters (state, strategies, permissions)
- Export as LangGraph graph code or JSON
- Test interactively in the playground

### 2.2 Integration with Our Framework

```
LangFlow UI
    │
    │  drag-and-drop nodes: extract, validate, transform, decide, respond
    │  configure: strategy, retry, permission, tool allowlist
    │
    ▼
Export as YAML → domain_model.yaml + workflow.yaml
    │
    ▼
Our Framework loads YAML → generates LangGraph graph
```

**Node palette mapping:**

| LangFlow Node Type | Framework Interface | Configurable In |
|--------------------|--------------------|-----------------|
| `Extract` | `ExtractionNode` | extract_strategy, extract_rules |
| `Validate` | `ValidationNode` | validate_strategy, validation_rules |
| `Transform` | `TransformNode` | transform_strategy, transform_rules |
| `Code Executor` | `CodeExecutor` | execute function, input/output schema |
| `Decision` | `DecisionNode` | rule engine, LLM fallback |
| `Sub-Workflow` | `SubWorkflowInvoker` | sub_workflow name, sync/async, input_mapping |
| `Respond` | `ResponseGenerator` | response_strategy (pure_message / widget) |
| `errorNode` | `ErrorNode` | strategy (clarify / escalate / terminate) |

### 2.3 Installation

```bash
pip install langflow
langflow run
# → http://localhost:7860
```

### 2.4 LangFlow Custom Component

Register framework nodes as LangFlow custom components via YAML:

```yaml
# langflow_components/extract_node.yaml
name: ExtractEntity
display_name: "Extract Entity"
description: "Extract structured entities from user input"
icon: Search
category: DeterministicWorkflow

parameters:
  - name: strategy
    display_name: "Strategy"
    type: dropdown
    options: [llm_primary, deterministic, hybrid]
    default: hybrid
  - name: entity
    display_name: "Entity"
    type: str
    info: "Domain model entity name"
  - name: state_hint
    display_name: "State Hint"
    type: text
    multiline: true

outputs:
  - name: message
    type: Message
    description: "Extracted entity data"
```

---

## 3. LangGraph CLI — Dev Server

### 3.1 Role

Local development server with hot reloading and built-in graph visualization. The `langgraph dev` command starts an API server that hosts the LangGraph graph, with a browser-based UI showing:
- Graph topology (nodes + edges)
- Current state at each node
- Stream trace of execution

### 3.2 Integration

```bash
# Start dev server with our framework graph
langgraph dev --config langgraph.json
```

```json
// langgraph.json
{
  "dependencies": ["langchain_openai", "./deterministic_workflow"],
  "graphs": {
    "home_insurance_quote": "./deterministic_workflow/graph.py:build_graph"
  },
  "env": "./.env"
}
```

The `build_graph` entry point loads config from YAML and compiles the LangGraph `StateGraph`:

```yaml
# deterministic_workflow/config.yaml — engine bootstrap config
engine:
  domain_model: "domain-models/home-insurance.yaml"
  workflow_config: "workflows/home_insurance_quote.yaml"
  checkpoint_backend: "postgresql://localhost:5432/langgraph"
  rule_engine: durable_rules

langgraph:
  entry_point: "deterministic_workflow.graph:build_graph"
  # build_graph() reads engine config, creates WorkflowEngine, returns compiled graph
```

### 3.3 Capabilities

| Feature | Command / API |
|---------|--------------|
| Start dev server | `langgraph dev` |
| Hot reload on change | Default (watch mode) |
| View graph | Browser at `http://localhost:2024` |
| Test conversation | Built-in chat UI |
| Inspect state | Click any node to view state snapshot |
| Time travel | Replay from any checkpoint |
| Deploy to Docker | `langgraph build -t myimage` |

---

## 4. LangSmith Studio — Debug & Monitor

### 4.1 Role

Cloud-based IDE for debugging, testing, and monitoring LangGraph agents. Features:
- Execution trace with node-level detail
- Time-travel debugging (replay from any checkpoint)
- Eval dataset management
- Prompt engineering playground
- One-click deploy

### 4.2 Integration

```yaml
# framework.yaml — LangSmith tracing configuration
langsmith:
  api_key: "${LANGSMITH_API_KEY}"
  tracing: true
  project: "home-insurance-quote"
  # Framework auto-traces all LLM calls and graph execution.
  # Every conversation.send() creates a trace in LangSmith Studio.
```

### 4.3 Eval Integration

Run eval datasets against our workflow to verify goal check accuracy and response quality:

```yaml
# langsmith/eval_config.yaml
evaluators:
  - goal_completion_accuracy
  - response_pii_leakage
  - decision_correctness

dataset: "home-insurance-eval-dataset"

experiment:
  name: "home-insurance-v1.0"
  description: "Baseline eval for home insurance quote workflow"
  metadata:
    domain: home_insurance
    version: "1.0.0"

# Run via: langsmith eval run --config langsmith/eval_config.yaml
```

---

## 5. Rule Engines

### 5.1 Role

Three pluggable rule engines for validation and decision nodes:

| Engine | Install | Best For |
|--------|---------|----------|
| `durable_rules` | `pip install durable-rules` | When/then inference, cross-field rules |
| `business-rules` | `pip install business-rules` | Simple YAML/JSON rules, no inference |
| `pyknow` | `pip install pyknow` | Expert system, Fact/KnowledgeEngine |

### 5.2 Configuration

```yaml
# workflow.yaml
nodes:
  validate_property_info:
    rule_engine: durable_rules    # per-node override

# framework.yaml (global default)
rule_engine:
  default: durable_rules
  available: [durable_rules, business-rules, pyknow]
```

### 5.3 Custom Rule Engine Registration

Register custom rule engines via YAML configuration:

```yaml
# framework.yaml
rule_engine:
  default: durable_rules
  available:
    - durable_rules
    - business-rules
    - pyknow
    - custom_engine:
        module: "my_package.custom_rules"
        class: "CustomRuleEngine"
        # Must implement: compile(ruleset_name, rules) -> None, execute(ruleset_name, facts) -> dict
```

---

## 6. Permission Enforcement — pycasbin

### 6.1 Role

Our framework has a two-level permission model (see Routing & Execution spec §7). The config-level enforcement (per-node `allowed_tools` + `allowed_transitions` YAML lists) is simple. For deployments with complex access patterns (many roles × many tools), `pycasbin` provides a configurable authorization engine.

### 6.2 When to Use pycasbin

| Scenario | Tool |
|----------|------|
| Simple: 1-2 roles, <10 tools | YAML allowlists (built-in) — no external library needed |
| Medium: 3-10 roles, <50 tools | pycasbin with CSV policies |
| Complex: role hierarchy, attribute-based rules | pycasbin with database adapter |

### 6.3 Installation

```bash
pip install pycasbin
```

### 6.4 Casbin Model Definition

The Casbin model defines the access control pattern. Written once, not changed at runtime:

```ini
# model.conf
[request_definition]
r = sub, obj, act        # subject (user/role), object (tool/transition), action (read/write)

[policy_definition]
p = sub, obj, act        # policy rule: who can do what to which

[role_definition]
g = _, _                 # role inheritance: g(alice, admin) means alice inherits admin privileges

[policy_effect]
e = some(where (p.eft == allow))   # allow if ANY matching policy grants access

[matchers]
m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
```

### 6.5 Policy (Generated from YAML Config)

```csv
# policy.csv — auto-generated from workflow YAML permission sections

# Role inheritance
g, scope:dangerous_operation:write, operator
g, scope:sensitive_data:read, analyst
g, operator, analyst
g, admin, operator

# Tool access policies
p, admin, *, *                          # admin: full access
p, operator, claims_gateway_api, write
p, operator, calculate_premium_api, read
p, operator, vector_search_mcp, read
p, analyst, policy_lookup_api, read
p, analyst, claim_history_api, read
p, user, vector_search_mcp, read
p, user, calculate_premium_api, read

# Transition access policies
p, *, collect_property_info, transition
p, *, collect_coverage_needs, transition
p, admin, claims_processing, transition
p, operator, claims_processing, transition
```

### 6.6 Framework Integration

```yaml
# framework.yaml
permission:
  engine: pycasbin           # pycasbin | native (built-in YAML list check)
  model: "config/casbin/model.conf"
  policy_source: workflow_yaml   # workflow_yaml | csv_file | database

# Per-workflow override
workflows:
  home_insurance_quote:
    permission:
      engine: native          # simple allowlist, no casbin needed
  enterprise_claims:
    permission:
      engine: pycasbin        # complex role hierarchy
      model: "config/casbin/claims_model.conf"
```

### 6.7 Enforcement Flow

```
1. Framework loads workflow YAML
2. If permission.engine == "pycasbin":
     a. Load casbin model.conf
     b. Generate policy.csv from YAML permission sections
     c. Create enforcer = casbin.Enforcer(model, adapter)
3. On every tool call or state transition:
     a. Config-level: enforcer.enforce(user_role, tool_name, access_level)
     b. OAuth-level: check user.scopes against required scope
     c. If dangerous_operation_write: require human approval gate (regardless of casbin result)
```

### 6.8 pycasbin vs Built-in YAML Native

| Dimension | pycasbin | Built-in YAML (native) |
|-----------|----------|------------------------|
| Role hierarchy | ✅ built-in | ❌ flat list only |
| Attribute-based rules | ✅ with ABAC model | ❌ |
| Policy hot-reload | ✅ with adapter | ❌ (restart required) |
| External dependency | 1 pip package | 0 |
| Complexity | Medium (model.conf + policy) | Low (YAML list check) |
| Debugging | Casbin explain API | Simple print/assert |
| Best for | Complex multi-role, compliance-heavy | Most production use cases |

---

## 7. Tool Servers (MCP + API + Command)

### 7.1 MCP Server Integration

Our framework nodes can call MCP servers as tools. MCP servers expose capabilities (vector search, knowledge base query, external API) that nodes invoke within their permission allowlist.

```yaml
# framework.yaml — MCP tool discovery
mcp_servers:
  knowledge_base:
    command: "npx @anthropic/mcp-server-knowledge-base"
    args: ["--db-path", "./kb.sqlite"]
    tools: [search_documents, get_document]
  claims_gateway:
    command: "python mcp_servers/claims_server.py"
    env:
      API_KEY: "${CLAIMS_API_KEY}"
    tools: [claim_submit, claim_status]
  # Framework auto-discovers tools at startup.
  # Available tools: vector_search, claim_submit, claim_status, ...
```

### 7.2 Tool Registration

> **Note:** The canonical `ToolMeta.type` enum (`api | mcp | command | llm | a2a | sdk`) is defined in [HLD §4.4](./2026-06-16-deterministic-workflow-framework-design.md). This section adds tool ecosystem-specific detail (registry, defaults, SDK/A2A extensions).

Register tools via YAML configuration. Type values follow the [HLD §4.4](./2026-06-16-deterministic-workflow-framework-design.md) enum:

```yaml
# framework.yaml
tools:
  - name: calculate_premium_api
    type: api
    access_level: read
    api:
      method: POST
      url: "/api/v1/premium"
      timeout_ms: 5000
      request_body_schema:
        type: object
        properties:
          coverage_amount: { type: number }
          property_type: { type: string }

  - name: vector_search_mcp
    type: mcp
    access_level: read
    mcp:
      server: knowledge_base
      tool_name: search_documents

  - name: run_risk_model_cmd
    type: command
    access_level: read
    command:
      run: "python /opt/models/risk.py"
      timeout_ms: 30000
      sandbox: true

  - name: delegate_faq_to_agent
    type: a2a
    access_level: read
    a2a:
      agent_id: rag_faq
      mode: sync
      timeout_ms: 10000
      input_mapping:
        question: "{{params.question}}"
        conversation_context: "{{params.context}}"
      output_mapping:
        answer: "{{a2a_response.results.answer}}"
        sources: "{{a2a_response.results.sources}}"

  - name: opencode_review_code
    type: sdk
    access_level: read
    sdk:
      provider: opencode
      action: ask
      prompt_template: "Review the following code for security issues:\n\n{{params.code}}"
      timeout_ms: 30000
      context:
        working_directory: "/path/to/project"

  - name: claude_analyze_logs
    type: sdk
    access_level: read
    sdk:
      provider: anthropic
      action: do
      prompt_template: "Analyze these error logs and suggest fixes:\n\n{{params.logs}}"
      model: claude-sonnet-4-20250514
      timeout_ms: 60000
```

### 7.3 Claude Desktop Integration

When the framework is used with Claude Desktop, MCP tools are auto-exposed:

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "deterministic-workflow": {
      "command": "python",
      "args": ["-m", "deterministic_workflow.mcp_server"],
      "env": {
        "WORKFLOW_CONFIG": "workflows/home_insurance_quote.yaml"
      }
    }
  }
}
```

### 7.4 Tool Failure Routing to `errorNode`

When a tool invocation fails (timeout, permission denied, invalid response), the framework routes the execution to a configured `errorNode` instead of crashing the workflow. For the canonical errorNode strategy definitions, see [Routing & Execution §6.5](./2026-06-17-routing-execution-layer-design.md).

```yaml
# framework.yaml
tool_failure_handling:
  default_error_node: errorNode
  timeout_ms: 30000
  max_retries: 2

nodes:
  calculate_premium:
    tools: [calculate_premium_api, run_risk_model_cmd]
    on_tool_failure:
      route_to: errorNode       # overrides default_error_node
      fallback_on_timeout: true     # use cached/default value on timeout
      escalate_after: 3             # retries before escalating

  errorNode:
    strategies: [clarify, escalate, terminate]
    on_clarify: "ask user for missing/corrected input"
    on_escalate: "notify human agent with error context"
    on_terminate: "gracefully end conversation with apology"
```

This ensures deterministic behavior: every tool failure has a defined recovery path, and failures are auditable via LangSmith traces.

### 7.5 A2A Tool Type — Agent-to-Agent as a Tool

#### 7.5.1 Concept

Any node can call another agent as a tool — not just at the executor level (`a2a_invoke`), but as a tool in the node's `allowed_tools` list. This means an LLM node or code executor node can invoke another agent to delegate a sub-task, get a JSON result back, and continue its own logic.

```
Node (e.g., LLM node deciding what to do)
    │
    ├── allowed_tools: [lookup_property_record, delegate_faq_to_agent, ...]
    │
    ├── Node decides: "I need to answer a FAQ question"
    │
    ├── Calls tool: delegate_faq_to_agent(question="What is covered?")
    │         │
    │         ▼
    │   A2A Request → rag_faq agent
    │         │
    │         ▼
    │   A2A Response { status: "completed", results: { answer: "...", sources: [...] } }
    │
    └── Node extracts JSON result → continues workflow
```

**Key difference from `a2a_invoke` executor:**

| Dimension | `a2a_invoke` executor | `type: a2a` tool |
|-----------|----------------------|-------------------|
| **Scope** | The entire node IS the agent call | The agent call is one of many tools available to the node |
| **Control** | Node's sole purpose is to delegate | Node decides whether/when to call the agent |
| **LLM-friendly** | Not applicable (executor-level) | LLM nodes can select this tool dynamically |
| **Composability** | One agent per node | Multiple agents + APIs + commands in one node |
| **State mapping** | Full `input_mapping` from agentState | Param-based call from tool invocation params |

#### 7.5.2 A2A Tool Contract

Every A2A tool conforms to the standard `Tool` interface with `type: a2a`. The framework auto-generates the A2A envelope from the tool's YAML config — the developer never writes A2A messages manually.

```yaml
# A2A tool contract
Tool:
  name: string                              # unique tool identifier
  type: a2a                                 # agent-to-agent tool type
  access_level: read | write | sensitive_data_read | dangerous_operation_write
  a2a:
    agent_id: string                        # target agent identifier (registered in registry)
    mode: sync | async                      # caller waits or continues
    timeout_ms: integer                     # max wait for response
    input_mapping:                          # maps tool params → A2A request entities
      <param_name>: "{{params.<field>}}"
    output_mapping:                         # extracts fields from A2A response → tool result
      <output_name>: "{{a2a_response.results.<field>}}"

# A2A tool result is standard ToolResult JSON
ToolResult:
  success: boolean
  data: object                              # mapped from output_mapping
  error: string
  duration_ms: integer
  audit_entry:
    correlation_id: string                  # A2A correlation ID for traceability
    agent_id: string                        # which agent was called
    status: completed | failed | partial | timeout
```

#### 7.5.3 A2A Tool Input/Output Flow

```
1. Node invokes tool: delegate_faq_to_agent(question="What is covered?", context="...")
2. Framework resolves tool config → sees type: a2a
3. Framework queries Agent Registry for agent_id=rag_faq
4. Framework constructs A2A request:
     - Applies input_mapping: tool params → A2A entities
     - Generates correlation_id
     - Sets deadline from timeout_ms
5. Framework sends A2A request via standard A2A protocol (see A2A Protocol spec)
6. Target agent executes → returns A2A response
7. Framework applies output_mapping to extract tool result data
8. Framework returns ToolResult to calling node
```

#### 7.5.4 A2A Tool Permission

A2A tools participate in the existing permission model:

```yaml
# A2A tool with permission configuration
tools:
  - name: delegate_claim_to_agent
    type: a2a
    access_level: dangerous_operation_write    # claims processing
    a2a:
      agent_id: claims_processor
      mode: sync
      timeout_ms: 15000
      input_mapping:
        amount: "{{params.amount}}"
        quote_id: "{{params.quote_id}}"
      output_mapping:
        transaction_id: "{{a2a_response.results.transaction_id}}"
        status: "{{a2a_response.results.status}}"
    requires_approval: true                     # human-in-the-loop gate

# In node YAML — tool must be in allowlist
nodes:
  process_quote:
    executor: llm
    tool_allowlist: [calculate_premium_api, delegate_claim_to_agent]
    permission:
      allowed_tools: [calculate_premium_api, delegate_claim_to_agent]
```

#### 7.5.5 A2A Tool Error Handling

A2A tool failures follow the same pattern as all tool failures — route to `errorNode` after retry exhaustion:

```yaml
# Per-tool A2A retry configuration
tools:
  - name: delegate_verification_to_agent
    type: a2a
    a2a:
      agent_id: property_verification
      mode: sync
      timeout_ms: 30000
    retry:
      max_attempts: 2
      backoff: exponential
      on_exhausted: errorNode

# A2A-specific error categories
# Agent unreachable → retry → errorNode
# Agent timeout → retry → errorNode
# Agent returns status: failed → errorNode with gap_analysis
# Agent returns status: partial → configurable: accept partial or errorNode
# Permission denied (caller not in agent's allowed_callers) → immediate errorNode
```

#### 7.5.6 A2A Tool vs MCP Tool vs Sub-Workflow

| Dimension | `type: mcp` tool | `type: a2a` tool | `executor: sub_workflow` |
|-----------|-----------------|------------------|------------------------|
| **Semantic level** | Function call | Intent-based agent delegation | Full workflow delegation |
| **State** | Stateless operation | Agent with its own FSM | Agent with its own FSM |
| **Call pattern** | Tool invocation within any node | Tool invocation within any node | The node IS the delegation |
| **Result** | ToolResult { data } | ToolResult { data from agent } | Returns full agentState |
| **LLM can select** | Yes (in tool_allowlist) | Yes (in tool_allowlist) | No (executor-level) |
| **Config location** | `framework.yaml → tools:` | `framework.yaml → tools:` | `workflow.yaml → nodes:` |
| **Granularity** | Single operation | Agent-level goal | Agent-level goal |
| **Multi-turn** | No (stateless) | Yes (max_turns + correlation_id) | Yes (full sub-workflow) |

#### 7.5.7 Multi-Turn A2A Conversations

When a downstream agent cannot complete a task in a single response, the calling node (typically an LLM node) can engage in a multi-turn conversation with the agent. The LLM and the downstream agent exchange messages within a bounded turn budget — either completing the task or failing explicitly.

```
Calling Node (LLM)                           Downstream Agent (e.g., claims_processor)
    │                                              │
    ├── Turn 1: A2A Tool Call ──────────────────→ │
    │    delegate_claim(amount=500, method=ACH)  │   "Need more info: which account?"
    │←── A2A Response (status: incomplete) ──────┤
    │    { needs_clarification: "account_type" }   │
    │                                              │
    ├── Turn 2: A2A Tool Call (with context) ────→│
    │    delegate_claim(account_type="checking") │   "Processing claim..."
    │←── A2A Response (status: completed) ────────┤
    │    { transaction_id: "tx_123", status: "ok" }│
    │                                              │
    └── LLM extracts final result → continues      │
```

**Key properties:**

| Property | Behavior |
|----------|----------|
| **Turn budget** | Per-tool config: `max_turns` (default 3). After exhaustion → error |
| **Turn tracking** | Framework tracks turn count via `correlation_id`, enforces budget |
| **Status signals** | Agent responds with `status: completed | incomplete | failed` |
| **Incomplete response** | Agent returns `needs_clarification` field — LLM decides next turn |
| **Error on exhaustion** | Turn budget exhausted → `errorNode` with gap analysis |
| **Idempotency** | Same `correlation_id` across turns enables agent-side idempotency |

**Multi-turn A2A tool configuration:**

```yaml
tools:
  - name: delegate_claim_to_agent
    type: a2a
    access_level: dangerous_operation_write
    a2a:
      agent_id: claims_processor
      mode: sync
      timeout_ms: 15000
      max_turns: 5                          # max conversational turns
      turn_timeout_ms: 10000                # timeout per individual turn
      input_mapping:
        amount: "{{params.amount}}"
        method: "{{params.method}}"
        context: "{{params.previous_agent_responses}}"
      output_mapping:
        transaction_id: "{{a2a_response.results.transaction_id}}"
        status: "{{a2a_response.results.status}}"
        needs_clarification: "{{a2a_response.results.needs_clarification}}"
    on_turn_exhausted: errorNode
```

**Multi-turn execution flow:**

```
1. LLM node invokes A2A tool with initial params
2. Framework sends A2A request, receives response
3. IF response.status == "completed":
     → Extract output_mapping → return ToolResult to LLM node
4. IF response.status == "incomplete":
     → Return ToolResult with { needs_clarification, partial_results }
     → LLM node reviews clarification needs
     → LLM node calls SAME tool again with additional context
     → Framework attaches existing correlation_id (same conversation)
     → Repeat from step 2
5. IF response.status == "failed":
     → Return ToolResult with error → route to errorNode
6. IF turn_count >= max_turns AND not completed:
     → errorNode with gap analysis
```

**LLM-to-LangGraph for multi-turn handling:**

The framework leverages LangGraph's built-in tool-calling loop for multi-turn A2A. When the LLM node calls an A2A tool and receives `status: incomplete`, the framework injects the clarification needs into the LLM's next prompt, allowing it to decide whether to:
- Call the same agent again with more context
- Call a different tool
- Escalate to the user for input

```yaml
# LLM node with multi-turn A2A capability
nodes:
  process_complex_quote:
    executor: llm
    prompt: |
      You have access to multiple agents as tools. When an agent asks for
      clarification, decide whether to provide more context or escalate to
      the user. You have up to 5 turns per agent call.
    tool_allowlist:
      - delegate_claim_to_agent       # a2a tool with max_turns: 5
      - delegate_verification_to_agent  # a2a tool with max_turns: 3
      - calculate_premium_api            # regular API
    max_llm_tool_calls: 15               # total tool calls across all agents
```

**Multi-turn A2A error matrix:**

| Scenario | Turn N Behavior | Exhausted Behavior |
|----------|----------------|-------------------|
| Agent returns `status: incomplete` | LLM reviews, may call again with more context | errorNode: "Agent could not complete after N turns" |
| Agent returns `status: failed` | errorNode immediately (no retry without correction) | N/A — immediate escalation |
| Agent timeout on turn N | Retry per tool retry budget | errorNode if retries exhausted |
| Agent unreachable | Retry with backoff | errorNode |
| User interrupts mid-conversation | Suspend A2A conversation, push to phase_stack | Resume on user continuation |

--- — OpenCode / Claude SDK as a Tool

#### 7.6.1 Concept

Nodes can invoke AI coding assistants (OpenCode CLI, Claude SDK, OpenAI SDK) as tools. An LLM node or code executor can ask OpenCode to review code, ask Claude to analyze data, or delegate a coding task to an SDK — all through a unified `type: sdk` tool interface.

```
Node (e.g., code executor validating business logic)
    │
    ├── tool_allowlist: [opencode_review_code, claude_analyze_logs, ...]
    │
    ├── Node decides: "I need to review this generated SQL"
    │
    ├── Calls tool: opencode_review_code(code="SELECT * FROM ...")
    │         │
    │         ▼
    │   SDK Call → OpenCode CLI (opencode ask "...")
    │         │
    │         ▼
    │   SDK Response { result: "Found 2 issues: ...", ... }  (JSON)
    │
    └── Node extracts JSON result → continues workflow
```

#### 7.6.2 SDK Tool Contract

```yaml
# SDK tool contract
Tool:
  name: string                              # unique tool identifier
  type: sdk                                 # AI coding assistant tool type
  access_level: read | write | sensitive_data_read | dangerous_operation_write
  sdk:
    provider: opencode | anthropic | openai # which SDK/provider
    action: ask | do | chat                 # ask=query, do=execute task, chat=conversation
    prompt_template: string                 # template with {{params.<field>}} placeholders
    model: string                           # optional: model override (provider-specific)
    timeout_ms: integer
    context:                                # optional: execution context
      working_directory: string
      environment: object                   # env vars to set
    response_schema:                        # optional: enforce JSON output structure
      type: object
      properties: ...

# SDK tool result
ToolResult:
  success: boolean
  data:
    result: string                          # the SDK's text/code output
    structured: object                      # parsed JSON if response_schema provided
    tool_calls: array                       # any tool calls the SDK made internally
  error: string
  duration_ms: integer
  audit_entry:
    provider: string
    action: ask | do | chat
    prompt_hash: string                     # SHA-256 of rendered prompt
```

#### 7.6.3 Provider Actions Matrix

| Provider | `action: ask` | `action: do` | `action: chat` |
|----------|--------------|-------------|----------------|
| **opencode** | `opencode ask "<prompt>"` — query, get answer | `opencode do "<task>"` — execute multi-step task with tools | Multi-turn conversation via OpenCode |
| **anthropic** | Claude API with single turn (temperature=0) | Claude with tool use enabled, multi-step | Claude multi-turn conversation |
| **openai** | GPT API with single turn (temperature=0) | GPT with function calling, multi-step | GPT multi-turn conversation |

#### 7.6.4 SDK Tool Registration Examples

**OpenCode — Code Review (ask):**

```yaml
tools:
  - name: opencode_security_review
    type: sdk
    access_level: read
    sdk:
      provider: opencode
      action: ask
      prompt_template: >
        Review this code for security vulnerabilities, injection risks,
        and hardcoded secrets. Output JSON with findings and severity.

        Code:
        {{params.code}}
      response_schema:
        type: object
        properties:
          vulnerabilities:
            type: array
            items:
              type: object
              properties:
                type: { type: string }
                severity: { type: string, enum: [critical, high, medium, low] }
                line: { type: integer }
                description: { type: string }
                fix: { type: string }
      timeout_ms: 30000
```

**OpenCode — Execute Refactoring (do):**

```yaml
tools:
  - name: opencode_refactor_module
    type: sdk
    access_level: write
    sdk:
      provider: opencode
      action: do
      prompt_template: >
        Refactor the following Python module to follow SOLID principles.
        Keep all existing functionality and tests passing.

        Module file: {{params.file_path}}
        Requirements: {{params.requirements}}
      context:
        working_directory: "{{params.project_root}}"
      timeout_ms: 120000
```

**Claude SDK — Log Analysis (ask):**

```yaml
tools:
  - name: claude_analyze_error_logs
    type: sdk
    access_level: read
    sdk:
      provider: anthropic
      action: ask
      model: claude-sonnet-4-20250514
      prompt_template: >
        Analyze the following error logs from the last {{params.time_window}}.
        Identify patterns, root causes, and suggest remediation steps.
        Output JSON.

        Logs:
        {{params.logs}}
      timeout_ms: 60000
```

**Claude SDK — Generate SQL (do):**

```yaml
tools:
  - name: claude_generate_sql
    type: sdk
    access_level: read
    sdk:
      provider: anthropic
      action: do
      model: claude-sonnet-4-20250514
      prompt_template: >
        Generate a parameterized SQL query for the following requirements.
        Output only valid SQL with no explanation.

        Database: {{params.db_schema}}
        Requirements: {{params.requirements}}
      timeout_ms: 30000
```

#### 7.6.5 SDK Tool Execution Flow

```
1. Node invokes tool: opencode_review_code(code="def foo(): ...")
2. Framework resolves tool config → sees type: sdk, provider: opencode
3. Framework validates provider is available (CLI installed, API key present)
4. Framework renders prompt_template with params → full prompt
5. Framework invokes SDK:
     a. opencode ask: spawns `opencode ask "<prompt>"` process
     b. anthropic ask: calls Claude API via langchain-anthropic
     c. openai ask: calls GPT API via langchain-openai
6. Framework collects output:
     - If response_schema defined: validates JSON, coerces types
     - If no schema: returns raw text in result field
7. Framework returns ToolResult to calling node
```

#### 7.6.6 SDK Tool Permission & Sandboxing

```yaml
tools:
  - name: opencode_refactor_module
    type: sdk
    access_level: write                            # writes code/files
    sdk:
      provider: opencode
      action: do
      prompt_template: "..."
      sandbox:
        mode: workspace_only                      # restrict file access to project dir
        deny_commands: [rm, sudo, curl, wget]     # blocked shell commands
        allow_file_patterns: ["**/*.py", "**/*.yaml"]  # writable file patterns
        network: none                             # no external network access
```

#### 7.6.7 SDK Output Validation

When `response_schema` is configured, the framework enforces the same JSON guardrails as LLM nodes:

```
SDK Output → JSON Parse → Schema Validate → Field Presence Check → Type Coercion
                                                                       │
                                                            ┌──────────┘
                                                            │
                                                     on failure:
                                                     retry with schema reminder
                                                     → errorNode on exhaustion
```

```yaml
# SDK tool with structured output enforcement
tools:
  - name: opencode_code_audit
    type: sdk
    access_level: read
    sdk:
      provider: opencode
      action: ask
      prompt_template: >
        Audit the following code and output valid JSON.
        {{params.code}}
      response_schema:
        type: object
        required: [score, issues, summary]
        properties:
          score: { type: number, minimum: 0, maximum: 100 }
          issues:
            type: array
            items:
              type: object
              properties:
                category: { type: string }
                description: { type: string }
          summary: { type: string }
      max_schema_retries: 2          # retry if output doesn't match schema
```

---

## 8. State Machine — `transitions`

### 8.1 Role

Python `transitions` library provides the deterministic FSM layer. Our framework generates a `transitions.Machine` from the Domain Model YAML (states + transitions + guards), then wraps it into a LangGraph node.

### 8.2 Graphviz Export

Configure FSM visualization via YAML and export to Graphviz:

```yaml
# framework.yaml
fsm:
  source: "domain-models/home-insurance.yaml"
  visualization:
    format: png
    output: "docs/diagrams/home_insurance_fsm.png"
    engine: dot                    # Graphviz layout engine
    render_on_build: true          # auto-export on graph compilation

  # Generated from domain-model YAML: states, transitions, guards
  # Exported as static FSM diagram for documentation
```

### 8.3 Integration Flow

```
domain-model.yaml
    │
    ▼
FSMGenerator → transitions.Machine (states, transitions, guards)
    │
    ▼
GraphCompiler → LangGraph StateGraph (nodes, conditional edges)
    │
    ▼
Visualization:
  - transitions: graph.draw() → PNG (static)
  - langgraph dev → browser (interactive)
  - LangFlow → drag-and-drop editor
```

---

## 9. PII Detection — Presidio

### 9.1 Role

Microsoft Presidio provides PII detection and anonymization. The **authoritative PII processing design** — including post-generation scrubbing, prompt filtering, audit log redaction, and PII rules in the domain model — is defined in [Response Generation Layer §8 Sensitive Field Handling](./2026-06-17-response-generation-layer-design.md).

The tool ecosystem integrates Presidio as the PII detection engine via declarative configuration:

```yaml
# framework.yaml
pii:
  engine: presidio
  language: en
  masking_strategy: partial_mask
```

---

## 10. LLM Providers

### 10.1 Supported Providers

| Provider | Package | Use |
|----------|---------|-----|
| **OpenAI** | `langchain-openai` | Extraction, decision, response generation |
| **Anthropic (Claude)** | `langchain-anthropic` | Extraction, response generation, goal setting |
| **Local (Ollama)** | `langchain-ollama` | Offline extraction, PII-safe processing |
| **Azure OpenAI** | `langchain-openai` | Enterprise deployments |

### 10.2 Provider Configuration

```yaml
# framework.yaml
llm:
  default_provider: openai
  providers:
    openai:
      model: gpt-4o
      temperature: 0
      max_tokens: 4096
    anthropic:
      model: claude-sonnet-4-20250514
      temperature: 0
      max_tokens: 4096

  # Per-node override
  nodes:
    extract_property_info:
      provider: anthropic
      temperature: 0
    generate_quote_response:
      provider: openai
      temperature: 0.3
```

---

## 11. Complete Tool Integration Example

Full-stack configuration: from YAML → LangFlow → LangGraph → LangSmith — all declarative:

```yaml
# framework.yaml — complete integration config
engine:
  domain_model: "domain-models/home-insurance.yaml"
  workflow_config: "workflows/home_insurance_quote.yaml"
  rule_engine: durable_rules
  checkpoint_backend: "postgresql://localhost:5432/langgraph"

llm:
  default_provider: openai
  providers:
    openai: { model: gpt-4o, temperature: 0, max_tokens: 4096 }
    anthropic: { model: claude-sonnet-4-20250514, temperature: 0, max_tokens: 4096 }

langsmith:
  api_key: "${LANGSMITH_API_KEY}"
  tracing: true
  project: "home-insurance-quote"

mcp_servers:
  knowledge_base:
    command: "npx @anthropic/mcp-server-knowledge-base"
    args: ["--db-path", "./kb.sqlite"]
  claims_gateway:
    command: "python mcp_servers/claims_server.py"
    env: { API_KEY: "${PAYMENT_API_KEY}" }

tools:
  - name: calculate_premium_api
    type: api
    access_level: read
    api: { method: POST, url: "/api/v1/premium", timeout_ms: 5000 }
  - name: run_risk_model_cmd
    type: command
    access_level: read
    command: { run: "python /opt/models/risk.py", timeout_ms: 30000, sandbox: true }
  - name: delegate_faq_to_agent
    type: a2a
    access_level: read
    a2a:
      agent_id: rag_faq
      mode: sync
      timeout_ms: 10000
      input_mapping:
        question: "{{params.question}}"
        conversation_context: "{{params.context}}"
      output_mapping:
        answer: "{{a2a_response.results.answer}}"
        sources: "{{a2a_response.results.sources}}"
  - name: opencode_security_review
    type: sdk
    access_level: read
    sdk:
      provider: opencode
      action: ask
      prompt_template: "Review this code for security issues:\n\n{{params.code}}"
      timeout_ms: 30000

tool_failure_handling:
  default_error_node: errorNode
  timeout_ms: 30000
  max_retries: 2

fsm:
  source: "domain-models/home-insurance.yaml"
  visualization: { format: png, output: "docs/diagrams/home_insurance_fsm.png" }

pii:
  engine: presidio
  language: en
  masking_strategy: partial_mask

export:
  langflow: "langflow/workflows/home_insurance.json"
  langgraph: "langgraph.json"
```

**Runtime flow:**
1. Framework loads `framework.yaml` → auto-discovers all tools, rule engines, PII config
2. Compiles LangGraph `StateGraph` from domain model + workflow
3. Exports to LangFlow JSON for visual editing and LangGraph JSON for dev server
4. Every conversation is auto-traced in LangSmith Studio
```

---

## 12. Tool Decision Matrix

| Need | Tool | Why |
|------|------|-----|
| Build workflow visually | **LangFlow** | Drag-and-drop, exports to code |
| Local dev + debug | **LangGraph CLI** | Hot reload, graph view, free |
| Production trace + eval | **LangSmith Studio** | Time-travel debug, eval datasets |
| FSM definition | **transitions** | Python-native, Graphviz export |
| Graph runtime | **LangGraph** | State graph, checkpoint, streaming |
| Complex rules | **durable_rules** | When/then inference, Drools-like |
| Simple rules | **business-rules** | Zero-inference YAML rules |
| Expert system rules | **pyknow** | Fact/KnowledgeEngine model |
| Permission enforcement (complex) | **pycasbin** | RBAC + ABAC, role hierarchy, policy hot-reload |
| Permission enforcement (simple) | **Built-in YAML** | No dependency, list check |
| PII detection | **Presidio** | Microsoft-backed, multi-language |
| External tools | **MCP servers** | Any language, standard protocol |
| Claude Desktop | **MCP config** | Auto-expose workflow as tool |
| Delegate to another agent | **A2A tool (`type: a2a`)** | Intent-based agent delegation as a tool, agent has its own FSM |
| Invoke other agent (full node) | **Sub-workflow (`executor: sub_workflow`)** | The node IS the delegation, full StateGraph nesting |
| AI code review / analysis | **SDK tool (`type: sdk`, `action: ask`)** | OpenCode ask / Claude ask, structured JSON output |
| AI refactoring / multi-step task | **SDK tool (`type: sdk`, `action: do`)** | OpenCode do / Claude with tool use, workspace-scoped |
| Mandatory JSON output | **LLM Gateway** | output_schema required for every LLM call |
| SDK output validation | **SDK tool `response_schema`** | JSON parse + schema validate + field check + type coercion |

---

## 13. Open Questions

1. **Should LangFlow components be auto-generated from the domain model YAML, or require manual wiring?** Auto-generation simplifies adoption but risks over-constraining the visual editor experience.

2. **What is the fault-tolerance boundary for MCP tool failures?** When an MCP server (e.g., claims gateway) is unreachable, should the workflow queue the request for retry, fall back to a cached response, or escalate immediately?

3. **How do we version and rollback eval datasets in LangSmith?** Eval results may drift as domain models evolve — do we pin eval datasets to workflow version tags?

4. **Can the framework support non-Python LangGraph runtimes?** LangGraph.js is production-ready for TypeScript users; should the framework spec remain Python-only or define a runtime-agnostic abstraction layer?

5. **How are custom rule engines validated at registration time?** The YAML config specifies a module and class — should the framework enforce a contract check (interface compliance, smoke test) before accepting the engine?

6. **Should pycasbin policies be editable at runtime (hot-reload via database adapter) or only at deploy time (YAML → CSV generation)?** Hot-reload simplifies operations for large orgs but introduces consistency risk across instances.

7. **Should A2A tools support streaming agent responses?** When a node calls an agent via `type: a2a`, should partial results stream token-by-token, or only complete responses? Streaming enables real-time UX but complicates the tool contract.

8. **What is the recursion limit for A2A tool chains?** Agent A (tool) → Agent B (tool) → Agent C ... — should there be a configurable max depth to prevent infinite agent chains?

9. **Should SDK tools require an explicit `response_schema` for all `action: ask` calls?** Consistent with the LLM Gateway rule that all LLM output is JSON — but some SDK queries are inherently free-text.

10. **How should SDK tool sandboxing work for `action: do`?** OpenCode can modify files — should the framework enforce a copy-on-write workspace, git branch, or Docker container per SDK invocation?

11. **Should SDK tools be pooled as long-running sessions?** Instead of spawning a new process per call, maintain a persistent OpenCode/Claude session for lower latency on repeated calls.

12. **What is the cost governance model for SDK tools?** SDK calls to Claude/GPT consume API credits — should the framework enforce per-node, per-workflow, or per-conversation token budgets for SDK tools?

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — framework architecture, permission model
- [Extraction Layer](./2026-06-17-extraction-layer-design.md) — rule engine integration in Validate node
- [Routing & Execution](./2026-06-17-routing-execution-layer-design.md) — rule engine in Decision nodes, tool system
- [Response Generation](./2026-06-17-response-generation-layer-design.md) — PII scrubbing, widget rendering
- [LangFlow](https://github.com/langflow-ai/langflow) — visual editor (150k stars, MIT)
- [LangGraph CLI](https://pypi.org/project/langgraph-cli/) — dev server + graph visualization
- [LangSmith Studio](https://docs.langchain.com/langsmith/studio) — debug + monitor IDE
- [transitions](https://github.com/pytransitions/transitions) — Python state machine library
- [durable_rules](https://github.com/jruizgit/rules) — Python forward-chaining rule engine
- [Presidio](https://github.com/microsoft/presidio) — Microsoft PII detection
