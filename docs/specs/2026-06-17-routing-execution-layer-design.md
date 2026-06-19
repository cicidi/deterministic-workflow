# Routing & Execution Layer Specification

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Business logic execution, decision routing, phase-aware routing + return stack, sub-workflow reuse, retry budgets, permission model, tool system.
> **This spec defines interfaces and alternative implementation strategies — not a single solution.**

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial routing & execution spec: executor, decision nodes, phase-aware routing + return stack, sub-workflow, retry, permission, tool system |
| 2026-06-17 | 0.2.0 | Replace all Python code blocks with YAML schemas/structured descriptions; merge errorNode config (§8) into retry section (§6); add YAML schemas for AbstractState, code executors, decision rules, phase routing, errorNode, permission enforcement, tool interface, transition enforcement |
| 2026-06-17 | 0.3.0 | Add §1.2 AgentState Concurrency Model: copy-on-write + reducer merge, conflict scenarios, reducer strategies (last_write_wins/conflict_detect/append/merge), Java ConcurrentHashMap comparison; Section 2.3: remove ≤50 lines constraint from YAML comment; delete Section 8 stub (now consolidated in Section 6); fix missing closing ``` on ASCII flow diagram in Section 6.7 |
| 2026-06-17 | 0.4.0 | Add §5 A2A protocol cross-reference (sub-workflows as A2A definition language); add A2A Protocol spec to References |
| 2026-06-18 | 0.5.0 | Extend `Tool.type` enum from `api \| mcp \| command \| llm` to `api \| mcp \| command \| llm \| a2a \| sdk`; add `a2a` tool type for agent-to-agent as a tool; add `sdk` tool type for OpenCode/Claude SDK as a tool |

---

## 1. Role

The Routing & Execution layer (Layer 2) answers: *"What should we do with the extracted data?"*

It consumes validated entities from Layer 1 (Extraction) and produces structured outcomes for Layer 3 (Response). It is the **core business logic layer** — where rules are enforced, decisions are made, and side effects (API calls, database writes) occur.

```
Layer 1 → validated entities
              ↓
+-----------------------------+
| Layer 2: DECIDE             |
|                             |
|  [Code Executor]            |  → business computation
|  [Decision Node]            |  → rule engine routing
|  [Sub-workflow Invoker]     |  → shared capability reuse
|  [Phase-Aware Routing]   |  → state locking via return stack
|  [Retry Manager]            |  → retry + escalation
|  [Permission Enforcer]      |  → tool + transition access
+-----------------------------+
              ↓
Layer 3 ← structured outcomes
```

### 1.1 What Layer 2 Does NOT Cover

- **Entity extraction** → Layer 1 (Extraction spec)
- **Intent classification** → Layer 1 (Intent Classification spec)
- **Field validation** → Layer 1 (Validate node in Extraction spec)
- **Response generation** → Layer 3 (Response Generation spec)
- **State machine mechanics** → State Machine Design spec (transitions, guards, metadata)
- **Domain model definition** → Domain Model spec (entities, states, transitions)

### 1.2 AgentState Concurrency Model

Multiple nodes read and write to `agentState` — but this does NOT cause race conditions. The design follows **copy-on-write + reducer merge**, inherited from LangGraph's `StateGraph` semantics. No ReadWriteLock needed.

**How it works:**

```
Node A execution:
  state_copy = agentState.deep_copy()     # take a snapshot
  state_copy.collectedFields["address"] = "Beijing"  # write to copy
  return {"collectedFields": state_copy.collectedFields}  # submit update

Node B execution:
  state_copy = agentState.deep_copy()     # independent copy
  state_copy.goal_check = result          # write to copy
  return {"goal_check": result}           # submit update

Framework merge (single-threaded reducer):
  agentState = merge(updates)  # { collectedFields: {address: "Beijing"}, goal_check: {...} }
```

**Key properties:**

| Property | How |
|----------|-----|
| **No shared mutable state** | Each node operates on its own copy |
| **No lock contention** | Merge is single-threaded, not concurrent |
| **Parallel nodes (Send API)** | Each parallel branch gets its own copy; reducers merge results |
| **Field isolation** | Parallel nodes write to different fields (response → `response`, goalChecker → `goal_check`) |

**Conflict scenario — parallel sub-workflow + parent:**

The only scenario where a write conflict is possible is an async sub-workflow and parent both writing to the same field. The framework uses a single strategy: **append** — all parallel writes are accumulated, never overwritten.

```yaml
state_reducers:
  collectedFields:
    strategy: append    # deep merge: new keys added, existing keys preserved
  response:
    strategy: append    # appended to response list for audit
  messages:
    strategy: append    # appended to message history
```

**Why only append:** For a regulated-industry framework, no data should be silently lost. If two parallel nodes both produce output, both outputs are preserved. The downstream node (or human reviewer) decides which to use — the framework never discards data.

Reducer behavior per type:

| Field Type | Append Behavior |
|------------|----------------|
| List (messages, audit_log) | Append items to end of list |
| Dict (collectedFields, entities) | Deep merge: new keys added, existing keys kept; same key from both sources → value wrapped in `[value_a, value_b]` for conflict visibility |
| Scalar (response, intent) | Value wrapped in list: `[old, new]` |

The framework guarantees that:
1. Serial nodes — zero contention (each node sees previous node's output before running)
2. Parallel LLM calls (goalChecker + generateResponse) — write different fields, each appended
3. Async sub-workflow + parent — both results appended, never lost

### 1.3 Append-Only Guarantee

All `agentState` fields use append-only semantics. This is not configurable — it is a framework-level enforcement. No parallel write is ever silently discarded.

**Design-time enforcement (workflow design / skill interview):**

```
Q: "Does this workflow have nodes that run in parallel?"
   ├── No → Skip. Serial nodes don't need reducers.
   └── Yes → All fields are append-only. No configuration needed.
              Downstream nodes consume accumulated lists/dicts.
```

**YAML declaration (for documentation only — behavior is enforced, not configured):**
    goal_checker:
      writes: [goal_check_result]
      # goal_check_result only written by this node → last_write_wins is safe

  state_reducers:            # MANDATORY when parallel_nodes is non-empty
    collectedFields:
      strategy: conflict_detect
      on_conflict: raise      # raise StateConflictError | log_and_override | queue
    response:
      strategy: last_write_wins
    messages:
      strategy: append
    goal_check_result:
      strategy: last_write_wins
```

**Interface:**

```
Reducer {
  field:      string                                    // which field this reducer governs
  strategy:   "last_write_wins" | "conflict_detect" | "append" | "merge" | "custom"
  on_conflict: "raise" | "log_and_override" | "queue"   // what to do on conflict
  custom_fn?: string                                    // registered custom reducer function name
}
```

**Framework enforcement flow:**

```
1. Workflow YAML loaded
2. Framework scans for parallel_nodes
3. If parallel_nodes is non-empty:
   a. For each field written by a parallel node → check state_reducers has an entry
   b. Missing reducer → YAML validation error, workflow REFUSED to load
   c. All reducers present → compile into LangGraph channel reducers
```

**Why this matters:**

Without reducers, two parallel nodes writing to the same field produce non-deterministic results — whichever finishes last wins silently. The framework catches this at load time, not at runtime, preventing silent data corruption in production.

---

## 2. Code Executor Node

### 2.1 Contract

Code executors are **pure business logic** functions. They receive validated data, compute results, and return them. They are small, composable, and deterministic.

```
Input:
  entities:   Map<string, any>   // validated entities from Layer 1
  state_context: StateContext     // current state information
  previous_results: Map<string, any> // results from prior nodes in this workflow

Output:
  results:    Map<string, any>   // computed business results
  decisions:  DecisionResult[]   // routing hints for downstream nodes
  side_effects: SideEffect[]     // API call results, DB writes (recorded for audit)
```

### 2.2 Design Conventions

- Every executor method ≤ **50 lines**
- Every executor file ≤ **1000 lines**
- Complex computations split into sub-functions or sub-workflows
- Executors are pure functions: same input → same output (no hidden state)
- Side effects (API calls, DB writes) are declared explicitly in `side_effects`

### 2.3 Abstract Parent Data Model

Every state shares a common abstract parent that provides metadata. The framework manages the metadata fields below; the developer implements a single `execute(input: StateInput) → StateOutput` function (≤ 50 lines) containing the business logic for this state.

```yaml
# Abstract parent data model — every state shares this structure
abstract_state:
  # --- Framework-managed (set in workflow YAML, populated at runtime) ---
  state_name: string              # unique node identifier
  state_entity: string            # bound domain model entity name
  state_hint: string              # disambiguation hint for downstream nodes
  permission: NodePermission      # tool + transition allowlist (see §7)
  retry_budget: RetryBudget       # retry configuration (see §6.2)

  # --- Developer-implemented ---
  # execute: (input: StateInput) -> StateOutput
  #   Business logic for this state. Delegate complex logic to sub-functions.
```

### 2.4 Implementation Options

#### Option A: Pure Functions (Recommended)

Code executors are registered as module+function references in the workflow YAML. The framework resolves the reference at load time and calls the function with validated input. The function is a pure, stateless computation — no side effects, no framework dependency.

```yaml
# Code executor configured as a pure function reference
executor: code
execute: premium.calculate                  # module.function reference
input_mapping:
  property_info: "{{entities.property_info}}"
  coverage_needs: "{{entities.coverage_needs}}"
output:
  risk_score: number
  annual_premium: number
  monthly_premium: number
  rate_multiplier: number
```

| Strengths | Testable in isolation; zero framework dependency; IDE-friendly |
|-----------|---------------------|
| Weaknesses | No built-in lifecycle hooks; manual audit trail |
| Best for | Stateless computation; risk scoring; premium calculation |

#### Option B: StateHandler Class

When richer lifecycle hooks are needed (pre/post execute, audit, error handling), the executor is configured with class-level metadata alongside the handler class reference:

```yaml
# StateHandler configured with lifecycle metadata
executor: code
execute: premium.CalculatePremiumHandler    # class reference
state_name: calculate_premium
state_entity: premium_result
lifecycle:
  pre_execute: premium.validate_inputs       # optional hook
  post_execute: premium.audit_calculation    # optional hook
  on_error: premium.log_calculation_error    # optional hook
audit: true                                  # framework auto-records audit trail
```

| Strengths | Lifecycle hooks (pre/post execute); framework-managed audit; reusable base |
|-----------|---------------------|
| Weaknesses | More boilerplate; harder to unit test in isolation |
| Best for | Complex multi-step computation; nodes that need rich lifecycle |

### 2.5 Comparison Matrix

| Dimension | Option A (Pure Function) | Option B (Class Handler) |
|-----------|------------------------|------------------------|
| Testability | Excellent (no framework) | Good (with fixtures) |
| Lines of code | ~10-30 per executor | ~20-50 per executor |
| Audit trail | Manual | Auto by framework |
| Lifecycle hooks | None | pre/post_execute, on_error |
| Suitability | Simple computation | Complex orchestration |

---

## 3. Decision Nodes

### 3.1 Role

Decision nodes answer: *"Which path should the workflow take next?"* — beyond simple field-completion guards (which are handled by the state machine's transition guards).

> **All LLM output is JSON.** Decision nodes that use LLM produce structured JSON output with framework-enforced guardrails (schema validation, field presence, type coercion). See HLD Section 4.3.

Examples:
- Risk triage: `risk_score > 80 → manual_review` / `risk_score ≤ 80 → auto_approve`
- Fraud detection: anomaly patterns trigger `manual_review` branch
- Coverage routing: `coverage_type == "basic"` routes to `calculate_basic_premium`

### 3.2 Implementation Options

#### Option A: 100% Rule Engine — Deterministic (Mandatory baseline)

All decisions must go through the rule engine first. No LLM involvement. Rules are defined declaratively in YAML:

```yaml
# Decision ruleset — evaluated top-to-bottom, first match wins
decision_rules:
  risk_triage:
    input: entities.premium_calculation.risk_score
    rules:
      - condition: "risk_score >= 0 AND risk_score <= 30"
        decision:
          route: auto_approve
          reason: "Low risk: {{risk_score}}"
      - condition: "risk_score > 30 AND risk_score <= 80"
        decision:
          route: standard_review
          reason: "Medium risk: {{risk_score}}"
      - condition: "risk_score > 80"
        decision:
          route: manual_review
          reason: "High risk: {{risk_score}}"
    on_unmatched: escalate               # default action when no rule matches
```

| Aspect | Detail |
|--------|--------|
| Strengths | Deterministic; auditable; explainable; fast |
| Weaknesses | Rule maintenance; cannot handle novel patterns |
| Dependencies | Rule engine (durable_rules / business-rules / native) |
| On unhandled case | Default route or error escalation |

#### Option B: Rule Engine + LLM Fallback (Future)

When the rule engine cannot resolve a case (e.g., novel fraud pattern), the framework **optionally** delegates to an LLM for a decision. The LLM receives:
- The full workflow context (current state, entity data, conversation history)
- Decision criteria from the rule engine (what could not be resolved)
- Expected output schema (JSON)

**This is deferred for future discussion.** The mechanism for how the LLM understands the workflow and makes correct decisions (e.g., via a skill or prompt construction) requires separate design.

#### Option C: Rule Engine Only — No Fallback, Direct Error (Strict mode)

Security-critical deployments disable LLM fallback entirely. If the rule engine cannot resolve → escalate to `on_unresolved_decision` node (typically human review or termination).

### 3.3 Decision Output Contract

Every decision node produces a structured result:

```yaml
# DecisionResult schema
DecisionResult:
  route: string                                  # target node name
  reason: string                                 # why this route was chosen (audit trail)
  confidence: number                             # optional, 1.0 for rule engine; variable for LLM fallback
  source: rule_engine | llm_fallback | default   # origin of the decision
```

### 3.4 Decision Evals

LLM-based decisions (Option B) require an eval framework:

```
EvalCase {
  input:    dict         # entity state fed to decision node
  expected: DecisionResult   # expected routing decision
  tolerance: float       # acceptable confidence threshold (default: 0.7)
}
```

Framework runs evals on each LLM decision model change. Must pass ≥ 95% of eval cases before deployment. Eval cases cover:
- Edge cases (boundary risk scores)
- Ambiguous inputs (missing optional fields)
- Safety-critical cases (must never route `high_risk → auto_approve`)

### 3.5 Comparison Matrix

| Dimension | Option A (Rule Engine) | Option C (Strict) |
|-----------|----------------------|-------------------|
| Determinism | 100% | 100% |
| Coverage | Closed-world rules | Closed-world rules |
| Unhandled case | Default route | Error → escalate |
| Auditability | Full | Full |
| Use case | Most production | High-security (claims, PII data) |

---

## 4. Phase-Aware Routing + Return Stack

### 4.1 Concept

Every node, when it completes, determines the **next node** based on:

```
next_node = resolve(agentState.phase, intent)
```

Key behaviors:

1. **Normal flow**: `phase=collect_property_info` + `intent=provide_information` → route to `validate_property_info`
2. **Mid-flow question**: `phase=collect_property_info` + `intent=ask_question` → route to `rag_faq` sub-workflow
3. **Return after question**: when `rag_faq` completes → return to **the previous phase** (`collect_property_info`)

The framework maintains a **phase return stack** to support this. When a mid-flow question detours, the current phase is pushed onto the stack. When the question is answered, the stack is popped, and the workflow resumes at the previous phase.

### 4.2 Phase Return Stack

```
agentState = {
    phase:          "collect_property_info",   // current phase
    phase_stack:    [],                         // push/pop for mid-flow detours
    collectedFields: { ... },                   // accumulated entity data
    ...
}
// See [Domain Model §10.1](./2026-06-17-domain-model-design.md) for the canonical AgentState schema.
```

**Flow example:**

```
1. User: "I want a quote for my apartment"
   phase = "collect_property_info"
   
2. Agent: "What's your address?"
   (waiting for user input)
   
3. User: "What does basic plan cover?"
   intent = ask_question
   → phase_stack.push("collect_property_info")    // save current phase
   → route to rag_faq sub-workflow               // answer question
   
4. Agent: "Basic plan covers fire, theft, and water damage..."
   rag_faq complete
   → phase = phase_stack.pop()                    // restore: "collect_property_info"
   → agent continues: "So, what's your address?"
```

### 4.3 Node Next-Step Resolution

The framework resolves the next node by looking up `(current_phase, detected_intent)` in a phase routing table:

```yaml
# Phase routing table — next node resolved from (phase, intent)
phase_routing:
  collect_property_info:
    provide_information: validate_property_info     # normal flow
    ask_question: rag_faq                            # detour (push phase → answer → pop → resume)
    cancel: terminate                                # exit (pop stack if non-empty, else terminate)
  validate_property_info:
    provide_information: assess_risk
    ask_question: rag_faq
    cancel: terminate
  # ... additional phases added per domain
```

### 4.4 Phase Continuity

The zelkim "once transactional, always transactional" pattern is reframed as: **phase determines routing, not a binary mode flag.** When `phase` is a transactional phase (e.g., `collect_property_info`), the routing always stays within the transactional branch — questions detour but return, and the phase stack ensures continuity.

```yaml
# Phase definition includes routing map
phases:
  collect_property_info:
    entity: property_info
    transitions:
      provide_information: validate_property_info
      ask_question: rag_faq                    # detour → return after
      cancel: terminate
```

---

## 5. Sub-Workflow

### 5.1 Concept

**Sub-workflows are the definition language for A2A (Agent-to-Agent) communication.** They define *what* agents communicate and *how* they coordinate — the inputs, outputs, permissions, and execution contracts between agents. See [A2A Protocol spec](./2026-06-17-a2a-protocol.md) for the runtime protocol that sub-workflows execute over (agent discovery, capability negotiation, task lifecycle, message formats).

Sub-workflows are **complete, standalone workflows** with the same structure as the super workflow — their own domain model (entities, states, transitions), permission model, retry budgets, and routing. Shared capabilities (RAG FAQ, property verification, claim processing) are defined once and invoked from any state in any parent workflow.

This prevents the zelkim anti-pattern where RAG logic is duplicated across conversational and transactional branches.

**Deadlock protection:** Sub-workflows must not create circular invocation chains (A → B → A). The framework enforces this at two levels:
- **Depth limit:** `max_sub_workflow_depth: 3` — after 3 nested sub-workflow levels, the conversation terminates with `errorNode`
- **Cycle detection:** The framework tracks the sub-workflow call stack. If a sub-workflow is invoked while already present in the stack, the call is rejected with `StateConflictError` and routes to `errorNode`

### 5.2 Full Workflow Structure

A sub-workflow has the **exact same structure** as a super workflow. No reduced subset:

```yaml
# sub-workflows/rag_faq.yaml — complete workflow
domain: rag_faq
version: 1.0.0
description: "Answer user questions using RAG knowledge base"

entities:
  question_input:
    fields:
      question:
        type: string
        required: true
      conversation_context:
        type: string
        required: false
  answer_output:
    fields:
      answer:
        type: string
        required: true
      sources:
        type: list
        required: false

states:
  search_knowledge_base:
    entity: question_input
    executor: code
    execute: search_vector_db
    permission:
      allowed_tools: [vector_search_mcp]
      allowed_transitions: [generate_answer]
    retry_budget:
      max_attempts: 2
      timeout_ms: 10000

  generate_answer:
    entity: answer_output
    executor: llm
    output_schema: { answer: string, sources: string[] }
    retry_budget:
      max_attempts: 4    # 3 base + 1 LLM extra

  return_to_caller:
    executor: code

transitions:
  - from: search_knowledge_base
    to: generate_answer
    guard: "question != null"
  - from: generate_answer
    to: return_to_caller
    guard: "answer != null"
```

### 5.3 Node Orchestration Within Sub-Workflow

Nodes within a sub-workflow support three orchestration patterns. **LangGraph natively supports all three** via its `Send` API, conditional edges, and sub-graph composition.

#### Pattern A: Serial (Sequential)

```
[A] → [B] → [C] → [D]
```

Standard edge routing. Each node completes before the next starts.

```yaml
transitions:
  - from: search_kb
    to: filter_results
  - from: filter_results
    to: generate_answer
  - from: generate_answer
    to: return_to_caller
```

#### Pattern B: Parallel (Fan-Out / Fan-In)

```
         ┌→ [B1] ─┐
[A] ──→  ├→ [B2] ─┼──→ [C]
         └→ [B3] ─┘
```

LangGraph `Send` API fans out to multiple nodes simultaneously. All must complete before converging at C.

```yaml
# Fan-out from A to multiple B nodes
parallel_nodes:
  from: search_kb
  fan_out:
    - search_policy_db       # search policy knowledge base
    - search_claims_db       # search claims knowledge base
    - search_faq_db          # search FAQ database
  fan_in: merge_results      # converge here when all 3 complete
```

#### Pattern C: Mixed (DAG)

```
         ┌→ [B] ─→ [C] ─┐
[A] ──→  │               ├──→ [E]
         └→ [D] ─────────┘
```

Serial and parallel combined. LangGraph supports arbitrary DAG topologies via conditional edges + `Send`.

```yaml
# DAG: serial chain B→C runs in parallel with D
parallel_nodes:
  from: classify_query
  fan_out:
    - chain:                    # serial sub-chain
        - extract_entities
        - validate_entities
    - search_knowledge_base     # single parallel node
  fan_in: synthesize_response
```

### 5.4 Sync vs Async Invocation

| Mode | Behavior | Use Case |
|------|----------|---------|
| **Sync** | Parent waits for sub-workflow to complete, then resumes | RAG FAQ (must get answer before continuing) |
| **Async** | Parent fires sub-workflow and continues immediately; result delivered via callback or polling | Audit logging, notification, background verification |

```yaml
# Sync invocation (default)
handle_question_in_quote:
  executor: sub_workflow
  sub_workflow: rag_faq
  mode: sync
  on_return: collect_property_info

# Async invocation
background_risk_check:
  executor: sub_workflow
  sub_workflow: property_verification
  mode: async
  on_complete: risk_result_received     # callback when async sub-workflow finishes
```

### 5.5 Sub-Workflow Nesting

Sub-workflows can recursively define child sub-workflows. A `rag_faq` sub-workflow can itself invoke a `translate_query` sub-workflow, which can invoke further sub-workflows. Each level has its own isolated state, phase stack, and retry budgets.

```yaml
# rag_faq calls translate_query as a sub-sub-workflow
states:
  translate_query:
    executor: sub_workflow
    sub_workflow: translate_query
    mode: sync
    on_return: search_knowledge_base
```

### 5.6 Invocation from Parent

```yaml
# In parent workflow
states:
  handle_question_in_quote:
    executor: sub_workflow
    sub_workflow: rag_faq                              # registered sub-workflow
    mode: sync                                          # sync | async
    input_mapping:
      question: "{{state.last_user_message}}"
      conversation_context: "{{state.conversation_history}}"
    on_return: collect_property_info                    # resume parent phase after return
```

### 5.7 LangGraph Support Summary

| Feature | LangGraph API | Supported |
|---------|--------------|-----------|
| Serial node chain | `add_edge("A", "B")` | ✅ |
| Parallel fan-out/fan-in | `Send()` API | ✅ (v0.2+) |
| Conditional routing | `add_conditional_edges()` | ✅ |
| Sub-graph composition | `StateGraph` nesting | ✅ |
| Checkpoint/resume (sync) | `checkpointer` | ✅ |
| Async execution | `ainvoke()` / `astream()` | ✅ (v0.2+) |
| Mixed DAG | Send + conditional edges combined | ✅ |

---

## 6. Retry & Error Handling

### 6.1 Core Principle: All Errors → errorNode

No per-category dispatch. No multi-link escalation chain. **All errors, all timeouts, all retry-exhausted failures — route to a single `errorNode` for unified handling.** The `errorNode` is the one place where error recovery logic lives.

### 6.2 Retry Budget

Every node has a retry configuration:

```yaml
retry_budget:
  max_attempts: 3
  backoff: exponential            # linear | exponential | fixed
  base_delay_ms: 500
  max_delay_ms: 10000
  timeout_ms: 30000               # per-attempt timeout
  on_exhausted: errorNode          # ALWAYS errorNode
```

**LLM nodes get +1 extra retry.** If `max_attempts` is 3, LLM nodes retry 4 times. This compensates for LLM non-determinism (transient hallucinations, malformed JSON).

The effective retry count is `max_attempts + 1` for LLM nodes (to compensate for non-determinism), and `max_attempts` for all other node types.

### 6.3 Timeout Handling

All timeouts (LLM timeout, API timeout, tool timeout) are treated as transient failures within the retry budget. After exhausting retries → `errorNode`.

### 6.4 Error Categories (for logging, not routing)

Errors are categorized for **audit logging**, not for separate routing paths. The `errorNode` receives the category and decides what to do:

| Category | Examples |
|----------|---------|
| `llm_error` | LLM timeout, malformed JSON, hallucination guardrail triggered |
| `api_error` | External API timeout, 5xx response, connection refused |
| `tool_error` | MCP server unavailable, command non-zero exit |
| `validation_error` | Data invariant violation, type mismatch |
| `business_rule_error` | Coverage exceeds limit, duplicate claim |
| `permission_error` | Unauthorized tool call, forbidden transition |
| `unrecoverable_error` | Corrupted state, missing required entity |

### 6.5 errorNode Interface (Canonical Definition)

The `errorNode` is a unified error handling node that receives all errors from all nodes — this is the single source of truth. All other specs that reference errorNode strategies MUST cross-reference this section.

Its contract:

```yaml
# errorNode contract
errorNode_input:
  source: string                  # which node failed
  category: error_category        # one of 7 categories (see §6.4)
  attempts: integer               # retries attempted before exhaustion
  message: string                 # human-readable error detail

errorNode_output:
  action: ask_clarify | escalate_to_human | terminate | fallback_value | retry_with_context
  correction: object              # correction instruction applied to the failed node
  message: string                 # user-facing or log message
```

**Built-in errorNode implementations (user-selectable):**

| Strategy | Behavior |
|----------|---------|
| `ask_clarify` | Re-prompt user with a clarification question, resume the failed node |
| `escalate_to_human` | Queue for human review, suspend conversation |
| `terminate` | Graceful exit with apology message + audit log |
| `fallback_value` | Use a configured default value, log warning, continue |
| `retry_with_context` | Re-invoke the failed node with enriched context (addressing specific error) |

### 6.6 Relationship with Extraction Layer

The Extraction Layer's `max_transform_attempts` is separate from Layer 2's node-level `retry_budget`. Extraction retries handle field-level corrections; Layer 2 retries handle node-level execution failures. Both route to `errorNode` on exhaustion.

### 6.7 Flow Diagram

```
Node execution
    │
    ├── success ──→ next node
    │
    └── failure
          │
          ├── retry (within budget) ──→ back to Node execution
          │     LLM nodes: +1 extra retry
          │
          └── retry exhausted ──→ errorNode
                                      │
                                      ├── ask_clarify (re-prompt user)
                                      ├── escalate_to_human
                                      ├── terminate
                                      ├── fallback_value
                                       └── retry_with_context
```
### 6.8 errorNode Configuration

```yaml
# Global default
error_handling:
  default_error_node: ask_clarify
  max_total_errors: 5               # conversation-level: after 5 total errors → terminate
  max_conversation_duration_ms: 300000  # 5 min hard limit: after timeout → terminate
  errorNode_config:
    ask_clarify:
      max_clarifications: 3     # max re-prompts before escalating
    escalate_to_human:
      queue: "agent_review"
      timeout_minutes: 15
    terminate:
      message_template: "I'm sorry, I ran into an error. Our team has been notified."
    fallback_value:
      default_values: {}        # per-field defaults

# Per-node override
nodes:
  process_claim_payment:
    error_node: escalate_to_human  # claim payment errors always go to human
  calculate_premium:
    error_node: fallback_value     # use default rate on calculation failure
```

Conversation-level budgets apply globally across all nodes in a conversation. When `max_total_errors` is exhausted OR `max_conversation_duration_ms` is exceeded, the conversation terminates regardless of per-node retry budget remaining. This bounds worst-case latency and prevents adversarial loops.

### 6.9 errorNode → Conversation Continuity

After `errorNode` handles the error, the conversation resumes from the state that triggered the error. The `errorNode` does NOT change the workflow state — it returns a **correction instruction** that the framework applies to the failed node.

---

## 7. Permission Model

### 7.1 Two-Level Enforcement

| Level | When | How |
|-------|------|-----|
| **Config-level** | Workflow load time (static) | YAML allowlists: `allowed_tools`, `allowed_transitions` |
| **OAuth / Role-based** | Runtime (dynamic) | User context: what is the authenticated user authorized to do? |

### 7.2 NodePermission Schema

```yaml
# Defined per node in workflow YAML
permission:
  allowed_tools:
    - calculate_premium_api        # read: can call premium calculation
    - claims_gateway_api            # dangerous_operation_write: can process claims
    - vector_search_mcp            # read: can query knowledge base
  allowed_transitions:
    - assess_risk
    - manual_review
    - generate_quote               # can route to these states
  # deny_all_transitions_except: true   # strict mode
```

### 7.3 Tool Classification

> **Note:** The canonical `ToolMeta.type` enum (`api | mcp | command | llm | a2a | sdk`) is defined in [HLD §4.4](./2026-06-16-deterministic-workflow-framework-design.md). This section extends it with routing-specific detail.

Every tool (API, MCP server, command, LLM call) has metadata:

```yaml
tools:
  calculate_premium_api:
    type: api
    access_level: read
    description: "Calculate insurance premium based on property + coverage data"
    endpoint: POST /api/v1/premium/calculate
    timeout_ms: 5000

  claims_gateway_api:
    type: api
    access_level: dangerous_operation_write
    description: "Process claim through the claims gateway"
    endpoint: POST /api/v1/claims/submit
    timeout_ms: 15000
    requires_approval: true       # human-in-the-loop gate

  vector_search_mcp:
    type: mcp
    access_level: read
    description: "Semantic search over insurance knowledge base"
    server: knowledge_base_mcp
    tool_name: search_documents

  run_risk_model_cmd:
    type: command
    access_level: read
    description: "Execute risk assessment model"
    command: "python /opt/models/risk_assessment.py"
    timeout_ms: 30000
```

### 7.4 Tool Interface

Every tool conforms to a standard contract (defined in [HLD §4.4](./2026-06-16-deterministic-workflow-framework-design.md)). The framework checks permissions before invoking the tool's execution function.

```yaml
# Tool contract (interface) — type enum: see HLD §4.4
Tool:
  name: string                                        # unique tool identifier
  type: ToolMeta.type                                 # canonical enum in HLD §4.4
  access_level: read | write | sensitive_data_read | dangerous_operation_write
  metadata: ToolMeta                                  # endpoint, timeout, approval (see §7.3)
  # execute: (params: object, context: ExecutionContext) → ToolResult
  #   Framework calls this after permission check passes.

# ToolResult schema
ToolResult:
  success: boolean
  data: object
  error: string                                       # null if success
  duration_ms: integer
  audit_entry: AuditEntry                             # auto-generated by framework
```

### 7.5 Access Level Matrix

| Access Level | Examples | Extra Controls |
|-------------|----------|---------------|
| `read` | Vector search, premium calculation, policy lookup | None |
| `write` | Save quote, update profile, log event | Audit trail |
| `sensitive_data_read` | View PII, medical records, credit score | OAuth scope + audit |
| `dangerous_operation_write` | Process claim, cancel policy, delete data | Human approval gate + OAuth + audit |

### 7.6 OAuth / Role-Based Enforcement

At runtime, the framework enforces a two-level permission check for every tool invocation:

1. **Config-level:** The tool must be in the node's `allowed_tools` list (see §7.2).
2. **Role-level:** The authenticated user's OAuth scopes must satisfy the tool's `access_level`.

```yaml
# Permission enforcement rules (evaluated per tool invocation)
permission_enforcement:
  # Level 1: Static config — tool must be in node's allowlist
  config_check:
    rule: "tool.name in node.permission.allowed_tools"
    on_violation: deny

  # Level 2: OAuth scope check (runtime, per authenticated user)
  scope_requirements:
    read: []                                          # no scope needed
    write: []                                         # audit trail only, no scope needed
    sensitive_data_read: ["sensitive_data:read"]
    dangerous_operation_write: ["dangerous_operation:write"]

  # Human-in-the-loop gate for dangerous operations
  approval_gate:
    condition: "tool.metadata.requires_approval == true"
    action: await_human_approval                      # blocks until approved
```

### 7.7 Transition Permission

Nodes also restrict which other nodes they can transition to. The framework enforces this on every state transition:

```yaml
# Transition permission enforcement (evaluated per transition)
transition_enforcement:
  rule: "to_node in from_node.permission.allowed_transitions"
  on_violation:
    error: TRANSITION_DENIED
    message: "Node '{{from_node}}' cannot transition to '{{to_node}}'. Allowed: {{allowed_transitions}}"
```

---

## 8. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | How does the LLM (in Option B decision nodes) understand the full workflow context to make correct decisions? Prompt construction? Skill-based injection? | LLM decision reliability |
| 2 | Should sub-workflows support recursion (sub-workflow calling another sub-workflow)? | Workflow complexity |
| 3 | Should retry budgets be cumulative or per-node? (i.e., global conversation-level retry budget + per-node allocation) | Resource management |
| 4 | For OAuth enforcement, should the framework integrate with specific providers (Auth0, Okta) or expose a generic interface? | Integration surface |
| 5 | How are sensitive data tool results handled — auto-redaction? Separate audit channel? | PII compliance |
| 6 | Should the framework support suspending/resuming sub-workflows (checkpoint at sub-workflow boundary)? | Long-running workflows |
| 7 | LLM decision evals — automated CI pipeline or manual review per change? | Quality assurance process |
| 8 | `errorNode` — should it be a single global node or per-workflow configurable? | Error handling flexibility |
| 9 | async sub-workflow + parent concurrent write to same `collectedFields` key — `conflict_detect` by default or `last_write_wins`? | State safety vs developer ergonomics |
| 10 | Should the framework surface a `StateConflictError` to the developer (for debugging) or silently resolve via merge strategy? | Debugability |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent architecture, framework principles, permission model overview
- [State Machine Design](./2026-06-16-state-machine-design.md) — transition mechanics, state metadata, guard expressions
- [Domain Model Design](./2026-06-17-domain-model-design.md) — entity/state/transition schema
- [Extraction Layer Design](./2026-06-17-extraction-layer-design.md) — Extract/Validate/Transform interfaces
- [A2A Protocol](./2026-06-17-a2a-protocol.md) — Agent-to-Agent runtime protocol (discovery, negotiation, task lifecycle, message formats)
- zelkim/langgraph-insurance-chatbot — phase-aware routing pattern, sub-workflow anti-pattern
- Prodigal Payment Collection Agent — per-phase retry budgets, tool execution pattern
