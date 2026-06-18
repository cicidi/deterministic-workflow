# MCP API Protocol

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: MCP (Model Context Protocol) server interface, tool definitions, provider configuration, MCP vs REST comparison.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial MCP API protocol spec: server interface, tool definitions, provider config, MCP vs REST comparison |

---

## 1. Role

The framework exposes its API as a standard **MCP (Model Context Protocol) server**. External AI tools — Claude Desktop, OpenAI, Google AI, and other MCP-compatible clients — call the framework like any other MCP tool. No custom SDKs. No bespoke REST clients. One protocol, universal access.

```
┌──────────────────────────────────────────────────────────────┐
│                     MCP CLIENTS                               │
├──────────────┬──────────────┬──────────────┬─────────────────┤
│  Claude      │  OpenAI      │  Google AI   │  Custom         │
│  Desktop     │  (MCP SDK)   │  (MCP SDK)   │  MCP Client     │
└──────┬───────┴──────┬───────┴──────┬───────┴────────┬────────┘
       │              │              │                │
       ▼              ▼              ▼                ▼
┌──────────────────────────────────────────────────────────────┐
│              MCP Server (Deterministic Framework)              │
│                                                               │
│  Tools:  create_conversation, send_message,                   │
│          resume_conversation, get_status                      │
│                                                               │
│  Resources: conversation://{id}/state,                        │
│             conversation://{id}/audit                         │
└──────────────────────────────────────────────────────────────┘
```

### 1.1 What MCP Provides

- ✅ **Standardized tool discovery** — clients auto-discover available workflow endpoints via `tools/list`
- ✅ **Streaming support** — LLM responses stream token-by-token through MCP
- ✅ **Resource access** — conversation state, audit logs exposed as MCP resources
- ✅ **Provider-agnostic** — write once, connect to any MCP-compatible AI tool
- ✅ **Permission model** — MCP server enforces tool-level access control per client

### 1.2 What MCP Does NOT Replace

- ❌ **Not an API gateway** — does not replace Kong, Envoy, or AWS API Gateway for routing/rate-limiting
- ❌ **Not a replacement for REST** — REST APIs remain available for programmatic/non-AI clients
- ❌ **Not an authentication layer** — auth is handled by the framework's existing token verification (see Auth spec)

---

## 2. MCP Server Interface

The framework auto-exposes workflow endpoints as MCP tools. Each workflow node that accepts external input becomes an MCP tool. The server handles JSON-RPC 2.0 messaging, capability negotiation, and transport (stdio or HTTP/SSE).

### 2.1 Auto-Exposure of Workflow Endpoints

```yaml
# framework.yaml
mcp:
  enabled: true
  transport: sse                           # sse | stdio
  endpoint: /mcp                           # SSE endpoint path
  port: 8000
  tool_discovery: auto                     # auto | manual
  auto_expose:
    source: workflows                      # expose all workflow entry points
    naming: snake_case                     # snake_case | camelCase
    prefix: ""                             # optional prefix for tool names
```

When `tool_discovery: auto`, the framework scans all registered workflows and generates MCP tool definitions from their entry-point nodes.

### 2.2 MCP Capability Advertisement

On connection, the server advertises:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "capabilities": {
      "tools": {
        "listChanged": true
      },
      "resources": {
        "subscribe": true,
        "listChanged": false
      },
      "logging": {}
    },
    "serverInfo": {
      "name": "deterministic-workflow-framework",
      "version": "0.2.0"
    }
  }
}
```

### 2.3 Transport Methods

| Transport | Protocol | Use Case | Client Support |
|-----------|----------|----------|----------------|
| **SSE (HTTP)** | HTTP POST + SSE stream | Remote deployments, multi-client | Claude Desktop, OpenAI, Google AI |
| **stdio** | Process stdin/stdout | Local development, embedded agents | Claude Desktop, CLI tools |
| **WebSocket** | WS Upgrade | Low-latency streaming | Custom clients (future) |

```yaml
# framework.yaml — transport configuration
mcp:
  transport:
    default: sse
    sse:
      host: "0.0.0.0"
      port: 8000
      path: /mcp
      cors:
        origins: ["*"]
    stdio:
      enabled: false                      # mostly for local dev
```

---

## 3. Tool Definitions

### 3.1 `create_conversation`

Initiates a new conversation within a workflow.

```yaml
# MCP tool: create_conversation
tool:
  name: create_conversation
  description: >
    Create a new conversation in the deterministic workflow framework.
    Returns a conversation ID that can be used for subsequent send_message calls.
  inputSchema:
    type: object
    properties:
      workflow_id:
        type: string
        description: "The workflow to start (e.g., 'home_insurance_quote')"
      user_id:
        type: string
        description: "The user initiating the conversation"
      initial_context:
        type: object
        description: "Optional initial context to seed agentState"
    required: [workflow_id, user_id]

  # Example response
  outputSchema:
    type: object
    properties:
      conversation_id:
        type: string
        description: "UUID v4 conversation identifier"
      state:
        type: string
        description: "Initial conversation state (always 'created')"
      agent_message:
        type: string
        description: "Initial greeting or prompt from the agent"
    required: [conversation_id, state]
```

### 3.2 `send_message`

Sends a user message to an active conversation and returns the agent's response.

```yaml
# MCP tool: send_message
tool:
  name: send_message
  description: >
    Send a user message to an existing conversation.
    The framework runs the full three-layer pipeline (Extract → Decide → Respond)
    and returns a structured JSON response.
  inputSchema:
    type: object
    properties:
      conversation_id:
        type: string
        description: "The conversation to send the message to"
      message:
        type: string
        description: "The user's natural language message"
      attachments:
        type: array
        items:
          type: object
          properties:
            type: { type: string }
            url: { type: string }
            metadata: { type: object }
        description: "Optional file attachments"
      metadata:
        type: object
        description: "Optional request metadata"
    required: [conversation_id, message]

  outputSchema:
    type: object
    properties:
      conversation_id:
        type: string
      agent_message:
        type: string
        description: "The agent's text response"
      intent:
        type: string
        description: "Classified intent for this turn"
      confidence:
        type: number
        description: "Intent classification confidence (0-1)"
      state:
        type: string
        description: "Current conversation state after processing"
      components:
        type: array
        description: "Rich UI components (cards, forms, etc.)"
    required: [conversation_id, agent_message, intent, state]
```

### 3.3 `resume_conversation`

Resumes a paused or interrupted conversation from the last checkpoint.

```yaml
# MCP tool: resume_conversation
tool:
  name: resume_conversation
  description: >
    Resume an existing conversation from its last checkpoint.
    Restores agentState, conversation history, and execution position.
  inputSchema:
    type: object
    properties:
      conversation_id:
        type: string
        description: "The conversation to resume"
      user_id:
        type: string
        description: "The user resuming the conversation (must match original)"
      resume_from:
        type: string
        description: "Optional: override checkpoint to resume from."
        enum: [latest, specific]
      checkpoint_id:
        type: string
        description: "Required if resume_from is 'specific'"
    required: [conversation_id, user_id]

  outputSchema:
    type: object
    properties:
      conversation_id:
        type: string
      state:
        type: string
        description: "Current state after resume (active)"
      agent_message:
        type: string
        description: "Agent message acknowledging resume or continuing"
      restored_at:
        type: string
        description: "Timestamp of the restored checkpoint"
    required: [conversation_id, state]
```

### 3.4 `get_status`

Returns the current status and metadata of a conversation.

```yaml
# MCP tool: get_status
tool:
  name: get_status
  description: >
    Get the current status, state, and metadata for a conversation.
    Does not modify the conversation.
  inputSchema:
    type: object
    properties:
      conversation_id:
        type: string
        description: "The conversation to query"
    required: [conversation_id]

  outputSchema:
    type: object
    properties:
      conversation_id:
        type: string
      user_id:
        type: string
      workflow_id:
        type: string
      lifecycle_state:
        type: string
        enum: [created, active, paused, completed, abandoned, timeout]
      current_phase:
        type: string
        description: "Current workflow phase (e.g., 'collect_property_info')"
      turn_count:
        type: integer
      created_at:
        type: string
      last_active_at:
        type: string
      checkpoint_count:
        type: integer
    required: [conversation_id, lifecycle_state, turn_count]
```

### 3.5 Tool Allowlist

Per-client tool access control via YAML config:

```yaml
# framework.yaml
mcp:
  tool_allowlist:
    default: [create_conversation, send_message, resume_conversation, get_status]
    
    # Restrict specific clients
    clients:
      claude_desktop:
        allow: [create_conversation, send_message, resume_conversation, get_status]
      openai:
        allow: [send_message, get_status]             # read-mostly
      internal_agent:
        allow: ["*"]                                   # full access
      read_only_dashboard:
        allow: [get_status]                            # dashboard only
```

---

## 4. YAML Config for MCP Server Setup

Full MCP server configuration within the framework's `framework.yaml`:

```yaml
# framework.yaml — complete MCP server configuration
mcp:
  enabled: true
  
  server:
    name: "deterministic-workflow-framework"
    version: "0.2.0"
    description: "MCP server for deterministic AI agent workflows"
    transport: sse
    host: "0.0.0.0"
    port: 8000
    path: /mcp
    cors:
      origins: ["*"]

  tools:
    discovery: auto                      # auto | manual
    auto_expose:
      source: workflows
      naming: snake_case
    manual_tools:                        # only relevant if discovery: manual
      - name: create_conversation
        workflow: home_insurance_quote
        node: entry_point

  resources:
    enabled: true
    expose:
      - pattern: "conversation://{id}/state"
      - pattern: "conversation://{id}/audit"
      - pattern: "workflow://{id}/schema"

  authentication:
    required: true
    method: bearer_token                  # bearer_token | api_key | none
    token_verification:
      provider: auth0                     # same as framework auth config

  rate_limiting:
    enabled: true
    requests_per_minute: 60
    burst: 10

  logging:
    level: info                           # debug | info | warn
    format: json                          # json | text
```

---

## 5. Provider Configuration

### 5.1 Claude Desktop

```json
{
  "mcpServers": {
    "deterministic-workflow": {
      "command": "python",
      "args": ["-m", "deterministic_workflow.mcp_server"],
      "env": {
        "FRAMEWORK_CONFIG": "/path/to/framework.yaml",
        "ENV": "prod"
      },
      "transport": "sse",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### 5.2 OpenAI (MCP SDK)

```yaml
# OpenAI MCP config (via openai-agents SDK)
mcp_servers:
  deterministic_workflow:
    transport: sse
    url: "http://localhost:8000/mcp"
    auth:
      type: bearer
      token: "${FRAMEWORK_API_TOKEN}"
    tool_filter:
      include: [create_conversation, send_message, resume_conversation, get_status]
```

### 5.3 Google AI (MCP SDK)

```yaml
# Google AI MCP config
mcp_servers:
  - name: deterministic-workflow
    transport: sse
    endpoint: "http://localhost:8000/mcp"
    headers:
      Authorization: "Bearer ${FRAMEWORK_API_TOKEN}"
    tools:
      - create_conversation
      - send_message
      - resume_conversation
      - get_status
```

### 5.4 Generic MCP Client (stdio transport)

```json
{
  "mcpServers": {
    "deterministic-workflow": {
      "command": "python",
      "args": ["-m", "deterministic_workflow.mcp_server", "--transport", "stdio"],
      "env": {
        "FRAMEWORK_CONFIG": "/path/to/framework.yaml",
        "ENV": "dev"
      }
    }
  }
}
```

---

## 6. MCP vs REST Comparison

### 6.1 Why MCP Over Traditional REST API

| Dimension | MCP (Model Context Protocol) | REST API |
|-----------|------------------------------|----------|
| **Client integration** | Zero-code for AI tools — auto-discovery via `tools/list` | Each client must implement HTTP calls, parse JSON, handle errors |
| **Tool discovery** | Built-in — client asks server for available tools | Manual — requires reading API docs or OpenAPI spec |
| **Streaming** | Native SSE transport, token-by-token streaming | Requires custom SSE or WebSocket implementation |
| **Schema validation** | Server declares `inputSchema`; clients validate before sending | Client must validate against OpenAPI spec manually |
| **AI-native** | Designed for LLM → tool calls; structured prompts as first-class | Designed for programmatic → API calls |
| **State management** | Conversation state exposed as MCP Resources (`conversation://{id}/state`) | Requires custom endpoints for state queries |
| **Error handling** | Standard JSON-RPC error codes with structured error data | HTTP status codes + custom error body (inconsistent) |
| **Client ecosystem** | Claude Desktop, OpenAI, Google AI, LangChain — all support MCP | Every HTTP client supports REST |
| **Versioning** | Server advertises version in `initialize` response | API versioning requires URL paths or headers |
| **Multi-provider** | One MCP server → all AI providers | REST is universal but not AI-optimized |

### 6.2 When to Use REST Instead

| Scenario | Recommendation |
|----------|---------------|
| Non-AI clients (mobile apps, web frontends) | REST — MCP is AI-specific |
| High-throughput programmatic access | REST — MCP adds JSON-RPC overhead |
| Existing REST infrastructure (API gateways, rate-limiting) | REST — leverage existing tooling |
| Simple CRUD operations on conversations | REST — simpler than MCP tool calls |

### 6.3 Dual-Protocol Strategy

The framework supports both MCP and REST simultaneously:

```yaml
# framework.yaml
protocols:
  mcp:
    enabled: true
    transport: sse
    port: 8000
  rest:
    enabled: true
    port: 8001
    openapi_spec: true                 # auto-generate OpenAPI from MCP tool schemas
    endpoints:
      # REST endpoints mirror MCP tools
      - POST   /v1/conversations                  → create_conversation
      - POST   /v1/conversations/{id}/messages    → send_message
      - POST   /v1/conversations/{id}/resume      → resume_conversation
      - GET    /v1/conversations/{id}             → get_status
```

---

## 7. Integration with Existing Framework Components

### 7.1 Auth Flow via MCP

```
MCP Client (Claude Desktop)
    │
    │   initialize request
    ▼
MCP Server
    │
    │   verify MCP client identity (Bearer token)
    ▼
[Token Verification]  ← same Auth0/Okta/Keycloak pipeline from Auth spec
    │
    └── user context injected into agentState
```

### 7.2 Checkpoint Integration

```yaml
# MCP resources expose checkpoints
resources:
  - uri: "conversation://{conversation_id}/state"
    name: "Conversation State"
    description: "Full agentState JSON for the conversation"
    mimeType: "application/json"
  
  - uri: "conversation://{conversation_id}/checkpoint/{checkpoint_id}"
    name: "Checkpoint Snapshot"
    description: "A specific LangGraph checkpoint for time-travel debugging"
    mimeType: "application/json"
```

### 7.3 Observability

MCP tool invocations are automatically traced:

```yaml
observability:
  mcp_metrics:
    enabled: true
    collect:
      - tool_call_count            # per-tool invocation count
      - tool_call_latency_ms       # p50, p95, p99
      - tool_error_rate            # per-tool error rate
      - active_connections         # concurrent MCP connections
    export:
      format: prometheus
      endpoint: /metrics
```

---

## 8. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| **Unauthorized MCP clients** | Bearer token verification on every MCP request; tool allowlists per client |
| **Tool abuse (excessive calls)** | Rate limiting (60 req/min default); per-tool quotas |
| **Conversation data exposure** | `user_id` scoping — MCP clients can only access their own conversations |
| **Man-in-the-middle** | SSE over HTTPS required in production; stdio inherently secure |
| **Injection via tool inputs** | All MCP tool inputs pass through the same Layer 1 extraction/validation pipeline |

---

## 9. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should the MCP server support dynamic tool registration (adding/removing tools at runtime without restart)? | Zero-downtime workflow updates |
| 2 | How should MCP handle long-running tool calls (e.g., `send_message` that takes >30s due to LLM latency)? Should it use MCP's progress notifications? | Client timeout handling |
| 3 | Should the framework support MCP Resources subscription (push notifications on state changes) or only polling? | Real-time dashboards vs complexity |
| 4 | For multi-tenant SaaS deployments, should there be one MCP server per tenant or one server with tenant routing? | Scalability and isolation |
| 5 | Should MCP tool responses include LangSmith trace URLs for debugging? | Developer experience vs response size |
| 6 | How should the MCP server advertise different tool sets per environment (dev vs prod workflows)? | Environment parity |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — §2 Core Architecture, §4.1 Framework Principles
- [Auth & Token Verification](./2026-06-17-auth-token-verification.md) — Token verification pipeline (reused for MCP)
- [Conversation Lifecycle](./2026-06-17-conversation-lifecycle.md) — Lifecycle states, checkpoint integration
- [Observability & Monitoring](./2026-06-17-observability-monitoring.md) — MCP metrics collection
- [Tool Ecosystem](./2026-06-17-tool-ecosystem.md) — MCP server integration with existing tool stack
- [Model Context Protocol Specification](https://modelcontextprotocol.io/specification) — Official MCP spec
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — Reference Python implementation
