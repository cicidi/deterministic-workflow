# Conversation Lifecycle

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Full conversation lifecycle states, checkpoint strategy, timeout policy, resume flow, audit trail, multi-device support.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial conversation lifecycle spec: states, trace_id = user_id, checkpoints, timeout, resume, audit, multi-device |

---

## 1. Role

Every conversation in the framework follows a well-defined lifecycle from creation to archival. The conversation is the unit of interaction, tracking, and recovery. Each conversation is identified by a `conversation_id` and traced across systems via `trace_id = user_id`.

```
┌──────────────────────────────────────────────────────────┐
│                  CONVERSATION LIFECYCLE                    │
│                                                           │
│   created ──→ active ──→ completed                        │
│                │  ↑                                       │
│                │  │ resume                                │
│                ▼  │                                      │
│              paused ──→ abandoned                         │
│                │                                          │
│                ▼                                          │
│             timeout ──→ archived                          │
└──────────────────────────────────────────────────────────┘
```

### 1.1 What the Lifecycle Covers

- ✅ **State transitions** — every valid path between lifecycle states
- ✅ **Checkpoint strategy** — when to save, when to restore
- ✅ **Timeout policy** — idle detection and automatic state transitions
- ✅ **Resume flow** — restoring conversations from cold storage
- ✅ **Audit trail** — logging every transition for compliance
- ✅ **Multi-device** — same user, multiple concurrent conversations

### 1.2 What the Lifecycle Does NOT Cover

- ❌ **Workflow state (FSM)** — this is the internal business state managed by the state machine, not the lifecycle
- ❌ **Session management** — login/logout, token refresh (see Auth spec)
- ❌ **Message history storage** — LangGraph checkpoints handle this
- ❌ **User identity management** — see Auth spec

---

## 2. Lifecycle States

### 2.1 State Definitions

| State | Description | Transitions To | Checkpoint |
|-------|-------------|----------------|------------|
| **created** | Conversation record created, no messages sent yet | active, abandoned | None |
| **active** | User is actively interacting; full three-layer pipeline runs | paused, completed, abandoned, timeout | On every user turn |
| **paused** | Conversation intentionally paused (user or system-initiated); state frozen | active, abandoned, timeout | On pause |
| **completed** | Goal met; terminal state for successful conversations | (terminal) | On completion |
| **abandoned** | User explicitly ends conversation or goal unachievable; terminal state | (terminal) | On abandonment |
| **timeout** | System-triggered idle timeout; can be resumed | active, archived | On timeout |
| **archived** | Cold storage after extended timeout (24h+); read-only | (terminal, read-only) | Archive snapshot |

### 2.2 State Transition Rules

```yaml
lifecycle:
  states:
    created:
      on:
        first_message: active
        abandon: abandoned
    
    active:
      on:
        pause: paused
        complete: completed
        abandon: abandoned
        idle_30min: timeout
    
    paused:
      on:
        resume: active
        idle_24h: archived
        abandon: abandoned
    
    timeout:
      on:
        resume: active
        idle_24h: archived
    
    completed:
      terminal: true
      archive_after_days: 90
    
    abandoned:
      terminal: true
      archive_after_days: 30
    
    archived:
      terminal: true
      read_only: true
```

### 2.3 Lifecycle State Machine (YAML View)

```yaml
# lifecycle_fsm.yaml — valid transitions
lifecycle_state_machine:
  initial: created
  
  transitions:
    - from: created
      to: active
      trigger: first_message
      guard: user_id == conversation.user_id
    
    - from: created
      to: abandoned
      trigger: user_abandon
      guard: no_messages_sent
    
    - from: active
      to: paused
      trigger: user_pause | system_pause
      before: save_checkpoint
    
    - from: active
      to: completed
      trigger: goal_met
      before: save_final_checkpoint
      after: log_completion_audit
    
    - from: active
      to: abandoned
      trigger: user_abandon | goal_unachievable
      before: save_final_checkpoint
    
    - from: active
      to: timeout
      trigger: idle_timer_expired
      guard: idle_duration >= 30min
      before: save_checkpoint
    
    - from: paused
      to: active
      trigger: user_resume
      after: restore_checkpoint | hydrate_context
    
    - from: paused
      to: archived
      trigger: idle_24h_timer
      before: archive_conversation
    
    - from: timeout
      to: active
      trigger: user_resume
      after: restore_checkpoint | hydrate_context
    
    - from: timeout
      to: archived
      trigger: idle_24h_timer
      before: archive_conversation
```

---

## 3. Tracing Model: `trace_id = user_id`

### 3.1 Why `user_id` as Trace ID

```
trace_id = user_id
```

Each user has a single `trace_id` that spans all their conversations. This enables:

- **Cross-conversation tracing** — all of a user's interactions across multiple conversations form a single trace
- **Compliance correlation** — audit trails for a single user are queryable by one ID
- **System-to-system handoff** — when a conversation is escalated to a human agent, the `user_id` trace continues into the CRM
- **Simple integration** — external systems (CRM, billing, support desk) already key on `user_id`

### 3.2 Trace Hierarchy

```
user_id (trace_id)
  ├── conversation_1
  │     ├── turn_1  → Layer 1 → Layer 2 → Layer 3
  │     ├── turn_2  → Layer 1 → Layer 2 → Layer 3
  │     └── turn_n
  ├── conversation_2
  │     ├── turn_1
  │     └── turn_2
  └── conversation_n
```

### 3.3 Trace Configuration

```yaml
tracing:
  model: user_id_as_trace      # user_id_as_trace | conversation_as_trace
  
  # When trace_id = user_id, each conversation is a span under the user trace
  span_hierarchy:
    root: "user:{user_id}"
    child: "conversation:{conversation_id}"
    grandchild: "turn:{turn_number}"
  
  propagation:
    # Trace context propagated to external systems via HTTP headers
    headers:
      - "X-Trace-ID: {user_id}"
      - "X-Conversation-ID: {conversation_id}"
      - "X-Turn-ID: {turn_number}"
```

---

## 4. Checkpoint Strategy

### 4.1 When to Checkpoint

| Lifecycle Event | Checkpoint Action | Storage Backend |
|-----------------|-------------------|-----------------|
| **Every user turn** | Auto-save after Layer 3 response | In-memory (dev) / PostgreSQL (prod) |
| **On pause** | Full state snapshot | PostgreSQL / Redis |
| **On completion** | Final snapshot + archive | PostgreSQL |
| **On timeout** | Snapshot before transitioning | PostgreSQL |
| **On abandon** | Final snapshot | PostgreSQL |
| **On archive** | Read-only archive copy | Object storage (S3/GCS) |

### 4.2 Checkpoint Content

```yaml
checkpoint:
  schema:
    metadata:
      checkpoint_id: string           # UUID
      conversation_id: string
      user_id: string                 # trace_id
      lifecycle_state: string
      created_at: datetime
      turn_number: integer
    
    workflow_state:
      current_phase: string           # e.g., "collect_property_info"
      phase_stack: array              # return stack for nested phases
      agent_state_snapshot: object    # full AgentState copy
    
    context:
      extraction_result: object       # last Layer 1 output
      routing_decision: object        # last Layer 2 output
      response_data: object           # last Layer 3 output
    
    messages:
      history: array                  # last N messages (configurable window)
      window_size: 6                  # matches CONTEXT_WINDOW_SIZE
    
    audit:
      state_transitions: array        # all lifecycle transitions since creation
      llm_calls: array                # LLM call records from LLM Gateway
      tool_calls: array               # tool invocation records
```

The canonical AgentState schema is defined in [Domain Model §10.1](./2026-06-17-domain-model-design.md).

### 4.3 Per-Environment Checkpoint Backend

```yaml
# checkpoint config — references Environment Config spec §3
checkpoint:
  dev:
    backend: in_memory
    # Data lost on process restart — fine for dev
  
  e2e:
    backend: sqlite                  # persistent across test runs
    path: /tmp/e2e_checkpoints.db
  
  prod:
    backend: postgresql
    dsn: "${POSTGRES_DSN}"
    schema: checkpoint_store
    connection_pool:
      min_size: 5
      max_size: 20
    # Optional: Redis write-through cache for hot conversations
    cache:
      backend: redis
      dsn: "${REDIS_DSN}"
      ttl_seconds: 1800              # 30 min cache for active conversations
```

---

## 5. Timeout Policy

### 5.1 Idle Timeout Tiers

| Tier | Idle Duration | Action | Resulting State |
|------|--------------|--------|-----------------|
| **Warn** | 15 min | Send "Are you still there?" prompt | active (unchanged) |
| **Soft timeout** | 30 min | Pause conversation, save checkpoint | paused |
| **Hard timeout** | 24 hours | Archive conversation | archived |

### 5.2 YAML Configuration

```yaml
lifecycle:
  timeout:
    warning:
      idle_seconds: 900              # 15 min
      action: send_warning_prompt    # send_warning_prompt | none
      message: "I haven't heard from you in a while. Do you still need help?"
    
    soft_timeout:
      idle_seconds: 1800             # 30 min
      action: pause                  # pause | abandon | none
      before_transition:
        - save_checkpoint
        - log_timeout_audit
    
    hard_timeout:
      idle_seconds: 86400            # 24 hours
      action: archive                # archive | abandon
      before_transition:
        - save_final_checkpoint
        - archive_messages
      archive_storage: s3            # s3 | gcs | local
    
    timer_implementation:
      strategy: scheduled_poll       # scheduled_poll | event_driven
      poll_interval_seconds: 60
      # Event-driven alternative (future):
      # strategy: event_driven
      # trigger: message_queue
```

### 5.3 Timer Reset Rules

```yaml
lifecycle:
  timer_reset:
    triggers:
      - user_message_sent          # reset on every user message
      - agent_message_delivered    # reset after agent responds
      - user_resume                # reset on explicit resume
    excludes:
      - system_message             # internal system messages don't reset timer
      - heartbeat                  # keepalive pings don't reset timer
```

---

## 6. Resume Flow

### 6.1 Resume Sequence

```
User: "resume_conversation(conversation_id)"
    │
    ▼
Step 1: Validate lifecycle state
    │
    ├── state is active → return "already active"
    ├── state is completed/abandoned → return error
    ├── state is archived → return "conversation expired"
    │
    └── state is paused/timeout → proceed
              │
              ▼
Step 2: Load checkpoint
    │
    ├── from PostgreSQL / Redis
    │
    └── verify checkpoint integrity (hash check)
              │
              ▼
Step 3: Hydrate context
    │
    ├── restore agentState from checkpoint
    ├── restore conversation history (last N messages)
    ├── restore execution position (current phase, phase_stack)
    │
    └── optionally re-run Context Hydration for stale external data
              │
              ▼
Step 4: Transition state
    │
    └── paused/timeout → active
              │
              ▼
Step 5: Notify user
    │
    └── "Welcome back! You were in the middle of [current_phase_description]."
              │
              ▼
Ready for next send_message
```

### 6.2 YAML Configuration

```yaml
lifecycle:
  resume:
    allowed_from:
      - paused
      - timeout
    
    validation:
      verify_user_id: true          # must match original user_id
      verify_not_archived: true
      max_resume_count: 10          # prevent abuse
    
    context_hydration:
      rehydrate: true               # re-run Context Hydration layer
      stale_threshold_seconds: 300  # rehydrate if checkpoint > 5 min old
      rehydrate_strategy: selective # selective | full
    
    post_resume:
      send_welcome_back: true
      summarize_state: true         # brief summary of where we left off
      auto_continue: false          # wait for user message before processing
```

---

## 7. Audit Trail

### 7.1 What Gets Logged

Every lifecycle transition records an audit entry:

```
LifecycleAuditEntry {
  timestamp:          datetime
  conversation_id:    string
  user_id:            string           // trace_id
  previous_state:     string
  new_state:          string
  trigger:            string           // first_message | user_pause | idle_timeout | ...
  metadata: {
    turn_number:      integer
    checkpoint_id?:   string
    error?:           string
  }
}
```

### 7.2 Audit Entry Examples

```json
// Conversation created
{
  "timestamp": "2026-06-17T10:00:00Z",
  "conversation_id": "conv_abc123",
  "user_id": "user_456",
  "previous_state": null,
  "new_state": "created",
  "trigger": "create_conversation",
  "metadata": {
    "turn_number": 0,
    "workflow_id": "home_insurance_quote"
  }
}

// Conversation paused due to idle
{
  "timestamp": "2026-06-17T10:30:00Z",
  "conversation_id": "conv_abc123",
  "user_id": "user_456",
  "previous_state": "active",
  "new_state": "paused",
  "trigger": "idle_timeout",
  "metadata": {
    "turn_number": 12,
    "checkpoint_id": "ckpt_789",
    "idle_duration_seconds": 1800
  }
}

// Conversation completed
{
  "timestamp": "2026-06-17T10:45:00Z",
  "conversation_id": "conv_def456",
  "user_id": "user_789",
  "previous_state": "active",
  "new_state": "completed",
  "trigger": "goal_met",
  "metadata": {
    "turn_number": 24,
    "checkpoint_id": "ckpt_final_012",
    "total_duration_seconds": 2700
  }
}
```

### 7.3 Audit Configuration

```yaml
lifecycle:
  audit:
    enabled: true
    log_transitions: true
    log_checkpoints: true
    
    storage:
      backend: postgresql
      table: lifecycle_audit_log
    
    retention:
      active: 365 days               # prod retention
      archived: 7 years              # compliance archive
    
    query_api:
      enabled: true
      filters:
        - by_user_id
        - by_conversation_id
        - by_date_range
        - by_lifecycle_state
```

---

## 8. Multi-Device Support

### 8.1 One User, Multiple Conversations

```
user_id: "user_456"
  ├── conversation_1 (home_insurance_quote)  → state: active
  ├── conversation_2 (home_insurance_claim)  → state: paused
  └── conversation_3 (claim_filing)          → state: completed
```

A single `user_id` can have multiple concurrent conversations across different workflows. Each conversation has its own `conversation_id`, lifecycle state, and checkpoints — but all share the same `trace_id = user_id`.

### 8.2 Device Awareness

```yaml
lifecycle:
  multi_device:
    enabled: true
    strategy: independent_conversations   # independent_conversations | single_conversation
    
    # independent_conversations:
    #   Each device gets its own conversation.
    #   User can have multiple active conversations.
    #   Best for: multi-tasking users, different workflows per device.
    
    # single_conversation (future):
    #   All devices share the same conversation.
    #   Requires distributed locking and message ordering.
    #   Best for: single-purpose assistants, kiosk mode.
    
    device_tracking:
      enabled: true
      fields:
        - device_id: string
        - platform: string              # ios | android | web | cli
        - user_agent: string
```

### 8.3 Conversation Isolation

```yaml
# When multi_device enabled, each conversation is fully isolated:
# - Separate LangGraph state
# - Separate checkpoints
# - Separate message history
# - Shared: user_id (trace_id), user context (from Auth spec)

lifecycle:
  conversation_per_device:
    naming_convention: "{workflow_id}_{device_id}_{timestamp}"
    max_active_per_user: 10             # prevent abuse
    cleanup:
      complete_older_than_days: 30
```

---

## 9. Integration Points

### 9.1 With Auth Spec

```yaml
# Lifecycle validates user_id against Auth spec's UserContext
lifecycle:
  user_identity:
    source: agentState.user.user_id    # from Auth spec §2.3 UserContext
    validation: verify_token           # re-verify on sensitive transitions (resume, abandon)
```

### 9.2 With LangGraph Checkpoints

```yaml
# Lifecycle checkpoints use LangGraph's built-in checkpointing
checkpoint:
  langgraph:
    # LangGraph auto-saves after each node execution
    # Lifecycle adds lifecycle-specific metadata to each checkpoint
    enrichment:
      add_lifecycle_state: true
      add_timeout_timestamp: true
      add_turn_number: true
```

### 9.3 With Observability

```yaml
# Lifecycle transitions emit metrics
observability:
  lifecycle_metrics:
    - conversations_created_total
    - conversations_active_gauge
    - conversations_paused_gauge
    - conversations_completed_total
    - conversations_abandoned_total
    - conversations_timed_out_total
    - avg_conversation_duration_seconds
    - avg_turns_per_conversation
```

---

## 10. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should the framework support conversation merging (user starts on web, continues on mobile as same conversation) or only parallel independent conversations? | Multi-device architecture complexity |
| 2 | Should archived conversations be restorable (legal hold, audit review) or permanently read-only? | Compliance requirements in regulated industries |
| 3 | How should the timeout policy handle connections where the user is typing but hasn't sent (e.g., long message composition)? | False-positive timeouts |
| 4 | Should the framework support conversation handoff between users (e.g., user calls support, agent takes over the same conversation)? | B2B and support escalation scenarios |
| 5 | What is the maximum conversation duration before forced archival — 30 days, 90 days, configurable per workflow? | Storage costs vs compliance needs |
| 6 | Should checkpoint snapshots include full LLM response raw data (for replay/debug) or only structured output to reduce storage? | Debugability vs storage cost |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — §2 Context Hydration + Three Layers, §4.1 Framework Principles
- [Auth & Token Verification](./2026-06-17-auth-token-verification.md) — §2.3 UserContext schema, user_id origin
- [Routing & Execution](./2026-06-17-routing-execution-layer-design.md) — §1.2 AgentState concurrency, checkpoint interaction
- [Domain Model Design](./2026-06-17-domain-model-design.md) — Workflow FSM states (distinct from lifecycle states)
- [Environment Config](./2026-06-17-environment-config.md) — Checkpoint backend per environment
- [Observability & Monitoring](./2026-06-17-observability-monitoring.md) — Lifecycle metrics in Grafana dashboards
- [State Machine Design](./2026-06-16-state-machine-design.md) — Business state transitions (distinct from lifecycle)
