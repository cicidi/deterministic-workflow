# Agent 2 — Cross-Model Reviewer: Execution Specs

> **Role:** Critique for correctness, completeness, clarity, consistency, trade-off gaps, and missing edge cases.
> **Specs reviewed:** Routing & Execution, Response Generation, Tool Ecosystem, A2A Protocol, MCP API Protocol
> **Date:** 2026-06-18

---

## 1. correctness — Reducer Rule Contradiction: "Mandatory for Parallel Nodes" vs Last-Write-Wins Default

**Affected:** `routing-execution-layer-design.md` §1.2, §1.3

§1.3 states: *"When a workflow defines parallel nodes, a reducer MUST be declared for every agentState field that any parallel node writes to. This is not optional."*

But §1.2 lists four strategies including `last_write_wins` with the annotation: *"Default. Second update overwrites first. Safe for non-overlapping fields."*

**Contradiction:** If parallel nodes write to **non-overlapping fields** (e.g., `generateResponse` writes to `response`, `goalChecker` writes to `goal_check_result`), then `last_write_wins` is declared safe — but it's also a no-op (there's nothing to overwrite). The framework's enforcement (§1.3) still requires a reducer declaration even when the reducer does nothing.

**The spec also says:** *"The framework guarantees that parallel LLM calls (goalChecker + generateResponse) — write different fields, no conflict."* This is the typical parallel pattern, meaning **in practice, most parallel nodes will use non-overlapping fields and `last_write_wins` will be a no-op reducer.**

The mandatory reducer requirement is **at the wrong abstraction level**. The rule should be: "If two parallel nodes write to the same field, a reducer must be declared." Writing to different fields requires no reducer — the existing copy-on-write semantics handle this correctly.

**Fix:** Change "MUST be declared for every field any parallel node writes to" → "MUST be declared for every field written by TWO OR MORE parallel nodes."

---

## 2. correctness — `errorNode` Category Enum Mismatch

**Affected:** `routing-execution-layer-design.md` §6.4 vs `a2a-protocol.md` §2.2

§6.4 defines 7 error categories:
```
llm_error | api_error | tool_error | validation_error | business_rule_error | permission_error | unrecoverable_error
```

The A2A response error schema (§2.2) defines:
```
llm_error | api_error | validation_error | permission_error | business_rule_error
```

Missing from A2A: `tool_error` and `unrecoverable_error`.

While it's defensible that A2A agents may not expose `unrecoverable_error` externally, `tool_error` is a legitimate A2A outcome (the target agent's tool invocation failed). This inconsistency means an A2A agent that encounters a `tool_error` must either map it to a different category (losing precision) or violate the response schema.

**Fix:** Add `tool_error` to the A2A error category enum. Document whether `unrecoverable_error` is intentionally excluded from A2A responses.

---

## 3. completeness — Missing Conversation-Level Retry Budget

**Affected:** `routing-execution-layer-design.md` §6; Open Question 3

The spec defines per-node retry budgets (§6.2) and a global `max_total_errors: 5` (§6.8) but **no conversation-level retry budget**. Open Question 3 asks: "Should retry budgets be cumulative or per-node?"

This is a significant gap. Without a conversation-level budget:
- A workflow with 10 nodes, each with `max_attempts: 3`, can attempt 30+ retries before failing — potentially minutes of latency.
- LLM nodes get `+1` extra retry, compounding the issue.
- An adversarial or confused user could keep triggering retries through repeated bad input.

Industry practice (AWS Step Functions, Temporal) uses **both** per-activity and workflow-level timeout/budget limits. The spec needs a `max_total_retries_per_conversation` and/or `max_conversation_duration_ms` to bound worst-case latency.

**Fix:** Add a conversation-level retry budget: `max_total_retries: 20` (global), `max_conversation_duration_ms: 300000` (5 min). Each node draws from the global budget. On exhaustion → `errorNode` with `escalate_to_human`.

---

## 4. completeness — Missing LLM Provider Failover Strategy

**Affected:** `tool-ecosystem.md` §10; `response-generation-layer-design.md` §3

§10 defines 4 LLM providers (OpenAI, Anthropic, Ollama, Azure) but the spec never defines a **failover strategy**. What happens when:
- OpenAI returns a 5xx error during extraction?
- Anthropic's rate limit is hit during response generation?
- The primary provider's latency exceeds the node's timeout?

This is a critical gap for fintech/regulated industries. The `retry_budget` handles intra-provider retries but not inter-provider failover. A production system needs:
- **Provider health checks** (not just retry on failure)
- **Fallback chain**: primary → secondary → local model → cached/default
- **Circuit breaker**: after N consecutive failures, stop sending to that provider for T seconds
- **Cost-aware routing**: route to cheapest provider that meets latency SLA (important for high-volume deployments)

**Fix:** Add an LLM provider failover configuration section with provider priority chains, circuit breaker thresholds, and cost/latency routing policies.

---

## 5. completeness — Static Agent Discovery Lacks Health Checks

**Affected:** `a2a-protocol.md` §4.3

Static discovery (§4.3) lists agent endpoints with no health check mechanism:
```yaml
static_agents:
  - agent_id: rag_faq
    endpoint: "http://localhost:8001"
```

If `rag_faq` goes down, the parent workflow will:
1. Send A2A request
2. Wait for timeout (up to `timeout_ms` — potentially 30 seconds)
3. Retry per budget
4. Eventually hit `errorNode`

This is ~60-90 seconds of wasted latency. The dynamic discovery mode has `health_endpoint` but static mode doesn't — creating a silent availability gap. The framework should support **active health checks** (periodic `/a2a/health` polling or passive circuit breaking) for static agents too.

**Fix:** Add `health_check` configuration for static agents: `health_endpoint`, `check_interval_sec`, `unhealthy_threshold`. If an agent is unhealthy, route immediately to `errorNode` without attempting invocation.

---

## 6. clarity — "Phase Return Stack" vs "Sub-Workflow Phase Stack" Ambiguity

**Affected:** `routing-execution-layer-design.md` §4.2, §5.5

§4.2 defines `phase_stack` for mid-flow detours (push current phase → handle question → pop → resume). §5.5 states: *"Each level has its own isolated state, phase stack, and retry budgets."*

**Ambiguity:** Does each sub-workflow nesting level get its own `phase_stack`, or does a single `phase_stack` span all levels? The diagrams suggest per-level isolation, but the prose conflates the two:

- §4.2: The stack is on the parent workflow's state — `agentState.phase_stack`
- §5.5: "Each level has its own isolated state, phase stack"

If a sub-workflow encounters a mid-flow question and detours to a sub-sub-workflow, which `phase_stack` is the push/pop on? The spec doesn't specify the interaction between parent and child phase stacks. This matters for:
- What happens if a sub-workflow's `phase_stack` is non-empty when it returns to the parent?
- Can a sub-workflow detour push onto the parent's stack?
- Does the parent see the sub-workflow's incomplete phases?

**Fix:** Clarify that each sub-workflow level has its own `phase_stack`. When a sub-workflow returns to the parent, its `phase_stack` must be empty (or an error is raised). Sub-workflows cannot push onto the parent's stack.

---

## 7. clarity — "Goal Checker Runs in Parallel with Response Generation" vs Streaming Blocking

**Affected:** `response-generation-layer-design.md` §4.1, §6.1

§4.1: *"At workflow end, an LLM node runs in parallel with response generation to verify whether the workflow actually achieved its goal."*

§6.1 diagram: Both `generateResponse` and `goalChecker` converge at `responseRouter`, which THEN decides to deliver or 422.

**Unclear:** Is the response delivered to the user BEFORE the goal checker completes, or AFTER? The diagram shows `deliver response` only after `responseRouter` runs, which runs only after **both** parallel nodes complete. This means:

1. Response is generated (1-3 seconds)
2. Goal is checked (1-3 seconds) — these may overlap in wall clock, but both must finish
3. Router decides → deliver or 422

The user waits for `max(generateResponse_time, goalChecker_time)`, not `min()`. If both take 2 seconds, the user waits 2 seconds. But if either takes 3 seconds, the user waits 3 seconds even if the response was ready at 2 seconds.

If the spec intends **optimistic delivery** (send response immediately, append/correct if goal check fails), it never states this. The current design is conservative: hold response until verified. This should be an explicit trade-off discussion.

**Fix:** Add explicit semantics: "Response is held until goal check completes (conservative) OR response is streamed immediately with late-binding correction (optimistic)." Make this a configurable strategy.

---

## 8. consistency — `tool_allowlist` in Routing vs `allowed_tools` in Permission Node Schema Use Different Names

**Affected:** `routing-execution-layer-design.md` §7.2 vs `tool-ecosystem.md` §7.5

The Routing & Execution spec (§7.2) uses `allowed_tools` in the `NodePermission` schema. The A2A tool section (§7.5.4) uses `tool_allowlist` in node YAML:

```yaml
# Routing spec §7.2
permission:
  allowed_tools: [calculate_premium_api]

# A2A tool §7.5.4
nodes:
  process_quote:
    tool_allowlist: [calculate_premium_api, delegate_claim_to_agent]
    permission:
      allowed_tools: [calculate_premium_api, delegate_claim_to_agent]
```

The A2A example uses **both** `tool_allowlist` (node-level) and `allowed_tools` (permission-level) as separate concepts. But neither spec defines `tool_allowlist` as a formal schema field. Is `tool_allowlist` the node's declared capability ("this node may call these tools") while `allowed_tools` is the permission gate ("this node is authorized to call these tools")? Or are they synonyms?

If they are distinct concepts, the relationship must be defined: `tool_allowlist` ⊆ `allowed_tools`? Can an LLM node dynamically select tools from its `tool_allowlist` that aren't in `allowed_tools`?

**Fix:** Unify naming or clearly define the distinction. Suggested resolution:
- `tool_allowlist` = node's **capability declaration** (what tools it can choose from)
- `allowed_tools` = node's **permission gate** (what tools it's authorized to use)
- Invariant: `tool_allowlist ⊆ allowed_tools` (enforced at YAML validation time)

---

## 9. consistency — `errorNode` vs `error_node` Naming Inconsistency

**Affected:** Multiple specs

The specs use inconsistent naming for the error handling node:

| Spec | Field Name |
|------|-----------|
| Routing §6.2 `retry_budget` | `on_exhausted: errorNode` |
| Routing §6.5 | `errorNode_input`, `errorNode_output` |
| Routing §6.8 | `default_error_node`, `errorNode_config` |
| Tool Ecosystem §2.2 table | `errorNode` (camelCase, noted as corrected from ErrorNode in v0.4.0) |
| Response Generation §4.4 | `errorNode` |
| Tool Ecosystem §7.4 | `default_error_node: errorNode`, `route_to: errorNode` |

The mix of `errorNode` and `error_node` in YAML keys within the same file (e.g., §6.8 uses `default_error_node` but `errorNode_config`) is confusing. The Routing spec uses camelCase for the node identifier (`errorNode`) but snake_case for config keys referencing it (`default_error_node: ask_clarify`).

**Fix:** Adopt a consistent convention:
- YAML keys: `snake_case` (e.g., `on_exhausted: error_node`, `default_error_node`)
- Node identifiers (values): `snake_case` (e.g., `error_node`, not `errorNode`)
- Or vice versa — but pick one and apply it uniformly.

---

## 10. consistency — A2A Tool Contract Duplicated Across Two Specs

**Affected:** `tool-ecosystem.md` §7.5.2 vs `a2a-protocol.md` §2.2

The A2A tool contract is defined in **two places** with slightly different schemas:

Tool Ecosystem §7.5.2:
```yaml
Tool:
  name: string
  type: a2a
  access_level: read | write | sensitive_data_read | dangerous_operation_write
  a2a:
    agent_id: string
    mode: sync | async
    timeout_ms: integer
    input_mapping: ...
    output_mapping: ...
```

A2A Protocol §2.2 `a2a_request`:
```yaml
a2a_request:
  agent_id: string
  correlation_id: string
  caller: { agent_id, workflow_id }
  goal: { summary, expected_outputs }
  entities: ...
  constraints: { deadline_ms, priority }
  mode: sync | async
  version: string
```

The A2A protocol message format includes `correlation_id`, `caller`, `version`, `goal`, and `priority` — none of which appear in the tool contract. The tool contract has `input_mapping` and `output_mapping` which don't appear in the wire format.

This is intentional (tool contract = configuration; A2A request = wire format), but the relationship is never explicitly diagrammed: **how does `input_mapping` generate `goal.expected_outputs`?** The spec should show the transformation pipeline from tool config → A2A request wire format.

**Fix:** Add a section explicitly mapping each tool contract field to the A2A request it generates. Show a concrete example of the transformation.

---

## 11. trade_off_gap — Deterministic vs LLM Decision Trade-off Not Quantified

**Affected:** `routing-execution-layer-design.md` §3.5

The decision comparison matrix (§3.5) compares Option A (Rule Engine) and Option C (Strict) but **omits Option B (Rule Engine + LLM Fallback)** — which is the most interesting case. Option B is deferred "for future discussion" (§3.2) but the trade-off is precisely what the spec should address:

| Dimension | A (Rule Only) | B (Rule + LLM) |
|-----------|--------------|-----------------|
| Coverage | Closed-world | Open-world (handles novel inputs) |
| Cost | $0/routing | $0.002-0.01/fallback |
| Latency | <1ms | +1-3s on fallback |
| Accuracy | 100% for known rules | 85-95% for novel cases (needs evals) |
| Maintenance | Manual rule updates | Rules + prompt updates |

Without quantifying the trade-off, the spec cannot guide when Option B is appropriate. Insurance underwriting (10,000 rules) vs claims processing (novel fraud patterns daily) have different profiles.

**Fix:** Add the B vs A/C trade-off matrix. Provide guidance: Option A for stable domains with complete rule sets; Option B for domains with evolving edge cases; Option C for safety-critical where no LLM involvement is acceptable.

---

## 12. trade_off_gap — Copy-on-Write Overhead vs Lock Contention Not Benchmarked

**Affected:** `routing-execution-layer-design.md` §1.2

§1.2 claims: *"Copy overhead per node (nanoseconds for small state)"* — but this is asserted without evidence or qualification.

For a conversation with:
- 30 turns of history (messages array)
- 15 collected fields (address, name, DOB, property details, coverage options, etc.)
- Goal object, phase stack, tool results, audit entries
- Each node copies the entire state

The state could easily reach 50KB-200KB. Deep-copying this per node (10-20 nodes per turn) adds up. The spec's "nanoseconds" claim is for a near-empty state — not representative of production.

The alternative (shared mutable state + lock) was dismissed because "race condition risk... possible on compound ops." But the spec never evaluates **optimistic concurrency** (version vectors, compare-and-swap) or **immutable data structures** (persistent collections with structural sharing). These offer zero-copy semantics without lock overhead.

**Fix:** Replace "nanoseconds" with a measured or estimated range. Add a discussion of immutable data structures as an alternative to deep-copy. If deep-copy is the chosen strategy, document the state size threshold beyond which performance degrades.

---

## 13. missing_edge_case — Sub-Workflow Deadlock via Nested Sync Invocation

**Affected:** `routing-execution-layer-design.md` §5.4, §5.5

Sub-workflows can recursively nest (§5.5): `rag_faq` → `translate_query` → further sub-workflows. With sync invocation (§5.4), the parent blocks waiting for the child.

**Deadlock scenario:** Agent A invokes Agent B (sync); Agent B invokes Agent A (sync) — either directly or through an intermediate chain. Since each blocks waiting for the other, both deadlock.

The spec has no cycle detection or max-depth enforcement for sync invocation chains. Open Question 2 asks: "Should sub-workflows support recursion?" but the answer must address deadlock, not just complexity.

Similarly, the A2A protocol (§6.1 step 5a: "Framework sends A2A request, blocks, waits for response") has the same vulnerability.

**Fix:** Add:
1. `max_sub_workflow_depth` (default 5) — enforced at invocation time
2. Cycle detection — track the call chain via `correlation_id` parent references; refuse invocation if the target agent is already in the call chain
3. `sync_invocation_timeout` — if a sync call exceeds this (accounting for all nested levels), `errorNode`

---

## 14. missing_edge_case — Goal Checker Runs After User Abandonment

**Affected:** `response-generation-layer-design.md` §4

The goal checker runs at workflow end. But what if the user **abandons the conversation** mid-workflow? The workflow never reaches its end state. Does the goal checker:

- Never run (the conversation times out in `active` state)?
- Run on timeout but produce misleading results (0% completion because the user left)?
- Trigger cleanup logic (partial results saved, user notified)?

The conversation lifecycle spec (referenced but not part of this review) should define timeout behavior, but the response generation spec should address what happens when goal check **cannot run** because the workflow never completed.

**Fix:** Add a timeout behavior: if the conversation reaches `timeout` lifecycle state, the framework runs a partial goal check (what was completed so far) and logs the gap analysis for audit. The 422 flow is not triggered (user already left).

---

## 15. missing_edge_case — PII in LLM Prompts Before Filtering

**Affected:** `response-generation-layer-design.md` §8.3

§8.3 states: *"PII rules are applied before prompt construction. The framework applies this filter to state.collectedFields before injecting entities into any LLM prompt template."*

**Edge case:** What if the **user's last message** (passed as `last_user_message` to the prompt) contains PII? The spec only filters `state.collectedFields` — not the raw user input. A user typing "My credit card is 4111-1111-1111-1111" would have that raw text injected into the prompt template for goal setting, extraction, decision LLMs, and response generation — bypassing PII scrubbing.

The spec's PII scope (§8.1) covers `response_text` and `component_data` (output scrubbing) and `collectedFields` (input filtering), but not `messages` or `last_user_message` in the conversation history that gets included in prompts.

**Fix:** Extend `prompt_entity_filter` to also apply PII rules to the conversation history injected into prompts. Or, more aggressively, run the full PII detection pipeline on every user message before it enters any LLM context.

---

## 16. missing_edge_case — `conflict_detect` Reducer Raises Error but No Recovery Path

**Affected:** `routing-execution-layer-design.md` §1.2

§1.2 defines `strategy: conflict_detect` — *"Raise StateConflictError if same key is written by two sources in the same tick."*

**But what happens after `StateConflictError` is raised?** The spec doesn't define the recovery path:
- Does the error route to `errorNode` like all other errors?
- Does the framework retry one of the conflicting nodes serially?
- Does it use a resolution strategy (`on_conflict: log_and_override`)?

The reducer interface (§1.3) defines `on_conflict: "raise" | "log_and_override" | "queue"` but:
1. `raise` and `log_and_override` are strategies in the `on_conflict` field but `raise` is also the behavior of `conflict_detect` — this is circular
2. `queue` — what does queuing mean? Serialize the conflicting writes? Queue them for later resolution?

The spec doesn't define what `StateConflictError` does to the workflow. Without this, `conflict_detect` is a debugging tool, not a production safety mechanism.

**Fix:** Define the `StateConflictError` recovery flow. If `on_conflict: raise` → `errorNode` with the conflicting fields in context. If `on_conflict: log_and_override` → log warning, apply last-write-wins. If `on_conflict: queue` → serialize writes in FIFO order (second writer blocks until first completes).

---

## 17. completeness — No SDK Tool Timeout Budget Per Conversation

**Affected:** `tool-ecosystem.md` §7.6; Open Question 12

Open Question 12 asks about cost governance for SDK tools but the spec doesn't address it. SDK tools (OpenCode `do`, Claude `do`) are **the most expensive and slowest tool type**:
- OpenCode `do` can run for minutes, invoking sub-tools, making multiple LLM calls
- Claude with tool use can consume significant token budgets

A single `opencode_refactor_module` call could consume 100K+ tokens across its internal tool calls. Without a budget:
- A `max_llm_tool_calls: 15` node (§7.5.7) could invoke 15 SDK `do` calls, each consuming unlimited resources
- No per-conversation cost cap exists

**Fix:** Add SDK tool budgets:
- `max_sdk_calls_per_conversation: 5`
- `max_sdk_cost_cents_per_conversation: 50` (approximate)
- `max_sdk_duration_ms_per_call: 120000` (2 min, already present as `timeout_ms`)
- On budget exhaustion → fall back to non-SDK tool or errorNode

---

## 18. clarity — "Transition Permission" (§7.7) Enforcement Point Is Undefined

**Affected:** `routing-execution-layer-design.md` §7.7

§7.7 defines transition enforcement: *"The framework enforces this on every state transition."* But it doesn't specify **when** enforcement occurs:

- **At YAML load time:** Validate that all declared transitions are in `allowed_transitions` — catches config errors early but doesn't cover dynamic routing (e.g., decision node output).
- **At runtime, before transition:** Validate the resolved next node against `allowed_transitions` — covers dynamic routing but allows a decision node to route to a forbidden state (then the transition is blocked).
- **At runtime, after decision:** Validate the decision output against `allowed_transitions` before executing the transition.

The spec implies runtime enforcement (`on_violation: TRANSITION_DENIED` with a runtime error message) but doesn't address what happens if a **decision node** (which deterministically routes to a target) outputs a target not in `allowed_transitions`. The spec says the framework "enforces" the transition — does it:
- Block the transition → route to `errorNode`?
- Allow it (because the decision node is "authoritative")?
- Raise a `TRANSITION_DENIED` error?

**Fix:** Clarify the enforcement point. Suggested: enforce at decision output time. If the resolved transition target is not in `allowed_transitions`, the framework raises `TRANSITION_DENIED` and routes to the node's configured `error_node`. The node's `allowed_transitions` list becomes the **validated output space** for decision nodes.

---

## Summary Table

| # | Tag | Issue | Severity |
|---|-----|-------|----------|
| 1 | correctness | Reducer mandatory rule contradicts non-overlapping field safety | High |
| 2 | correctness | A2A error category enum missing `tool_error`, `unrecoverable_error` | Low |
| 3 | completeness | Missing conversation-level retry/duration budget | High |
| 4 | completeness | Missing LLM provider failover strategy | High |
| 5 | completeness | Static agent discovery has no health checks | Medium |
| 6 | clarity | Phase stack isolation between parent/child sub-workflows ambiguous | Medium |
| 7 | clarity | Response delivery timing (before/after goal check) not explicit | Medium |
| 8 | consistency | `tool_allowlist` vs `allowed_tools` naming conflict undefined | Medium |
| 9 | consistency | `errorNode` vs `error_node` naming inconsistent across specs | Low |
| 10 | consistency | A2A tool contract duplicated with different schemas across specs | Medium |
| 11 | trade_off_gap | Decision Rule+LLM trade-off not quantified (Option B deferred) | Medium |
| 12 | trade_off_gap | Copy-on-write "nanoseconds" claim unsubstantiated | Low |
| 13 | missing_edge_case | Sub-workflow deadlock via nested sync invocation | High |
| 14 | missing_edge_case | Goal checker behavior on user abandonment not defined | Medium |
| 15 | missing_edge_case | PII in raw user messages bypasses prompt filtering | High |
| 16 | missing_edge_case | `StateConflictError` has no recovery flow defined | Medium |
| 17 | completeness | No cost/token budget for SDK tools | Medium |
| 18 | clarity | Transition permission enforcement point (load vs runtime) undefined | Medium |
