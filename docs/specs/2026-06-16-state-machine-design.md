# State Machine Layer Design — transitions + LangGraph Fusion

> See also: [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) for overall architecture and non-FSM concerns.
> All concrete workflow examples have been extracted to [examples/home-insurance/](../../examples/home-insurance/).

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | Initial design: transitions as source of truth, LangGraph as infra layer |
| 2026-06-16 | 0.2.0 | Add state metadata (precondition, postcondition, guards, invariants) |
| 2026-06-16 | 0.3.0 | Add invoice and payment use cases; full English translation |
| 2026-06-16 | 0.4.0 | Add Section 8: Intent + State resolution (per-state intent policy, confirmation flow) |
| 2026-06-16 | 0.5.0 | Extract all examples to examples/home-insurance/; remove invoice/payment appendices; unify on home insurance domain |
| 2026-06-17 | 0.6.0 | Term consistency (errorNode, agentState.phase); add References section |
| 2026-06-17 | 0.7.0 | Add Section 1.1: Implementation Approaches (YAML-Only vs Code-First vs Hybrid) |
| 2026-06-18 | 0.8.0 | Change default recommendation to Option C (Hybrid); add §1.2 registration & lookup mechanism; add §4.1 auto-generated Mermaid visualization + CI snapshot verification |
| 2026-06-18 | 0.9.0 | Add §3.5 State Lifecycle Actions: declarative field mutations via on_entry/on_exit/on_take.set_field — all agentState writes visible in YAML; expand §3.3 field reference |
| 2026-06-18 | 1.0.0 | Add §1.0 Semantic Model — SCXML: adopt W3C SCXML Recommendation as the state machine semantic standard; full SCXML ↔ YAML mapping table; YAML as canonical artifact, SCXML for compliance/audit reference |

---

## 1. Core Principle

> **transitions defines WHAT (business correctness). LangGraph executes HOW (conversation infrastructure).**
>
> Developers maintain only the transitions definition. The LangGraph graph, LLM nodes, checkpointing, and interrupt are all auto-generated.

### 1.0 Semantic Model — SCXML

The state machine semantic model follows the **W3C SCXML (State Chart XML) Recommendation** — the W3C standard for statechart-based control abstractions. SCXML defines the complete conceptual vocabulary: states, transitions, entry/exit actions, guards, data model, parallel regions, history, invoke, and send.

Our YAML workflow definition is **a YAML expression of SCXML semantics**, executed on LangGraph. No XML file is generated — the YAML is the canonical artifact. The semantic alignment serves two purposes:

1. **Compliance & Audit:** regulated industries generally can reference a W3C standard to justify state machine correctness
2. **Conceptual completeness:** SCXML's semantic model is proven and comprehensive; we adopt it wholesale rather than inventing our own

**SCXML ↔ YAML Mapping:**

| SCXML concept | W3C reference | Our YAML |
|---------------|---------------|----------|
| `<state>`, `<parallel>`, `<final>` | §3.2 States | `states:` collection |
| `<transition event="" cond="" target="">` | §3.3 Transitions | `transitions:` with `guard:` and `to:` |
| `<onentry>` | §3.3.2 | `on_entry: set_field:` |
| `<onexit>` | §3.3.2 | `on_exit: set_field:` |
| `cond="expr"` | §3.4 | `guard: "expr"` / `@register_guard` |
| `<datamodel><data>` | §4 | entities + `agentState.collectedFields` |
| `<assign location="" expr=""/>` | §4.4 | `set_field: x: "expr"` |
| `<send event="" target="">` | §3.12 | framework internal (checkpoint events) |
| `<invoke type="" src="">` | §3.9 | `executor: sub_workflow` |
| `<parallel>` | §3.8 | parallel composite state + `Send()` |
| `<history type="shallow\|deep">` | §3.7 | deferred (Appendix C.1 Q5) |
| `<final>` | §3.2.4 | implicit (no outgoing transitions) |
| `<log label="" expr="">` | §4.5 | framework auto-checkpoint audit log |
| `<script>` | §4.6 | not supported — complex logic via Python actions |
| `<if>`, `<elseif>`, `<else>` | §4.7 | Python guards / YAML guard expressions |
| `<foreach>` | §4.8 | not supported — iteration via Python actions |

> **Implementation:** `SCXML 1.0` — W3C Recommendation 1 September 2015
> **Reference:** https://www.w3.org/TR/scxml/

---

## 1.1 Implementation Approaches

Three architectural options for implementing the state machine layer. All three share the same `transitions` mental model; they differ in *how* the definition is authored and consumed.

### Option A: YAML-Only Declarative (Current Approach)

States and transitions are defined purely in YAML. No code touches the state graph directly — the framework auto-generates the LangGraph graph at startup.

```yaml
# transitions.yaml
states:
  - name: collect_info
    executor: llm
    intent_policy:
      accept: [provide_information, ask_question]
      on_unlisted: ask_confirm
  - name: calculate_premium
    executor: code
    action: compute_premium

transitions:
  - from: collect_info
    to: calculate_premium
    guard: "context_complete"
```

**Pros:** Fully auditable (YAML is human-readable), no code-generation step, entire workflow is version-controlled as a single YAML artifact.

**Cons:** Complex guard logic is cumbersome in a string expression language. Runtime control flow lives entirely inside the framework generator.

### Option B: Code-First LangGraph

States are defined programmatically in Python. The developer constructs LangGraph nodes directly; the framework provides helper decorators and base classes but does NOT generate the graph from YAML.

```python
from framework import StateNode, Transition, build_graph

collect_info = StateNode(
    name="collect_info",
    executor="llm",
    intent_policy={"accept": ["provide_information"], "on_unlisted": "ask_confirm"},
)

calculate_premium = StateNode(
    name="calculate_premium",
    executor="code",
    action=compute_premium,
)

collect_info >> Transition(to=calculate_premium, guard="context_complete")

graph = build_graph([collect_info, calculate_premium])
```

**Pros:** Guards can be arbitrary Python functions (`guard=lambda ctx: ctx.risk_score > 80 and ctx.amount > 5000`). Full IDE support (autocomplete, type-checking, refactoring). Easier unit testing of individual nodes.

**Cons:** Less auditable — non-technical stakeholders cannot read the state machine. The graph definition is spread across Python files rather than in a single declarative artifact. Risk of imperative leaks (business logic mixed with graph construction).

### Option C: Hybrid (YAML Base + Code Overrides)

A YAML file defines the base structure (states, transitions, metadata). Complex guard functions, custom validators, and tool bindings are implemented in Python and referenced by name from the YAML.

```yaml
# transitions.yaml
states:
  - name: assess_risk
    executor: code
    action: assess_risk
    exit_guard: high_risk_override  # references a Python function
```

```python
# guards.py
def high_risk_override(ctx: AgentState) -> bool:
    return ctx.risk_score > 80 and ctx.total_claims > 3
```

**Pros:** Best of both worlds — YAML for structure/auditability, Python for complex logic. Guards stay readable while supporting arbitrary complexity. YAML remains the definition; Python code is referenced by name, never drives state transitions directly.

**Cons:** Two artifacts to maintain per workflow. Risk of drift between the YAML declaration and the code implementation (mitigated by drift detection at framework startup — see §1.2).

### 1.2 Option C Registration & Lookup Mechanism

Python functions (guards, validators, actions, tool bindings) are registered by name and referenced from YAML.

**Registration:**

```python
# actions.py
from framework import register_action

@register_action("compute_premium")
def compute_premium(ctx: AgentState) -> dict:
    base = ctx.rate_table.get(ctx.coverage_type)
    return {"premium": base * ctx.age_factor * ctx.risk_multiplier}
```

```python
# guards.py
from framework import register_guard

@register_guard("high_risk_override")
def high_risk_override(ctx: AgentState) -> bool:
    return ctx.risk_score > 80 and ctx.total_claims > 3
```

```python
# validators.py
from framework import register_validator

@register_validator("zip_code_check")
def zip_code_check(value: str) -> bool:
    return len(value) == 5 and value.isdigit()
```

**YAML references names only:**

```yaml
# workflow.yaml
states:
  - name: assess_risk
    executor: code
    action: compute_premium              # references @register_action("compute_premium")
    exit_guard: high_risk_override       # references @register_guard("high_risk_override")
    output_schema:
      zip_code:
        type: str
        validator: zip_code_check        # references @register_validator("zip_code_check")
```

**Runtime lookup flow:**

```
workflow.yaml loaded at startup
       │
       ▼
For each state, for each guard/action/validator name:
  1. Look up in global registry (dict[str, Callable])
  2. Match found → bind to node
  3. Match not found → framework raises StartupError("action 'compute_premium' not registered")
       │
       ▼
If any binding fails → framework refuses to start
```

**Drift detection:** At startup, the framework validates that every name referenced in YAML resolves to a registered Python function. If any name is unresolved, the framework raises a `StartupError` and refuses to initialize. This guarantees YAML ↔ code consistency at load time, not at runtime.

**Convention:** One Python module per workflow (e.g., `workflows/home_insurance/actions.py`, `guards.py`, `validators.py`). The framework auto-discovers registered functions by scanning the workflow directory at startup. No manual import registration needed — decorators auto-register into the global registry.

### Comparison Matrix

| Dimension | Option A: YAML-Only | Option B: Code-First | Option C: Hybrid |
|-----------|--------------------|----------------------|------------------|
| **Determinism** | High — pure data-driven | High — code is deterministic | Medium-High — code overrides introduce flexibility |
| **Developer-Friendliness** | Medium — YAML is simple but guards are limited | High — full IDE support, type safety | Medium — YAML base is simple, code overrides require discipline |
| **Auditability** | High — single YAML file, non-technical readable | Low — spread across Python files | Medium — YAML for structure, Python for details |
| **Flexibility** | Low — guard expression language is minimal | High — arbitrary Python for guards/validators | Medium — constrained to YAML structure, flexible on details |
| **Version Control** | Excellent — single YAML diff tells the whole story | Good — but state machine logic scatters across files | Good — YAML diffs + code diffs must be reviewed together |

**Default recommendation: Option C (Hybrid) — YAML as definition, Python for complex logic.** YAML is always the single source of truth for the workflow structure (states, transitions, schemas, metadata). Complex guard expressions, custom validators, tool bindings, and action functions are implemented in Python and referenced by name from YAML. Option A (YAML-Only) is available for simple workflows where the guard expression language suffices. Option B (Code-First) is available for teams that prefer Python-native workflows and do not require YAML auditability.

---

## 2. transitions Definition Format (Single Source of Truth)

> **Developers maintain only the transitions definition.** The LangGraph graph, LLM nodes, checkpointing, and interrupt are all auto-generated from this single YAML file.

For the complete definition format and a concrete home insurance workflow, see [workflow.yaml](../../examples/home-insurance/workflow.yaml). The format supports:

- **states**: typed nodes (`executor: llm | code`) with schemas, guards, metadata, and tool allowlists
- **transitions**: named edges with guard expressions, self-loops, and `on_take` side-effects
- **Meta-variables**: framework-generated flags (`context_incomplete`, `exit_guard_pass`, `all_approved`, etc.) usable in guard expressions
- **Declarative field mutations**: `on_entry`, `on_exit`, `on_take` — `set_field` assignments declared directly in YAML, tracking every agentState write in a single artifact (see §3.5)

---

## 3. State Metadata — Precondition / Postcondition / Guard / Invariant

Each state can carry 5 types of metadata, enforced at different points in the state lifecycle:

```
                  +---------------------------------------+
                  |  precondition                          |
                  |  "What must be true before entry"       |
                  |  (design contract — static verification)|
                  +------------------+--------------------+
                                     |
                  +------------------v--------------------+
                  |  entry_guard                           |
                  |  "Final check at the door"             |
                  |  (runtime — reject on failure)         |
                  +------------------+--------------------+
                                     | passed
              +----------------------v------------------------+
              |            STATE: calculate                    |
              |                                                |
              |   +----------------------------------------+  |
              |   |  data_invariant                         |  |
              |   |  "What must hold while in this state"    |  |
              |   |  (runtime — assertion error on violation)|  |
              |   +----------------------------------------+  |
              |                                                |
              |   action: compute_premium(data)                 |
              |                                                |
              |   +----------------------------------------+  |
              |   |  exit_guard                              |  |
              |   |  "One more check before leaving"          |  |
              |   |  (runtime — block transfer, route elsewhere)|  |
              |   +------------------+---------------------+  |
              +----------------------+------------------------+
                                     | passed
                  +------------------v--------------------+
                  |  postcondition                         |
                  |  "What must be true after exit"         |
                  |  (design contract — static verification)|
                  +---------------------------------------+
```

### 3.1 Definitions

| Concept | Trigger Timing | Failure Behavior | Purpose |
|---------|---------------|------------------|---------|
| **precondition** | Before entry | Does not block runtime; static analysis reports contract violation | Design contract for test generation |
| **entry_guard** | At entry | Runtime rejection; routes to errorNode | Runtime safety gate |
| **data_invariant** | Throughout state lifetime | Runtime AssertionError; interrupts workflow | Runtime data integrity protection |
| **exit_guard** | At exit | Runtime block; routes to alternate branch | Branch routing based on computed result |
| **postcondition** | After exit | Does not block runtime; verification tool reports violation | Ensures action function output contract |

> **Note on static verification:** The "static analysis" and "verification tool" referenced above refers to a planned YAML linter and test generator (design TBD) that reads preconditions, postconditions, and invariants to catch contract violations before deployment. This tooling is out of scope for the current design document; see Appendix C.7 for related open questions.
>
> **Note on errorNode:** errorNode provides unified error handling, defined in [Routing & Execution §6.5](./2026-06-17-routing-execution-layer-design.md).

### 3.2 Example Patterns

> For a complete state annotated with all 5 metadata fields, see `assess_risk` and `calculate_premium` states in [workflow.yaml](../../examples/home-insurance/workflow.yaml). Below are the key behavioral patterns.

**Guard vs Contract:**

```
                      Guard                          Contract
                      (entry_guard / exit_guard)     (precondition / postcondition)

  Timing              Runtime                         Offline (static analysis / test generation)
     Failure behavior    Routes to errorNode       Marks as "contract violation", does not block execution
  Typical use         "age < 18 -> direct reject"      "This state declares it needs age; generate test with age<18"
  Expression req.     Must be runtime-evaluable        Can be descriptive comment or formal formula
```

### 3.3 Complete State Field Reference

```yaml
states:
  - name: <state_name>
    executor: llm | code

    # --- State Metadata (all optional) ---
    precondition:     "expression or comment"
    entry_guard:      "runtime-evaluated boolean expression"
    data_invariant:   "constraint monitored throughout state lifetime"
    exit_guard:       "boolean expression evaluated on exit"
    postcondition:    "expression or comment"

    # --- Data Schemas (optional, recommended) ---
    input_schema:     {field: type, ...}     # data required from upstream state
    context_schema:   {field: type, ...}     # working memory while in this state
    output_schema:    {field: type, ...}     # data produced for downstream states

    # --- Execution ---
    action:           "function name (required for code executor)"
    prompt:           "system prompt (required for llm executor)"
    tool_allowlist:   [...]                  # tools the LLM may call in this state
    human_review:     true | false           # whether to interrupt for human approval
    review_prompt:    "what the approver sees"
    stream:           true | false           # whether to stream LLM output
    on_entry:                                      # see §3.5
      set_field: { field: "expression", ... }       # assign fields on state entry
    on_exit:                                       # see §3.5
      set_field: { field: "expression", ... }       # assign fields on state exit
    on_error: errorNode            # state to enter on unhandled error
    description:      "human-readable note about what this state does"

    # --- Guard Meta-Variables (framework-generated, usable in guard expressions) ---
    # These are not user-defined fields. The framework sets them automatically:
    #   exit_guard_pass    — true if all exit_guard constraints passed
    #   exit_guard_blocked — true if any exit_guard constraint failed
    #   context_complete   — true when the LLM confirms it has all needed data
    #   context_incomplete — true when the LLM needs more info (drives self-loop)
    #   all_approved       — true when all required human approvals received
    #   any_rejected       — true when any human approval was rejected
    #   any_field_missing  — true when output_schema has null required fields
    #   retries_exhausted  — true when LLM or code node has exceeded max retries
```

### 3.4 Guard Expression Syntax

Guard expressions support:
- **State field access:** `field_name`, `schema.field_name` (e.g., `amount`, `collected_data.age`)
- **Boolean operators:** `AND`, `OR`, `NOT`, `and`, `or`, `not`
- **Comparison operators:** `==`, `!=`, `>`, `<`, `>=`, `<=`
- **List membership:** `field in [a, b, c]`, `field in ['a', 'b', 'c']`
- **Null checks:** `field != null`, `field == null`
- **Meta-variables:** framework-generated flags listed in §3.4
- **Natural language prose:** allowed as fallback when the condition cannot be mechanically evaluated (treated as "not verifiable by static analysis, always raises a warning")

Full formal grammar is deferred to implementation planning (see Appendix C.2).

### 3.5 State Lifecycle Actions — Declarative Field Mutations

Every agentState field write is declared in the YAML. Three lifecycle hooks provide `set_field` assignments at precise execution points. No Python code needed for simple field assignments.

```
  +--------+
  | entry  |  on_entry.set_field  ── executed once, before the state's main logic
  +--------+
       │
       ▼
  +--------+
  | main   |  executor (llm|code) ── runs the state's primary action or LLM prompt
  +--------+
       │
       ▼
  +--------+
  | exit   |  on_exit.set_field  ── executed once, after main logic, before any transition
  +--------+
       │
       ▼
  +--------+
  | take   |  on_take.set_field  ── executed on a specific transition, per-edge
  +--------+
```

**on_entry / on_exit (per state):**

```yaml
states:
  - name: validate_claim
    executor: code
    action: run_claim_validations
    on_entry:
      set_field:
        checked_at: "now()"           # expression: framework calls datetime.now()
        retry_count: 0                # literal: sets retry_count = 0
    output_schema:
      validation_result: { type: dict }
    on_exit:
      set_field:
        last_validated: "now()"       # timestamp on every exit
```

**on_take (per transition):**

```yaml
transitions:
  - from: validate_claim
    to: reject_claim
    guard: validation_failed
    on_take:
      set_field:
        claim_rejected: true          # this path → claim rejected
        alert_level: "CRITICAL"       # escalation marker
```

**Execution order per turn (a state transition from A→B):**

```
1. on_exit.set_field (state A)       ── A's cleanup fields
2. Evaluate exit_guard (state A)     ── determines which transition
3. on_take.set_field (transition)    ── per-edge side effects
4. Checkpoint (transition committed) ── audit: who/when/why
5. on_entry.set_field (state B)      ── B's setup fields
6. Execute state B's main logic      ── executor runs (llm or code)
```

**Why YAML, not Python:** The entire agentState mutation history is visible in a single artifact. Every field write is traceable: which state set it, at which lifecycle point, with what value. No reading action function code to find `ctx.collectedFields["x"] = y` hidden 50 lines deep.

**Expression types in set_field values:**

| Type | Syntax | Example |
|------|--------|---------|
| Literal | quoted or unquoted value | `true`, `0`, `"CRITICAL"` |
| Function call | `fn(args)` | `now()`, `uuid4()`, `len(collectedFields.items)` |
| Field reference | `collectedFields.x` | `collectedFields.premium * 0.1` |

**set_field vs action function output_schema:**

| Mechanism | When | For |
|-----------|------|-----|
| `on_entry / on_exit / on_take.set_field` | Start/end of any state or transition | Metadata, flags, timestamps, counters |
| `action() return dict` → `output_schema` merger | During state main execution | Computed business data (premium, total, risk_score) |

Complex computation still belongs in action functions. Simple field assignments belong in YAML.

---

## 4. Auto-Generated LangGraph Graph

The framework auto-generates a LangGraph StateGraph from the YAML transitions definition. Each state becomes one LangGraph node; each transition becomes a conditional edge.

For the generated graph of a complete workflow, see the diagram in [README.md](../../examples/home-insurance/README.md) and the state-by-state walkthrough in [e2e-scenarios.md](../../examples/home-insurance/e2e-scenarios.md).

**Each state -> one LangGraph node. Executor determines node behavior:**

| executor | LangGraph Node Behavior |
|----------|------------------------|
| `llm` | Auto-inject chat history -> call LLM -> stream output -> checkpoint |
| `code` | Execute deterministic action function; inputs/outputs are auditable |

The graph structure mirrors the transitions definition exactly: the nodes are the states, the edges are the transitions with their guard conditions. Self-loops (e.g., `guard: context_incomplete`) keep the conversation in a state until data is complete.

### 4.1 Auto-Generated Mermaid Visualization

The framework auto-generates a visual diagram of the workflow graph using LangGraph's built-in Mermaid rendering.

**Generation flow:**

```
workflow.yaml           framework          LangGraph              output
    │                       │                  │                     │
    ▼                       ▼                  ▼                     ▼
 YAML parse ──────────> StateGraph ──────> .get_graph() ──────> draw_mermaid_png()
                                                            │
                                                            ▼
                                                   workflow_graph.png
```

**Built-in API:**

```python
from framework import load_workflow, generate_graph_png

graph = load_workflow("workflows/home_insurance/workflow.yaml")
graph.get_graph().draw_mermaid_png(output_file_path="workflow_graph.png")
```

The framework provides a convenience function that wraps the full pipeline:

```python
generate_graph_png(
    workflow_path="workflows/home_insurance/workflow.yaml",
    output_path="docs/workflow_graph.png",
)
```

**CI auto-generation + snapshot verification:**

```yaml
# .github/workflows/ci.yml — verify graph matches committed snapshot
jobs:
  graph-snapshot:
    steps:
      - name: Generate graph from YAML
        run: framework generate-graph workflows/home_insurance/workflow.yaml --output /tmp/generated.png
      - name: Compare against committed snapshot
        run: framework diff-graph /tmp/generated.png docs/workflow_graph.png
```

The CI step regenerates the graph from YAML and compares it byte-for-byte against the committed snapshot. If they differ:
- **PR fails** — the YAML changed but the snapshot wasn't updated (or vice versa)
- **Developer runs** `framework update-graph-snapshot` to regenerate and commit the new snapshot

This guarantees that the graph PNG committed in the repo is always consistent with the YAML definition. Non-technical reviewers can visually inspect `workflow_graph.png` in PR diffs alongside the YAML changes.

**Commitment:** The graph PNG is committed alongside the workflow YAML. Every PR that changes the YAML must also update the graph snapshot. The CI enforces this automatically.

---

## 5. Five-Capability Integration Matrix

| Capability | Mechanism | Integration Point |
|------------|-----------|-------------------|
| **LLM invocation** | executor=llm nodes auto-attach ChatOpenAI | Auto-generated |
| **Streaming output** | executor=llm + stream:true nodes auto-enable .astream_events() | Auto-generated |
| **Conversation persistence** | SqliteSaver.put() auto-called after every node exit | Checkpointer injection |
| **Human-in-the-loop (interrupt)** | executor=llm + human_review:true nodes auto-interrupt() after LLM generation, resume on approval | LangGraph interrupt |
| **Tool calling** | tool_allowlist tools auto-injected into ToolNode | LangGraph ToolExecutor |

---

## 6. End-to-End Walkthrough

> For complete end-to-end conversation examples (quote flow, claim flow, high-risk routing), see [e2e-scenarios.md](../../examples/home-insurance/e2e-scenarios.md). The walkthrough covers:
> - LLM-powered data collection with tool calling
> - Deterministic code execution (risk scoring, premium calculation)
> - Guard-based routing and self-loops
> - Human-in-the-loop interrupt + approval
> - Audit log auto-generation


---

## 7. Why This Architecture Works

| Concern | Resolution |
|---------|------------|
| Maintaining two graphs | Only maintain one YAML; LangGraph graph is generated output, never hand-edited |
| Two state machines conflicting | transitions is the single authority on state; LangGraph is a pure execution engine |
| Too complex | Developer only faces YAML + action functions; generator hides LangGraph details |
| Generator hard to maintain | Generator is itself a deterministic component (YAML in -> graph out), unit-testable |

---

## 8. Intent + State Resolution

### 8.1 Principle

Intent classification (Layer 1) and the state machine (Layer 2) are not independent. An intent has different meanings depending on the current state. The combination of **(intent, current_state)** determines whether a transition is valid, requires confirmation, or is rejected.

### 8.2 Per-State Intent Policy

Each state declares which intents it accepts and how to handle unaccepted intents:

```yaml
states:
  - name: collect_info
    intent_policy:
      accept:
        - provide_information    # user gives data → continue form
        - ask_question           # user asks about coverage → answer within flow
        - decline                # user wants to cancel → confirm then exit
      on_unlisted: ask_confirm   # unrecognized intent → ask user to confirm
```

**Policy behaviors:**

| Behavior | Description |
|----------|-------------|
| `accept` | Intent is valid in this state; proceed with transition |
| `on_unlisted: ask_confirm` | Unlisted intent triggers confirmation: "You're in the middle of [current task]. Do you want to cancel and [new intent]?" |
| `on_unlisted: reject` | Unlisted intent is silently blocked; agent prompts user to continue current task |

### 8.3 Resolution Flow

```
User utterance
      │
      ▼
┌─────────────────┐
│ Layer 1: Intent  │
│ Classification   │ → intent: file_claim, confidence: 0.92
└────────┬────────┘
         ▼
┌─────────────────┐
│ Layer 2: Check   │
│ intent vs state  │
│                  │
│ state=collect_property_info
│ intent_policy:   │
│   accept:        │
│     - provide_information
│     - ask_question
│     - decline
│   on_unlisted: ask_confirm
│                  │
│ file_claim ∉ accept
└────────┬────────┘
         ▼
┌─────────────────┐
│ ask_confirm:     │
│ "You're filling  │
│  a quote form.   │
│  Cancel and file a claim?"│
└────────┬────────┘
         ▼
    user responds
         │
    ┌────┴────┐
    ▼         ▼
  "yes"     "no"
    │         │
    ▼         ▼
  state     stay in
  → idle   collect_property_info
  intent    (re-classify
  → file_claim   next input)
```

### 8.4 Example Scenarios

For concrete intent+state resolution examples within home insurance workflows, see [intent-definitions.md](../../examples/home-insurance/intent-definitions.md) and the `intent_policy` sections in [workflow.yaml](../../examples/home-insurance/workflow.yaml).

### 8.5 Relationship to Other State Machine Concerns

- **Retry counters** are independent of intent resolution. A user who triggers `ask_confirm` does not consume a retry attempt — only invalid data inputs (wrong name, wrong code) increment retries.
- **Sensitive field scrubbing** happens on state exit regardless of whether the exit was triggered by a normal transition, a `decline`, or a confirmed intent switch.

> **Note on phase routing:** The resolved intent+state maps to `agentState.phase`, which drives the phase-aware routing with return stack (defined in Routing & Execution spec Section 4).

## References

- [W3C SCXML 1.0 Recommendation](https://www.w3.org/TR/scxml/) — semantic standard
- [transitions Library](https://github.com/pytransitions/transitions) — Python state machine concept reference
- [LangGraph](https://github.com/langchain-ai/langgraph) — runtime execution engine
- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
- [Domain Model](./2026-06-17-domain-model-design.md)
- [Routing & Execution](./2026-06-17-routing-execution-layer-design.md)
- [Extraction Layer](./2026-06-17-extraction-layer-design.md)
- [Intent Classification](./2026-06-16-intent-classification-design.md)

## Appendix C: Implementation Planning — Open Questions (State Machine)

> Questions identified during design but deferred for implementation planning.
> For non-FSM questions, see [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) Appendix.

### C.1 State Design

> **Sub-workflow:** a state whose internal logic is itself a complete workflow (nested YAML definition). The parent state delegates execution to the child workflow and resumes when it completes.

| # | Question | Impact |
|---|----------|--------|
| 1 | How to define state data schema? `input_schema` / `context_schema` / `output_schema` three-layer isolation vs flat dict | Audit trace granularity, data isolation safety |
| 2 | Maximum sub-workflow nesting depth? Does deep nesting hurt readability | Workflow reusability, maintainability |
| 3 | Is history state (restore to last active sub-state) needed? Implementation strategy | Complex flow breakpoint recovery |
| 4 | Parent state unified entry/exit behavior — should all children run cleanup/validation when leaving parent | Resource management, leak prevention |
| 5 | Dynamic vs static workflow — can the graph structure be modified at runtime | Flexibility vs determinism conflict |

### C.2 Transition & Guard

> **History state:** a pseudo-state that remembers which sub-state was active when the parent was exited, enabling re-entry at the same point. Standard UML statechart concept.

| # | Question | Impact |
|---|----------|--------|
| 6 | Guard expressiveness boundary: pure functions only? Allow external service calls (DB/API) | Performance, determinism, testability |
| 7 | Guard conflict resolution — what happens when multiple guards are simultaneously true | Runtime behavioral determinism |
| 8 | Guard completeness enforcement — how to statically detect uncovered exit guard cases | Prevents runtime deadlock in a state |
| 9 | Implicit errorNode (no-match) design: explicit catch-all vs framework-injected errorNode | Compliance — system must not "freeze" |
| 10 | Full guard expression grammar (see §3.5 for current syntax) | Developer experience, security |

### C.3 Parallel States

> **Orthogonal regions:** multiple concurrently active sub-states within a parent state. For example, while in "onboarding", simultaneously run "verify_identity" and "collect_preferences" in parallel. Standard UML statechart concept.

| # | Question | Impact |
|---|----------|--------|
| 11 | Can orthogonal regions communicate (share data/events) | Parallel branch coupling |
| 12 | How do parallel branches converge: all-complete vs any-complete vs timeout | Complex workflow orchestration flexibility |

### C.4 Error & Recovery

| # | Question | Impact |
|---|----------|--------|
| 13 | When code nodes encounter external API failure or DB unavailability, how does the state machine trigger retry/compensation/rollback transitions | State transition reliability |
| 14 | Global error workflow design — unified errorNode for all uncaught exceptions | Compliance — state machine must not freeze or silently fail |

### C.5 Version Migration

| # | Question | Impact |
|---|----------|--------|
| 15 | How to smoothly migrate in-flight conversation states to a new workflow YAML version | Zero-downtime production updates |
| 16 | How to map old states to new states — auto-inference vs manual mapping table; strategy for state creation/deletion/modification | Migration accuracy |

### C.6 Code Generator

| # | Question | Impact |
|---|----------|--------|
| 17 | How to guarantee YAML definition -> LangGraph graph equivalence | System trust foundation |
| 18 | Generator testability — given YAML input, assert output graph structure is correct | Regression protection |

### C.7 Static Verification

| # | Question | Impact |
|---|----------|--------|
| 19 | Dead state detection — states defined but unreachable by any transition | Code quality |
| 20 | Missing transition detection — states with uncovered event/condition branches | Runtime completeness |
| 21 | Unreachable state detection — states with incoming transitions but unreachable entry | Code quality |
| 22 | Guard conflict detection — two guards that can be simultaneously true pointing to different targets | Runtime non-determinism |
| 23 | Postcondition satisfiability — does the declared postcondition necessarily hold on the normal path | Contract validity |
| 24 | YAML schema strictness — how many errors (field typos, type mismatches) can be caught before deployment | Developer experience |
