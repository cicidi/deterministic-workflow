# State Machine Layer Design — transitions + LangGraph Fusion

> See also: [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) for overall architecture and non-FSM concerns.

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | Initial design: transitions as source of truth, LangGraph as infra layer |
| 2026-06-16 | 0.2.0 | Add state metadata (precondition, postcondition, guards, invariants) |
| 2026-06-16 | 0.3.0 | Add invoice and payment use cases; full English translation |
| 2026-06-16 | 0.4.0 | Add Section 8: Intent + State resolution (per-state intent policy, confirmation flow) |

---

## 1. Core Principle

> **transitions defines WHAT (business correctness). LangGraph executes HOW (conversation infrastructure).**
>
> Developers maintain only the transitions definition. The LangGraph graph, LLM nodes, checkpointing, and interrupt are all auto-generated.

---

## 2. transitions Definition Format (Single Source of Truth)

> This example shows a simplified insurance quote workflow. For brevity, some states omit `input_schema`/`context_schema`/`output_schema`. See Appendix A and B for the complete format.

```yaml
# quote_workflow.yaml — the only file developers maintain
workflow: insurance_quote
states:
  - name: start
    executor: code
    action: reset_context

  - name: collect_info
    executor: llm
    prompt: "Collect applicant info: name, age, car model, driving years"
    output_schema:
      name: str
      age: int
      car_model: str
      driving_years: int
    tool_allowlist: ["lookup_car_price"]
    human_review: false
    on_exit: validate_collected_data

  - name: calculate
    executor: code
    action: compute_premium
    precondition: "all 4 collected_data fields non-null AND age >= 18"
    postcondition: "premium field assigned AND premium > 0"
    entry_guard: "collected_data.age >= 18"
    exit_guard: "premium < 10000"            # premium >= 10000 routes to manual review instead
    data_invariant: "premium >= 0"            # premium must not be negative while in this state
    on_error: error_recovery

  - name: high_premium_review               # reached when exit_guard blocks
    executor: llm
    prompt: "Premium is unusually high. Forward to manual review queue."
    human_review: true
    stream: false

  - name: present_quote
    executor: llm
    prompt: "Present the quote to the user and ask if they want to purchase."
    human_review: true
    review_prompt: "Quote review: premium {premium}, info {collected_data}"
    stream: true

  - name: confirm_purchase
    executor: code
    action: create_policy

  - name: done
    executor: code
    action: log_conversation

  - name: error_recovery
    executor: llm
    prompt: "Explain the calculation error to the user and re-collect info."

transitions:
  - from: start
    to: collect_info

  - from: collect_info
    to: calculate
    guard: "age >= 18 and driving_years > 0"

  - from: collect_info
    to: collect_info        # self-loop: LLM detects incomplete info, asks again
    guard: "context_incomplete"

  - from: calculate
    to: present_quote
    guard: "exit_guard_pass AND premium <= 10000"

  - from: calculate
    to: high_premium_review
    guard: "exit_guard_blocked"             # premium >= 10000 triggers this branch

  - from: high_premium_review
    to: present_quote
    guard: "manual_review_approved"

  - from: present_quote
    to: confirm_purchase
    guard: "user_says_yes"

  - from: present_quote
    to: error_recovery

  - from: confirm_purchase
    to: done
```

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
| **entry_guard** | At entry | Runtime rejection; routes to fallback or error state | Runtime safety gate |
| **data_invariant** | Throughout state lifetime | Runtime AssertionError; interrupts workflow | Runtime data integrity protection |
| **exit_guard** | At exit | Runtime block; routes to alternate branch | Branch routing based on computed result |
| **postcondition** | After exit | Does not block runtime; verification tool reports violation | Ensures action function output contract |

> **Note on static verification:** The "static analysis" and "verification tool" referenced above refers to a planned YAML linter and test generator (design TBD) that reads preconditions, postconditions, and invariants to catch contract violations before deployment. This tooling is out of scope for the current design document; see Appendix C.7 for related open questions.

### 3.2 Concrete Example: calculate State

```yaml
- name: calculate
  executor: code
  action: compute_premium

  # Before entry: 4 fields complete, age valid. Violation = static analysis error
  precondition: "collected_data.name != null AND age >= 18 AND car_model != null AND driving_years != null"

  # Door check. Failure -> reject entry, route to error_recovery
  entry_guard: "collected_data.age >= 18"

  # While alive: premium must not go negative. Violation -> immediate assertion error
  data_invariant: "premium >= 0"

  # On exit: premium over 10000 blocked from direct user presentation, routed to manual review
  exit_guard: "premium < 10000"

  # After exit: premium field exists and is positive
  postcondition: "state.premium != null AND state.premium > 0"
```

**Runtime trace:**

```
collect_info ---> calculate

  Entering calculate:
    1. Check precondition (static, already passed)
    2. Execute entry_guard: age >= 18  -> passed
    3. Execute action: compute_premium() -> premium = 8500
    4. During execution, data_invariant: premium >= 0 -> passed
    5. On exit, exit_guard: premium < 10000 -> passed (8500 < 10000)
    6. Check postcondition: premium > 0 -> passed
    -> Enter present_quote

  Alternative path:
    3. compute_premium() -> premium = 12000
    5. exit_guard: premium < 10000 -> FAILED
    -> Blocked from present_quote, routed to high_premium_review instead
```

### 3.3 Guard vs Contract

```
                      Guard                          Contract
                      (entry_guard / exit_guard)     (precondition / postcondition)

  Timing              Runtime                         Offline (static analysis / test generation)
  Failure behavior    Routes to fallback / error       Marks as "contract violation", does not block execution
  Typical use         "age < 18 -> direct reject"      "This state declares it needs age; generate test with age<18"
  Expression req.     Must be runtime-evaluable        Can be descriptive comment or formal formula
```

### 3.4 Complete State Field Reference

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
    on_exit:          "callback function run after state completes"
    on_error:         <fallback_state>       # state to enter on unhandled error
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

### 3.5 Guard Expression Syntax

Guard expressions support:
- **State field access:** `field_name`, `schema.field_name` (e.g., `amount`, `collected_data.age`)
- **Boolean operators:** `AND`, `OR`, `NOT`, `and`, `or`, `not`
- **Comparison operators:** `==`, `!=`, `>`, `<`, `>=`, `<=`
- **List membership:** `field in [a, b, c]`, `field in ['a', 'b', 'c']`
- **Null checks:** `field != null`, `field == null`
- **Meta-variables:** framework-generated flags listed in §3.4
- **Natural language prose:** allowed as fallback when the condition cannot be mechanically evaluated (treated as "not verifiable by static analysis, always raises a warning")

Full formal grammar is deferred to implementation planning (see Appendix C.2).

---

## 4. Auto-Generated LangGraph Graph

From the YAML above, the following LangGraph StateGraph is generated automatically:

```
                    +------------------+
                    |    start (code)   |
                    |   reset_context   |
                    +--------+---------+
                             |
                    +--------v---------+
                    | collect_info(llm)|<------+
                    |  prompt + tools   |       | guard: context_incomplete
                    |  + stream         |       |
                    |  + checkpoint     |-------+
                    +--------+---------+
                             | guard: age>=18 AND driving>0
                    +--------v---------+
                    | calculate (code)  |
                    |  compute_premium  |
                    |  on_error --------+----------+
                    +--------+---------+          |
                             |                    |
                    +--------v---------+   +------v----------+
                    | present_quote    |   | error_recovery  |
                    |   (llm)          |   |    (llm)        |
                    |   + human_review |   +------+----------+
                    |   + stream       |          |
                    |   + checkpoint   |          |
                    +---+--------+-----+          |
                        |        |                |
              user_yes  |        | anything_else  |
                        |        +----------------+
               +--------v---------+
               | confirm_purchase |
               |   (code)         |
               |   create_policy  |
               +--------+---------+
                        |
               +--------v---------+
               |   done (code)    |
               | log_conversation |
               +------------------+
```

**Each state -> one LangGraph node. Executor determines node behavior:**

| executor | LangGraph Node Behavior |
|----------|------------------------|
| `llm` | Auto-inject chat history -> call LLM -> stream output -> checkpoint |
| `code` | Execute deterministic action function; inputs/outputs are auditable |

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

## 6. End-to-End Conversation Example (Insurance Quote)

### User Dialogue Flow

```
User:   "I want a quote for my Model Y"

-- collect_info -------------------------------------------------
  [LLM -> stream]
  "Great! Please provide your name, age, and driving experience."

User:   "Zhang San, 28 years old, 5 years driving"

  [LLM + tool call]
  Internal: lookup_car_price("Model Y") -> 250,000 CNY
  [collect_info self-loop] "Also need to confirm: any claims in the past 3 years?"

User:   "No claims"

  [guard passed: age=28>=18, driving=5>0]
  -> Enter calculate

-- calculate ----------------------------------------------------
  [code] compute_premium(age=28, price=250000, years=5) -> premium = 4,200 CNY

  -> Enter present_quote

-- present_quote ------------------------------------------------
  [LLM generate] "Your Model Y premium is 4,200 CNY/year. Confirm purchase?"

  *** trigger interrupt(): paused, awaiting human approval ***
  --- audit log: 2026-06-16 14:30:22 | present_quote | waiting_human ---

  Reviewer confirms quote, clicks [Approve]

  --- audit log: 2026-06-16 14:31:05 | present_quote | approved_by: operator_003 ---
  Streaming resumes...

User:   "Yes, purchase"

-- confirm_purchase ---------------------------------------------
  [code] create_policy() -> policy ID: POL-2026-00001
  "Purchase confirmed! Policy ID: POL-2026-00001"

  -> done -> log_conversation()
```

### Audit Log (Auto-Generated)

```json
[
  {"ts": "14:30:00", "state": "collect_info",    "action": "llm_query",  "tokens": 150},
  {"ts": "14:30:10", "state": "collect_info",    "action": "tool_call",  "tool": "lookup_car_price", "args": {"model":"Model Y"}, "result": 250000},
  {"ts": "14:30:15", "state": "collect_info",    "action": "transition", "from": "collect_info", "to": "calculate", "guard": "age>=18", "result": "passed"},
  {"ts": "14:30:20", "state": "calculate",        "action": "exec",      "fn": "compute_premium", "args": {"age":28,"price":250000,"years":5}, "result": 4200},
  {"ts": "14:30:22", "state": "present_quote",    "action": "interrupt", "reason": "human_review"},
  {"ts": "14:31:05", "state": "present_quote",    "action": "approved",  "approver": "operator_003"},
  {"ts": "14:31:10", "state": "present_quote",    "action": "transition","from": "present_quote", "to": "confirm_purchase"},
  {"ts": "14:31:10", "state": "confirm_purchase", "action": "exec",      "fn": "create_policy", "result": "POL-2026-00001"},
  {"ts": "14:31:10", "state": "done",             "action": "complete"}
]
```

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
│ Classification   │ → intent: make_payment, confidence: 0.92
└────────┬────────┘
         ▼
┌─────────────────┐
│ Layer 2: Check   │
│ intent vs state  │
│                  │
│ state=filling_form
│ intent_policy:   │
│   accept:        │
│     - provide_information
│     - ask_question
│     - decline
│   on_unlisted: ask_confirm
│                  │
│ make_payment ∉ accept
└────────┬────────┘
         ▼
┌─────────────────┐
│ ask_confirm:     │
│ "You're filling  │
│  a quote form.   │
│  Cancel and pay?"│
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
  → idle   filling_form
  intent    (re-classify
  → make_   next input)
  payment
```

### 8.4 Examples

**Example 1: Allowed transition**
```
state: filling_form, intent: decline
→ accept list includes decline → transition to idle
→ follow-up: "What would you like to do instead?"
```

**Example 2: Unlisted — ask confirm**
```
state: filling_form, intent: make_payment
→ make_payment not in accept list, on_unlisted = ask_confirm
→ agent: "You're filling a quote form. Cancel and start a payment instead?"
→ user confirms → state → idle, intent → make_payment
→ user declines → stay in filling_form, re-process next input
```

**Example 3: Invalid combo — reject**
```
state: confirm_purchase, intent: ask_question
→ accept list: [confirm, decline], on_unlisted = reject
→ agent: "Please confirm or decline the purchase first."
→ stay in confirm_purchase
```

### 8.5 Relationship to Other State Machine Concerns

- **Retry counters** are independent of intent resolution. A user who triggers `ask_confirm` does not consume a retry attempt — only invalid data inputs (wrong name, wrong code) increment retries.
- **Sensitive field scrubbing** happens on state exit regardless of whether the exit was triggered by a normal transition, a `decline`, or a confirmed intent switch.

---

## Appendix A: Invoice Processing — Complete Use Case

### A.1 Overview

Enterprise finance staff submit supplier invoices via chatbot. The system automatically extracts, validates, approves, and records them. The entire process is auditable; transition rules are statically verifiable.

### A.2 State Machine Definition (YAML)

```yaml
workflow: invoice_processing
version: "1.0"

states:
  # ============================================================
  # Stage 1: Upload & Extraction
  # ============================================================
  - name: receive_invoice
    executor: llm
    prompt: |
      You are an invoice processing assistant. Identify invoice information
      from the user's message. If the user uploaded an image/PDF, call the
      extract_invoice tool.
    stream: true
    tool_allowlist: ["extract_invoice"]
    context_schema:
      attachment_url: str | null
      raw_invoice_data: dict | null

  - name: extract_fields
    executor: llm
    prompt: |
      Extract structured fields from raw invoice data. Output must strictly
      match output_schema. Extract amount as numeric only, no currency symbols.
      Set missing fields to null.
    input_schema:
      raw_invoice_data: dict                    # OCR result from previous state
    context_schema:
      extracted: dict                           # working memory during extraction
    output_schema:
      vendor_name: str | null
      invoice_number: str | null
      invoice_date: date | null
      amount: float | null
      currency: str | null
      line_items: list | null
      due_date: date | null
    postcondition: "if extracted.amount is non-null then it must be > 0"

  # ============================================================
  # Stage 2: Deterministic Validation (pure code, no LLM)
  # ============================================================
  - name: validate_invoice
    executor: code
    action: run_validations
    input_schema:
      vendor_name: str
      invoice_number: str
      invoice_date: date
      amount: float
      currency: str
      due_date: date
    precondition: "all 6 required fields in input_schema are non-null"
    entry_guard: "amount > 0 AND invoice_date <= today + 30d"
    data_invariant: "validation_errors only appends, never deletes existing errors"
    context_schema:
      validation_errors: list
      validation_passed: bool
      vendor_details: dict
    output_schema:
      validation_passed: bool
      validation_errors: list
      vendor_details: dict
    postcondition: |
      validation_passed == (len(validation_errors) == 0)
    on_error: reject_invoice
    # Internal steps (deterministic):
    #   1. check_required_fields -> missing_fields -> write validation_errors
    #   2. check_duplicate(invoice_number) -> duplicate_detected -> write validation_errors
    #   3. check_vendor_approved(vendor_name) -> unapproved -> write validation_errors
    #   4. check_amount_vs_threshold(amount) -> amount_alert -> write validation_errors
    #   5. Summarize: validation_passed = (len(validation_errors) == 0)

  - name: reject_invoice
    executor: llm
    prompt: |
      Invoice validation failed. List the following errors and explain how to resolve them:
      {validation_errors}
    stream: true
    context_schema:
      rejection_reason: str
    output_schema:
      needs_resubmit: bool

  # ============================================================
  # Stage 3: Approval Routing (code — pure deterministic routing)
  # ============================================================
  - name: route_approval
    executor: code
    action: determine_approval_route
    input_schema:
      amount: float
      vendor_details: dict
    precondition: "amount > 0"
    context_schema:
      approval_route: str                      # "auto" | "manager" | "director" | "cfo"
      required_approvers: list                 # ["manager"] | ["manager", "cfo"]
    exit_guard: "approval_route in ['auto', 'manager', 'director', 'cfo']"
    postcondition: "required_approvers is non-empty"
    # Routing logic (deterministic):
    #   amount < 500        -> approval_route = "auto"
    #   500 <= amount < 5000  -> approval_route = "manager"
    #   5000 <= amount < 50000 -> approval_route = "director"
    #   amount >= 50000     -> approval_route = "cfo"

  # ============================================================
  # Stage 4: Human Approval (interrupt)
  # ============================================================
  - name: await_approval
    executor: llm
    prompt: "Invoice submitted for approval. Please wait for the result."
    human_review: true
    review_prompt: |
      Invoice Approval
      Vendor: {vendor_name}
      Amount: {amount} {currency}
      Invoice #: {invoice_number}
      Approvers: {required_approvers}
    stream: false
    input_schema:
      vendor_name: str
      amount: float
      currency: str
      invoice_number: str
      required_approvers: list
    context_schema:
      approvals_received: list                 # [{name, status, timestamp, comment}]
    exit_guard: |
      all required_approvers have approved
      AND no approval in approvals_received has status="rejected"
    postcondition: |
      all required_approvers completed AND all status="approved"

  - name: rejected_by_approver
    executor: llm
    prompt: |
      Invoice rejected by approver. Reason: {rejection_comment}
      Inform user and explain next steps.
    stream: true
    output_schema:
      closed: bool                             # true = workflow ends

  # ============================================================
  # Stage 5: ERP Recording (code — irreversible operation)
  # ============================================================
  - name: record_in_erp
    executor: code
    action: create_erp_entry
    input_schema:
      vendor_name: str
      invoice_number: str
      invoice_date: date
      amount: float
      currency: str
      line_items: list
      due_date: date
      approvers: list
    precondition: "all fields in input_schema are non-null"
    entry_guard: "all approvers have approved"
    data_invariant: "erp_entry_id is null before ERP API call, immutable after"
    context_schema:
      erp_entry_id: str | null
      erp_response: dict
    exit_guard: "erp_entry_id != null AND erp_response.status == 'created'"
    postcondition: "erp_entry_id is persisted in ERP"
    on_error: compensation_handler

  - name: compensation_handler
    executor: llm
    prompt: |
      ERP recording failed. Issue submitted to IT support ticket.
      Ticket #: {ticket_id}
    # Compensation: if ERP write partially fails, ERP rollback or manual ticket escalation
    # are triggered externally by the LLM node (via tool call)

  # ============================================================
  # Stage 6: Archive
  # ============================================================
  - name: archive_and_notify
    executor: llm
    prompt: |
      Invoice processing complete. Notify user:
      Invoice #: {invoice_number}, Amount: {amount} {currency}, ERP Entry: {erp_entry_id}
    stream: true
    output_schema:
      notification_sent: bool

  # Terminal state
  - name: invoice_closed
    description: "Invoice processing complete; workflow ended"

transitions:
  # Upload -> Extract
  - from: receive_invoice
    to: extract_fields
    guard: "raw_invoice_data != null"

  - from: receive_invoice
    to: receive_invoice
    guard: "raw_invoice_data == null"          # not yet uploaded, keep asking

  # Extract -> Validate
  - from: extract_fields
    to: validate_invoice
    guard: |
      vendor_name != null AND invoice_number != null
      AND invoice_date != null AND amount != null

  - from: extract_fields
    to: extract_fields
    guard: "any_field_missing"                  # LLM extraction incomplete, retry

  - from: extract_fields
    to: reject_invoice
    guard: "extract_retries_exceeded"           # 3 retries exhausted

  # Validate -> Route or Reject
  - from: validate_invoice
    to: route_approval
    guard: "validation_passed == true"

  - from: validate_invoice
    to: reject_invoice
    guard: "validation_passed == false"

  # Reject -> Retry or End
  - from: reject_invoice
    to: receive_invoice
    guard: "user_wants_retry"

  - from: reject_invoice
    to: invoice_closed

  # Route -> Human Approval or Auto-pass
  - from: route_approval
    to: await_approval
    guard: "approval_route in ['manager', 'director', 'cfo']"

  - from: route_approval
    to: record_in_erp
    guard: "approval_route == 'auto'"          # <500 auto-pass

  # Approval -> Record or Reject
  - from: await_approval
    to: record_in_erp
    guard: "all_approved"

  - from: await_approval
    to: rejected_by_approver
    guard: "any_rejected"

  - from: rejected_by_approver
    to: invoice_closed

  # Record -> Archive
  - from: record_in_erp
    to: archive_and_notify

  - from: record_in_erp
    to: compensation_handler
    guard: "erp_failure"

  - from: compensation_handler
    to: invoice_closed

  - from: archive_and_notify
    to: invoice_closed
```

### A.3 State Diagram

```
                        +----------+
                        | receive   |
                        | _invoice  |<--------+ user retry
                        |  (llm)    |          |
                        +-----+-----+          |
                              |                |
                        +-----v-----+   +------+-------+
                        | extract   |<--+ reject        |
                        | _fields   |   | _invoice (llm)|
                        |  (llm)    |   +------+-------+
                        +-----+-----+          |
                              |                |
                        +-----v-----+          |
                        | validate  |----------+ failed
                        | _invoice  |          |
                        |  (code)   |          |
                        +-----+-----+          |
                              | passed         |
                        +-----v-----+          |
                        | route     |          |
                        | _approval |          |
                        |  (code)   |          |
                        +--+----+---+          |
                           |    |              |
              amount<500   |    | amount>=500  |
                           |    |              |
                  +--------v-+ +v----------+   |
                  |  record   | | await     |  |
                  |  _in_erp  | | _approval |  |
                  |  (code)   | | (llm+HI)  |  |
                  +----+-----+ +--+----+---+   |
                       |          |    |       |
                       |   approve|    |reject |
                       |          |    |       |
                       |  +-------+    |       |
                       |  |     +------v---+   |
                       |  |     | rejected  |  |
                       |  |     | _by_admin |  |
                       |  |     |  (llm)   |  |
                       |  |     +----------+   |
                       |  |                    |
                  +----v--v----+               |
                  | archive    |               |
                  | _and_notify|               |
                  |  (llm)    |               |
                  +-----+-----+               |
                        |                     |
                  +-----v--+            +-----v--+
                  | invoice|            | invoice|
                  | _closed|            | _closed|
                  +--------+            +--------+
```

### A.4 End-to-End Example

```
User uploads: "Please process this invoice" [attached PDF: INV-2026-0042.pdf]

-- receive_invoice ----------------------------------------------
  [LLM -> tool call: extract_invoice(pdf)]
  Returns: raw_invoice_data = {
    vendor: "CloudSuite GmbH",
    inv_no: "INV-2026-0042",
    date: "2026-06-10",
    amount: "EUR 4,200",
    due: "2026-07-10"
  }

-- extract_fields -----------------------------------------------
  [LLM] Structured extraction:
  extracted = {
    vendor_name: "CloudSuite GmbH",
    invoice_number: "INV-2026-0042",
    invoice_date: "2026-06-10",
    amount: 4200.00,
    currency: "EUR",
    line_items: [{"desc": "Cloud Infrastructure Q2", "amount": 4200.00}],
    due_date: "2026-07-10"
  }
  -> All 6 required fields non-null -> enter validate

-- validate_invoice ---------------------------------------------
  [code] Executing run_validations:
    Step 1: check_required_fields -> ok
    Step 2: check_duplicate("INV-2026-0042") -> ok (no duplicate)
    Step 3: check_vendor_approved("CloudSuite GmbH") -> ok (in allowlist)
    Step 4: check_amount_vs_threshold(4200) -> ok (normal range)
  validation_passed: true
  vendor_details: {id: "V-088", category: "IT", approved_since: "2024-01"}

-- route_approval -----------------------------------------------
  [code] amount=4200, 500 <= 4200 < 5000
  -> approval_route = "manager"
  -> required_approvers = ["dept_manager"]

-- await_approval -----------------------------------------------
  *** trigger interrupt(): paused, entered human approval queue ***
  Approver sees:
    Vendor: CloudSuite GmbH
    Amount: EUR 4,200.00
    Invoice #: INV-2026-0042
    Approver: dept_manager
  Approver reviews -> [Approve]

  approvals_received: [{name: "mueller", status: "approved", ts: "...", comment: "Q2 budget ok"}]
  exit_guard: all_approved -> passed

-- record_in_erp ------------------------------------------------
  [code] Call ERP API:
    POST /api/v1/payables
    -> erp_entry_id: "ERP-2026-08842"
    -> erp_response: {status: "created", entry_id: "ERP-2026-08842"}
  exit_guard: erp_entry_id != null -> passed

-- archive_and_notify -------------------------------------------
  [LLM -> stream] "Invoice INV-2026-0042 processed successfully.
  Vendor CloudSuite GmbH, Amount EUR 4,200.00,
  Recorded as ERP-2026-08842."

-- invoice_closed ------------------------------------------------
```

### A.5 Audit Log

```json
[
  {"ts":"09:00:00","state":"receive_invoice",    "action":"llm_tool_call","tool":"extract_invoice","input":"INV-2026-0042.pdf","output":"{vendor:CloudSuite...}"},
  {"ts":"09:00:05","state":"extract_fields",      "action":"llm_extract",  "input":"{raw_invoice_data}","output":"{vendor_name,amount:4200,...}"},
  {"ts":"09:00:05","state":"extract_fields",      "action":"transition",   "from":"extract_fields","to":"validate_invoice","guard":"all_required_present","result":"passed"},
  {"ts":"09:00:05","state":"validate_invoice",    "action":"code_exec",    "fn":"run_validations","steps":[{"step":"check_duplicate","result":"ok"},{"step":"check_vendor","result":"ok"}],"result":{"validation_passed":true}},
  {"ts":"09:00:05","state":"validate_invoice",    "action":"transition",   "from":"validate_invoice","to":"route_approval","guard":"validation_passed","result":"passed"},
  {"ts":"09:00:05","state":"route_approval",      "action":"code_exec",    "fn":"determine_approval_route","input":{"amount":4200},"result":{"route":"manager","approvers":["dept_manager"]}},
  {"ts":"09:00:05","state":"await_approval",      "action":"interrupt",    "reason":"human_review","context":{"vendor":"CloudSuite","amount":4200}},
  {"ts":"09:15:22","state":"await_approval",      "action":"human_approve","approver":"mueller","comment":"Q2 budget ok"},
  {"ts":"09:15:22","state":"await_approval",      "action":"transition",   "from":"await_approval","to":"record_in_erp","guard":"all_approved","result":"passed"},
  {"ts":"09:15:23","state":"record_in_erp",       "action":"code_exec",    "fn":"create_erp_entry","input":{"vendor":"CloudSuite","amount":4200},"result":{"erp_entry_id":"ERP-2026-08842"}},
  {"ts":"09:15:23","state":"record_in_erp",       "action":"transition",   "from":"record_in_erp","to":"archive_and_notify"},
  {"ts":"09:15:24","state":"archive_and_notify",  "action":"llm_generate", "tokens":45},
  {"ts":"09:15:24","state":"archive_and_notify",  "action":"transition",   "from":"archive_and_notify","to":"invoice_closed"},
  {"ts":"09:15:24","state":"invoice_closed",      "action":"complete"}
]
```

### A.6 Static Verification Points

The invoice workflow YAML can be checked by static analysis:

| Check | Result |
|-------|--------|
| Dead states (no transitions reachable) | None |
| Unreachable states | None |
| Missing transitions | `archive_and_notify` must reach a terminal state -> has `invoice_closed` |
| Guard conflicts | `route_approval` exit_guard and `await_approval` auto guard are mutually exclusive |
| input_schema closure | `validate_invoice.input_schema` 6 fields all present in `extract_fields.output_schema` |
| postcondition satisfiability | `record_in_erp` postcondition satisfiable on normal path, error path uses compensation |

---

## Appendix B: Payment Collection — Complete Use Case

### B.1 Overview

Enterprise initiates automated collection for overdue customers. The system negotiates repayment with the customer, collects payment method, and calls the payment gateway to charge. Money movement is irreversible; every state transition must be auditable.

**Differences from Invoice:**
- Invoice is one-way submission+approval; Payment is two-way negotiation (customer can counter-offer)
- Payment involves real money movement; failures cannot be ignored (decline/refund/partial payment)
- Payment requires gateway integration; the state machine must synchronize with external system states

### B.2 State Machine Definition (YAML)

```yaml
workflow: payment_collection
version: "1.0"

states:
  # ============================================================
  # Stage 1: Outreach & Negotiation
  # ============================================================
  - name: notify_debtor
    executor: llm
    prompt: |
      You are a payment collection assistant. Notify the customer of overdue amounts:
      Total due: {total_due}
      Days overdue: {days_overdue}
      Minimum payment: {min_amount}
      Ask how they would like to pay (full/partial/installment/dispute).
    stream: true
    context_schema:
      contact_method: str                       # sms / email / whatsapp
      contact_delivered: bool
      total_due: float
      days_overdue: int
      min_amount: float
    output_schema:
      contact_delivered: bool

  - name: negotiate
    executor: llm
    prompt: |
      The customer may express one of the following intents:
      - Pay in full
      - Partial payment (amount X)
      - Installment plan (N installments, amount M each)
      - Dispute (believes amount is wrong or already paid)
      Confirm the customer's intent and extract specific values.
    stream: true
    tool_allowlist: ["lookup_account_history"]
    input_schema:
      total_due: float
      min_amount: float
    context_schema:
      intent: str                               # "pay_full" | "pay_partial" | "pay_plan" | "dispute"
      offered_amount: float | null
      plan_instalments: int | null
      plan_amount_per: float | null
    output_schema:
      intent: str
      offered_amount: float | null
      plan_instalments: int | null
      plan_amount_per: float | null
    exit_guard: "intent in ['pay_full', 'pay_partial', 'pay_plan', 'dispute']"

  # ============================================================
  # Stage 2: Intent Routing (code — pure deterministic routing)
  # ============================================================
  - name: route_by_intent
    executor: code
    action: decide_payment_path
    input_schema:
      intent: str
      offered_amount: float | null
      total_due: float
      min_amount: float
    precondition: "intent in ['pay_full', 'pay_partial', 'pay_plan', 'dispute']"
    context_schema:
      selected_path: str                        # "full" | "partial" | "plan" | "dispute"
      final_amount: float
      requires_collection: bool                 # true = need to collect payment method
    exit_guard: "selected_path != null AND (selected_path == 'dispute' OR final_amount > 0)"
    postcondition: "requires_collection is set"
    # Routing logic (deterministic):
    #   intent=pay_full       -> final_amount=total_due,      requires_collection=true
    #   intent=pay_partial    -> final_amount=offered_amount,  requires_collection=true
    #   intent=pay_plan       -> final_amount=plan_amount_per, requires_collection=true
    #   intent=dispute        -> final_amount=0,               requires_collection=false

  # ============================================================
  # Stage 3: Collect Payment Method (llm — sensitive information)
  # ============================================================
  # NOTE: Payment method collection involves PII (bank account, card numbers).
  #       PII tokenization, encryption, and storage strategies will be addressed
  #       in a dedicated PII handling design document.
  #       Here we only note "processed via tokenize_card tool", no implementation detail.
  - name: collect_payment_method
    executor: llm
    prompt: |
      Ask the customer to provide payment method:
      - Credit/debit card
      - Bank account
      Do not store plaintext card numbers. Use the tokenize_card tool.
    stream: true
    tool_allowlist: ["tokenize_card", "validate_bank_account"]
    context_schema:
      payment_token: str | null                 # tokenized, never plaintext
      payment_type: str                         # "card" | "bank_transfer"
      last_four: str                            # only store last 4 digits
    output_schema:
      payment_token: str
      payment_type: str
      last_four: str
    data_invariant: |
      payment_token immutable once set
      AND plaintext card numbers never stored (handled by tokenize_card tool)

  # ============================================================
  # Stage 4: Payment Validation (code — deterministic, no LLM near money)
  # ============================================================
  - name: validate_payment
    executor: code
    action: pre_payment_checks
    input_schema:
      payment_token: str
      final_amount: float
      total_due: float
    precondition: "payment_token != null AND final_amount > 0"
    entry_guard: "final_amount >= min_amount"
    data_invariant: "all check results are append-only, never overwritten"
    context_schema:
      checks: list                               # [{check_name, passed, detail}]
      all_checks_passed: bool
    output_schema:
      all_checks_passed: bool
      checks: list
    # Validation steps (deterministic):
    #   1. validate_token_valid(payment_token) -> true/false
    #   2. check_amount_vs_min(final_amount, min_amount) -> true/false
    #   3. check_amount_vs_max(final_amount, total_due) -> true/false (cannot charge more than owed)
    #   4. check_duplicate_payment(payment_token, total_due) -> true/false
    #   5. fraud_check(payment_token, final_amount) -> true/false
    exit_guard: "all_checks_passed == true"
    on_error: payment_failed

  # ============================================================
  # Stage 5: Execute Charge (code — irreversible operation)
  # ============================================================
  - name: process_payment
    executor: code
    action: execute_charge
    input_schema:
      payment_token: str
      final_amount: float
    precondition: "payment_token != null AND final_amount > 0"
    entry_guard: "all_checks_passed == true"
    data_invariant: "charge executes exactly once (idempotency_key dedup)"
    context_schema:
      idempotency_key: str
      charge_id: str | null
      charge_status: str | null                  # "succeeded" | "declined" | "error"
      gateway_response: dict
    exit_guard: "charge_id != null"              # must receive gateway response
    postcondition: |
      charge_id is persisted
      AND charge_status is non-null
    on_error: payment_failed
    # Critical: gateway call includes idempotency_key to prevent duplicate charges

  # ============================================================
  # Stage 6: Payment Result Handling
  # ============================================================
  - name: confirm_payment
    executor: llm
    prompt: |
      Charge successful. Amount: {final_amount}.
      Inform customer and provide receipt.
    stream: true
    input_schema:
      final_amount: float
      charge_id: str
      last_four: str
    context_schema:
      receipt_sent: bool
    output_schema:
      receipt_sent: bool

  - name: payment_failed
    executor: llm
    prompt: |
      Payment failed. Reason: {charge_status}. Checks: {checks}
      Ask customer whether to:
      - Retry (same payment method)
      - Change payment method
      - Give up
    stream: true
    context_schema:
      failure_reason: str
      user_choice: str                           # "retry" | "change_method" | "give_up"
    output_schema:
      user_choice: str
    exit_guard: "user_choice in ['retry', 'change_method', 'give_up']"

  # ============================================================
  # Stage 7: Installment Plan Setup (code)
  # ============================================================
  - name: setup_payment_plan
    executor: code
    action: schedule_recurring_payments
    input_schema:
      payment_token: str
      plan_instalments: int
      plan_amount_per: float
    precondition: "plan_instalments > 0 AND plan_amount_per > 0"
    context_schema:
      plan_id: str
      next_charge_date: date
    exit_guard: "plan_id != null"
    postcondition: "plan_id created AND next_charge_date = today + 30d"

  # ============================================================
  # Stage 8: Dispute Handling
  # ============================================================
  - name: handle_dispute
    executor: llm
    prompt: |
      Customer disputes the debt. Collect dispute details and inform them
      it will be escalated to human support. Call create_support_ticket.
    stream: true
    human_review: true
    review_prompt: |
      Dispute Ticket — Customer: {customer_id}, Amount: {total_due},
      Dispute: {dispute_detail}
    tool_allowlist: ["create_support_ticket", "lookup_payment_history"]
    context_schema:
      dispute_detail: str
      ticket_id: str | null
    output_schema:
      ticket_id: str

  # Terminal states
  - name: closed_paid
    description: "Collection complete, debt cleared"
  - name: closed_unpaid
    description: "Collection incomplete (user gave up / unrecoverable error)"

transitions:
  # Outreach -> Negotiate
  - from: notify_debtor
    to: negotiate
    guard: "contact_delivered == true"

  - from: notify_debtor
    to: closed_unpaid
    guard: "contact_delivered == false AND retries_exhausted"

  # Negotiate -> Route
  - from: negotiate
    to: route_by_intent
    guard: "intent != null"

  - from: negotiate
    to: negotiate
    guard: "intent == null"                     # not yet clear, keep asking

  # Route -> Branch
  - from: route_by_intent
    to: collect_payment_method
    guard: "requires_collection == true"

  - from: route_by_intent
    to: handle_dispute
    guard: "selected_path == 'dispute'"

  # Collect -> Validate
  - from: collect_payment_method
    to: validate_payment
    guard: "payment_token != null"

  - from: collect_payment_method
    to: collect_payment_method
    guard: "payment_token == null"

  # Validate -> Charge
  - from: validate_payment
    to: process_payment
    guard: "all_checks_passed == true"

  - from: validate_payment
    to: payment_failed
    guard: "all_checks_passed == false"

  # Charge -> Success or Fail
  - from: process_payment
    to: confirm_payment
    guard: "charge_status == 'succeeded'"

  - from: process_payment
    to: payment_failed
    guard: "charge_status in ['declined', 'error']"

  # Confirm -> Done
  - from: confirm_payment
    to: closed_paid

  # Payment Failed -> Retry / Change Method / Give Up
  - from: payment_failed
    to: process_payment
    guard: "user_choice == 'retry'"

  - from: payment_failed
    to: collect_payment_method
    guard: "user_choice == 'change_method'"

  - from: payment_failed
    to: closed_unpaid
    guard: "user_choice == 'give_up'"

  # Installment setup (special path: charge first installment immediately)
  - from: route_by_intent
    to: setup_payment_plan
    guard: "selected_path == 'plan'"

  - from: setup_payment_plan
    to: process_payment
    guard: "plan_id != null"                    # charge first installment now

  # Dispute -> End
  - from: handle_dispute
    to: closed_unpaid
```

### B.3 State Diagram

```
                         +--------------+
                         | notify       |
                         | _debtor (llm)|----------+ unreachable
                         +------+-------+          |
                                |                  |
                         +------v-------+          |
                         | negotiate    |<--+       |
                         |   (llm)      |   | loop  |
                         +------+-------+---+       |
                                | intent ok        |
                         +------v-------+          |
                         | route_by     |          |
                         | _intent(code)|          |
                         +-+---+---+----+          |
                           |   |   |               |
          pay_full/partial |   |   | dispute       |
                           |   |   |               |
                +----------+   |   +-----------+   |
                |   pay_plan   |               |   |
                v              v               v   |
         +------------+ +-------------+  +-----------+
         | collect    | | setup_plan  |  | handle    |
         | _method    | |  (code)     |  | _dispute  |
         |  (llm)     | +------+------+  | (llm+HI)  |
         +------+-----+        |         +-----+-----+
                |              |               |
         +------v-----+        |               |
         | validate   |        |               |
         | _payment   |<---+   |               |
         |  (code)    |    |   |               |
         +--+----+----+    |   |               |
            |    |         |   |               |
     passed |    | failed  |   |               |
            |    |         |   |               |
     +------v-+  | +-------v+  |               |
     |process |  | |payment |  |               |
     |_payment|  | |_failed |  |               |
     | (code) |  | | (llm)  |  |               |
     +--+--+--+  | +--+-+---+  |               |
        |  |     |    | |      |               |
   ok   |  |fail |retry| |change|               |
        |  |     |    | |method|               |
        |  +-----+----+ |  |    |               |
        |        |      |  |    |               |
        |        +------+--+    |               |
        |               |       |               |
 +------v-----+         |       |               |
 | confirm    |  +------+       |               |
 | _payment   |  | give_up      |               |
 |  (llm)     |  v              |               |
 +------+-----+ +--------------+ |              |
        |       | closed_unpaid| |              |
        v       +--------------+ |              |
 +-----------+                   |              |
 | closed    |                   |              |
 | _paid     |                   |              |
 +-----------+                   |              |
                    +------------+--+  +--------+--+
                    | closed_unpaid |  |closed_unpaid|
                    +---------------+  +------------+
```

### B.4 End-to-End Example (Partial Payment Path)

```
Customer: receives SMS reminder -> opens conversation

-- notify_debtor ------------------------------------------------
  [LLM -> stream]
  "Hello, your account has an overdue balance of CNY 8,500.00 (45 days overdue).
   Minimum payment is CNY 1,000.00. How would you like to pay?"

Customer: "I'm short on cash right now, can I pay 3,000 first?"

-- negotiate ----------------------------------------------------
  [LLM + tool: lookup_account_history]
  -> Confirmed good payment history
  intent = "pay_partial"
  offered_amount = 3000

-- route_by_intent ----------------------------------------------
  [code] decide_payment_path:
    intent="pay_partial" -> selected_path="partial"
    final_amount=3000, requires_collection=true

-- collect_payment_method ---------------------------------------
  [LLM] "Sure, paying CNY 3,000.00 first. Please provide your card details."
  Customer: "Card 4532-xxxx-xxxx-1234"
  [LLM -> tool: tokenize_card("4532...1234")]
  -> payment_token = "tok_v0a1b2c3d4"
  -> payment_type = "card"
  -> last_four = "1234"

-- validate_payment ---------------------------------------------
  [code] pre_payment_checks:
    Step 1: validate_token_valid("tok_v0a1b2c3d4") -> passed
    Step 2: check_amount_vs_min(3000, 1000) -> passed    (3000 >= 1000)
    Step 3: check_amount_vs_max(3000, 8500) -> passed    (3000 <= 8500)
    Step 4: check_duplicate_payment -> passed
    Step 5: fraud_check("tok_v0a1b2c3d4", 3000) -> passed
  all_checks_passed: true

-- process_payment ----------------------------------------------
  [code] execute_charge:
    idempotency_key = "idem_pay_8842_20260616"
    POST /gateway/charges {token: "tok_v0a1b2c3d4", amount: 3000, key: "idem_..."}
    -> charge_id: "ch_a1b2c3d4e5"
    -> charge_status: "succeeded"
    -> gateway_response: {auth_code: "Z-8842", ...}
  postcondition: charge_id="ch_a1b2c3d4e5" passed

-- confirm_payment ----------------------------------------------
  [LLM -> stream]
  "Charge successful! CNY 3,000.00 collected (card ending in 1234).
   Remaining balance: CNY 5,500.00. Please pay within 30 days.
   Receipt: ch_a1b2c3d4e5"

-- closed_paid --------------------------------------------------
  -> Audit log written, ERP balance updated to CNY 5,500.00
```

### B.5 Payment-Specific Deterministic Requirements

| Scenario | Why Deterministic | How State Machine Enforces |
|----------|-------------------|---------------------------|
| **Duplicate charge** | Double charge = financial loss + regulatory fine | `idempotency_key` is enforced by `process_payment` data_invariant; non-reentrant |
| **Overcharge** | Charging more than owed | `validate_payment` check_amount_vs_max is a pure function; 3000 > total_due is impossible |
| **Card number leak** | PCI DSS compliance | `collect_payment_method` data_invariant prohibits plaintext; enforced via tokenize |
| **Dispute without evidence** | Customer claims "I paid" needs proof | `handle_dispute` tool_allowlist restricts to lookup_payment_history only |
| **Partial payment balance** | Total due 8500->5500 must be atomic | `confirm_payment` exit triggers deterministic ERP balance update (not on LLM path) |
| **Installment default** | First charge must succeed before plan creation | `setup_payment_plan -> process_payment` guard forces first charge |

---

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
| 9 | Implicit fallback (no-match) design: explicit catch-all vs framework-injected error handler | Compliance — system must not "freeze" |
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
| 14 | Global error workflow design — unified fallback target state for all uncaught exceptions | Compliance — state machine must not freeze or silently fail |

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
