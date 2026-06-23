# Three-Tier Agent Testing Methodology

**Version:** 0.2.2
**Scope:** Testing strategy for agents built on the three-layer deterministic workflow framework. Industry-agnostic. Applies to any domain (fintech, healthcare, legal, government).

---

## 1. Problem Statement

Testing LLM-powered agents is fundamentally different from testing traditional software. The agent has two kinds of components: deterministic code (Layer 2 decisions, Layer 3 responses) and non-deterministic LLM calls (Layer 1 classification and extraction). A test that passes today may fail tomorrow because the LLM classified a message differently. Conversely, a test that mocks the LLM perfectly may pass while the real LLM fails on the same input.

The three-tier methodology separates these concerns: test the code without the LLM, test the LLM without variable user input, then test both together.

## 2. The Three Tiers

```
┌──────────────────────────────────────────────────────────────┐
│ Tier 1: Logic Tests                                          │
│ Client: hardcoded strings   Server: MockGateway (keyword)    │
│ Verifies: code logic, state machine, database persistence    │
│ Runs: fast, deterministic, CI-safe, no API keys needed       │
├──────────────────────────────────────────────────────────────┤
│ Tier 2: LLM Accuracy Tests                                   │
│ Client: pre-written scripts  Server: real LLM                │
│ Verifies: LLM can correctly classify and extract from        │
│           realistic but controlled user messages             │
│ Runs: with API keys, measures intent accuracy per turn       │
├──────────────────────────────────────────────────────────────┤
│ Tier 3: Completion Tests                                     │
│ Client: LLM (persona)        Server: real LLM                │
│ Verifies: end-to-end conversation success rate, turn count,  │
│           loop detection, indirect multi-party communication  │
│ Runs: with API keys, stochastic (run N times for confidence) │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 Why Three Tiers?

A single tier is insufficient:

| If you only have... | You miss... |
|--------------------|------------|
| Tier 1 only | LLM may misclassify real user messages. All 65 tests pass but the agent fails in production. |
| Tier 2 only | The scripted client can't find unexpected edge cases. Coverage is limited to what humans pre-write. |
| Tier 3 only | Stochastic LLM variance makes it impossible to localize bugs. Is the test failing because of a code bug or an LLM fluke? |

Together, the three tiers isolate failures: Tier 1 tells you "is my code wrong?", Tier 2 tells you "can the LLM understand my users?", Tier 3 tells you "does the whole system work?"

### 2.2 Layer Coverage Matrix

The deterministic workflow framework has three layers. Each test tier covers different layers:

| Layer | What it does | Tier 1 | Tier 2 | Tier 3 |
|-------|-------------|--------|--------|--------|
| **Layer 1: NLU** | Intent classification + entity extraction (LLM) | Mocked | **Tested** | **Tested** |
| **Layer 2: Decide** | State machine routing + business logic (deterministic code) | **Tested** | **Tested** | **Tested** |
| **Layer 3: Respond** | Response generation + goal checker (deterministic code) | **Tested** | **Tested** | **Tested** |

**Per-tier layer focus:**

```
Tier 1: Tests Layer 2 + Layer 3 code correctness. Layer 1 is mocked.
        Question answered: "Given correct intent X and entities Y, does the code do the right thing?"

Tier 2: Tests Layer 1 LLM accuracy. Layer 2 + 3 run normally but are secondary.
        Question answered: "Given a real user message, can the LLM correctly classify it?"

Tier 3: Tests all three layers together under stochastic LLM behavior.
        Question answered: "Does the complete system work end-to-end, across multiple runs?"
```

**Why this separation matters:**

| Problem | Caught by | Example |
|---------|-----------|---------|
| Bug in `_calculate_monthly_payment` formula | Tier 1 | Test asserts payment = $1,896.20 for $300k @ 6.5% |
| LLM misclassifies "I wanna refi" as `ask_about_rates` instead of `provide_loan_info` | Tier 2 | Script expects intent=provide_loan_info with entities={loan_purpose: refinance} |
| LLM classifies correctly but stalls in a 10-turn loop asking the same question | Tier 3 | Loop detection fires: same intent 3+ turns with no state change |
| Code rejects a correctly-extracted entity | Tier 2 or 3 | LayerTrace shows LLM extracted `{home_value: 800000}` but `phase` didn't advance |

## 3. Tier 1: Logic Tests

### 3.1 Architecture

```
FixedScriptClient ──pre-written message──► Agent (MockGateway)
                    ◄──deterministic response──
```

Both sides are deterministic. The same input always produces the same output.

### 3.2 MockGateway

Replace the real LLM with a keyword-based classifier that returns pre-determined intents. The mock must:

- Return correct intents for every test message
- Return appropriate entities for entity-extraction tests
- Be deterministic — same message → same intent every run

**MockGateway template:**

```python
class MockGateway:
    """Drop-in replacement for the real LLM Gateway. Keyword-based, deterministic."""

    def _extract_message(self, prompt: str) -> str:
        """Extract just the user message from the classify prompt template."""
        marker = 'User message: "'
        if marker in prompt:
            start = prompt.index(marker) + len(marker)
            end = prompt.index('"', start)
            return prompt[start:end]
        return prompt

    def call(self, prompt: str, output_schema: type, temperature: float = 0):
        """
        Return a pre-determined intent based on keyword matching.
        Developer MUST replace the keyword rules with their own domain's intents.
        """
        msg = self._extract_message(prompt).lower()

        # --- REPLACE BELOW with your domain's intent keywords ---
        if "hello" in msg or "hi" in msg:
            return output_schema(intent="greet", confidence=1.0)
        if "help" in msg:
            return output_schema(intent="help", confidence=1.0)
        # ... add rules for each intent in your system ...

        # Default: extract entities or return ask_about_rates
        entities = {}
        # ... add entity extraction rules ...
        return output_schema(intent="provide_loan_info" if entities else "ask_about_rates",
                            confidence=1.0, entities=entities)
```

**Anti-patterns for MockGateway:**
- Don't use real API keys — MockGateway must never make network calls
- Don't make it too smart — keyword matching should be simple. Overly complex mocks hide LLM failures
- Don't return `confidence=1.0` for every call — include at least one test with `confidence=0.4` to exercise low-confidence paths

### 3.3 What to Test

**Happy paths:**
- Complete workflow from start to finish
- Every state transition fires correctly
- Every entity is written to the database

**Edge cases (举一反三):**
For each happy path test, write 2-3 variants by changing one dimension:
- Different values (amounts, states, credit scores)
- Different order of information provision
- Multiple fields provided in one message
- Corrections (wrong value → correct value)
- Diversions (ask unrelated question mid-flow → return)

**Error paths:**
- LLM returns low confidence
- LLM returns unrecognized intent
- Required entity missing
- No matching entities in database
- Database connection failure

**Domain model exhaustion:**
For every entity field in the domain model, verify:
- Is there a test where this field is missing?
- Is there a test where this field is wrong and corrected?
- Is there a test where this field is at its boundary?
- Is there a test where this field is provided alongside other fields?

### 3.4 Assertion Patterns

```python
# State machine assertions
assert result["phase"] == "completed"
assert state.collected_data.get("required_field") is not None

# Database assertions
assert session.query(LeadModel).filter_by(id=state.lead_id).count() == 1

# Response assertions
assert expected_text in result["response"].lower()

# Trace assertions (LayerTrace)
assert result["trace"].layer1_intent == "expected_intent"
assert result["trace"].layer2_phase_after == "expected_phase"
```

## 4. Tier 2: LLM Accuracy Tests

### 4.1 Architecture

```
ScriptedClient ──pre-written message──► Agent (real LLM)
                 ◄──response──────────
```

The client sends fixed messages from a script. The server uses the real LLM for intent classification and entity extraction. All other agent logic (Layer 2 decisions, Layer 3 responses) runs normally.

### 4.2 Script Format

```python
TIER2_SCRIPTS = [
    {
        "id": "scenario_name",
        "user_type": "borrower",
        "turns": [
            {
                "message": "Hi, I want to check rates",
                "expect": {
                    "intent": "ask_about_rates",
                    "phase_after": "collecting_info",
                }
            },
            {
                "message": "I'm buying a home in California, worth $500k",
                "expect": {
                    "intent": "provide_loan_info",
                    "entities": {"loan_purpose": "purchase", "state": "CA", "home_value": 500000},
                }
            },
        ]
    },
]
```

### 4.3 Metrics Collected Per Script

| Metric | Definition | Target |
|--------|-----------|--------|
| `intent_accuracy` | % turns where LLM intent matches expected | ≥85% |
| `entity_extraction_rate` | % expected entities correctly extracted | ≥80% |
| `false_positive_intents` | Number of turns where LLM returned wrong intent | 0 |
| `turn_count` | Actual turns vs expected turns | ±1 acceptable |
| `error_rate` | % scripts that hit the errorNode | 0% |

### 4.4 Scenario Design Principles

**Cover every intent.** For each intent in the system, write at least one script where that intent is expected.

**Cover every user type.** Scripts for each user role (borrower, officer, admin).

**Cover both happy and edge paths.** Not just "everything works" but also "what if the user is vague?" and "what if the user corrects themselves?"

**Vary natural language.** Don't use the same phrasing across scripts. "I want a mortgage quote" vs "can you tell me current rates?" vs "how much would a loan cost?" — all should map to `ask_about_rates`.

**Industry-agnostic names.** Don't name scenarios "B1_purchase_ca". Name them generically: "S01_happy_path_user_type_A", "S02_edge_case_vague_input".

## 5. Tier 3: Completion Tests

### 5.1 Architecture

```
SimClient (LLM persona) ──natural msg──► Agent (real LLM)
                          ◄──response──
```

Both sides use LLMs. The simulated client is given a persona (goal, situation, characteristics) and a system prompt instructing it to role-play as that user. The server agent runs normally.

### 5.2 Persona Format

```python
PERSONA = {
    "id": "persona_name",
    "user_type": "borrower",
    "goal": "get a mortgage rate quote",
    "system_prompt": "You are a home buyer. Your situation: {situation}. "
                     "Respond naturally to the mortgage agent's questions. "
                     "Answer what is asked. Be concise.",
    "situation": {
        "loan_purpose": "purchase",
        "home_value": 500000,
        "loan_amount": 300000,
        "state": "California",
        "credit_score": "around 720",
    },
    "success_criteria": {
        "phase": "completed",
        "quote_not_null": True,
    },
}
```

**SimClient template:**

```python
class SimClient:
    """LLM-powered simulated user. Takes a persona, runs conversation loop."""

    def __init__(self, gateway, persona: dict):
        self.gateway = gateway
        self.persona = persona
        self.history = []

    def _build_prompt(self, agent_response: str) -> str:
        """Build the system prompt from persona template + history."""
        prompt = self.persona["system_prompt"].format(**self.persona["situation"])
        for turn in self.history[-6:]:  # last 6 turns for context window
            prompt += f"\nUser: {turn['user']}\nAgent: {turn['agent']}"
        prompt += f"\n\nLast agent message: {agent_response}"
        prompt += "\n\nYour natural response (1-2 sentences, stay in character):"
        return prompt

    def next_message(self, agent_response: str) -> str:
        """Generate the next user message based on persona and conversation."""
        prompt = self._build_prompt(agent_response)
        return self.gateway.call_text(prompt, temperature=0.3)

    def record_turn(self, user_msg: str, agent_response: str):
        self.history.append({"user": user_msg, "agent": agent_response})

    def run(self, agent, opening_message: str, max_turns: int = 15) -> dict:
        """Run a complete conversation. Returns {success, turns, state}."""
        state = AgentState(user_type=self.persona["user_type"])
        user_msg = opening_message

        for turn in range(max_turns):
            result = agent.process(user_msg, "sim_user", self.persona["user_type"],
                                   self.persona.get("name", ""), state)
            self.record_turn(user_msg, result["response"])
            state = result["state"]

            if result["phase"] == "completed":
                return {"success": True, "turns": self.history, "state": state}
            if result["phase"] == "error":
                return {"success": False, "turns": self.history, "state": state, "error": state.error}

            user_msg = self.next_message(result["response"])

        return {"success": False, "turns": self.history, "state": state, "phase": state.phase}
```

### 5.3 Run Configuration

Each persona must be run multiple times (N ≥ 3) to account for LLM variance:

```
for persona in PERSONAS:
    for run in range(N):
        result = run_conversation(persona, max_turns=15)
        record(result)
```

### 5.4 Metrics Collected Per Persona

| Metric | Definition | Pass | Warn | Fail |
|--------|-----------|------|------|------|
| `completion_rate` | % runs that reach the success criteria | ≥70% | 50-69% | <50% |
| `avg_turn_count` | Mean turns to completion (or max if failed) | ≤12 | 13-15 | >15 |
| `loop_count` | Number of runs where same intent repeated >3 turns | 0 | 1 | >1 |
| `error_rate` | % runs that hit the errorNode | ≤10% | 11-20% | >20% |
| `turn_distribution` | Histogram of turn counts across all runs | — | — | — |

### 5.5 Loop Detection

A conversation has entered a loop when:
- The same intent is classified 3+ consecutive turns
- AND the state phase has not changed
- AND the collected data has not changed

When a loop is detected, the run is marked as failed and the conversation transcript is saved for debugging.

### 5.6 Indirect Multi-Party Communication

Tier 3 also validates scenarios where two end-users communicate through the agent:

```
Borrower (LLM) ──msg──► Agent (masks contacts) ──forward──► Loan Officer (LLM)
                       ◄──response─────────────────────────
```

The agent strips PII (email, phone) from forwarded messages. Tier 3 tests must verify:
- Neither party receives the other's contact info
- Messages are correctly relayed
- The payment gate prompt appears when contact is requested

## 6. Scenario Catalog

### 6.1 Minimum Viable Catalog (20 scenarios)

| # | User Type | Scenario Class | Key Test |
|---|-----------|---------------|----------|
| 1 | Type A | Happy path, normal values | Complete workflow |
| 2 | Type A | Happy path, different values | State/amount variant |
| 3 | Type A | Alternative workflow | Different primary action |
| 4 | Type A | Boundary low values | Minimum acceptable inputs |
| 5 | Type A | Boundary high values | Maximum values |
| 6 | Type A | Returning user | Existing data lookup |
| 7 | Type A | Vague responses | Agent guidance |
| 8 | Type A | Mid-flow correction | Value overwrite |
| 9 | Type A | Mid-flow diversion | Topic jump + return |
| 10 | Type A | All info at once | Multi-field extraction |
| 11 | Type A | Channel variant | Alternative input channel |
| 12 | Type A | Status inquiry | Data retrieval |
| 13 | Type B | Registration | Onboarding |
| 14 | Type B | Discovery | List available items |
| 15 | Type B | Action on item | Create/update on item |
| 16 | Type B | Privacy gate | Access control request |
| 17 | Type B | Indirect communication | Relay through agent |
| 18 | Type B | Context switching | Switch between items |
| 19 | Type B | Balance/payment | Financial transaction |
| 20 | Type B | Insufficient balance | Payment gate enforcement |

### 6.2 Expansion to 50+ Scenarios

From the MVP catalog, expand by inference (举一反三):

- For each happy path (1-3): add 2-3 variants (different states, amounts, credit tiers)
- For each edge case (4-8): add 2-3 variants (different fields corrected, different diversions)
- For each officer flow (13-20): add variants (different states, different lead types, different products)
- Add multi-party indirect communication: borrower↔officer complete cycle

## 7. LayerTrace for Visibility

Every agent turn must include a `LayerTrace` that separates LLM work from deterministic work:

```
[L1:LLM] intent=provide_loan_info, conf=0.95, entities={home_value: 800000}
[L2:CODE] phase: collecting_info → collecting_info, decision=borrower_provide_loan_info
[L3:CODE] type=deterministic, template=
```

**LayerTrace data class definition:**

```python
@dataclass
class LayerTrace:
    """Deterministic workflow layer trace for test visibility."""
    layer1_intent: str = ""              # LLM: classified intent
    layer1_confidence: float = 0.0       # LLM: confidence score
    layer1_entities: dict = field(default_factory=dict)  # LLM: extracted entities
    layer2_phase_before: str = ""        # Code: phase before routing
    layer2_phase_after: str = ""         # Code: phase after routing
    layer2_decision: str = ""            # Code: routing decision made
    layer2_validation: str = ""          # Code: validation result
    layer3_response_type: str = "deterministic"  # Code: "deterministic" | "template"
    layer3_template: str = ""            # Code: template name used

    def to_log(self) -> str:
        return (f"[L1:LLM] intent={self.layer1_intent}, conf={self.layer1_confidence:.2f}, "
                f"entities={self.layer1_entities}\n"
                f"[L2:CODE] phase: {self.layer2_phase_before} → {self.layer2_phase_after}, "
                f"decision={self.layer2_decision}, validation={self.layer2_validation}\n"
                f"[L3:CODE] type={self.layer3_response_type}, template={self.layer3_template}")
```

This enables:
- Tier 2: verify the LLM classified correctly
- Tier 3: detect when the LLM and code disagree (LLM extracted entity X but code rejected it)
- Debugging: pinpoint which layer failed without reading the full conversation

## 8. API Mocking

When the agent depends on external APIs (SMS, payment, CRM), mock them for all three tiers:

| API | Mock Behavior |
|-----|-------------|
| SMS | Return `{"status": "sent"}` for all calls |
| Payment/Balance | In-memory ledger, deduct on quote, recharge on command |
| Email | Log all sends, return success |
| External data | Return pre-seeded test data |

For each mocked API, track a GitHub issue for the real integration. The mock interface should match the real API's contract so the switch requires zero agent code changes.

## 9. CI/CD Integration

| Tier | Runs On | Trigger | API Key Required |
|------|---------|---------|-----------------|
| Tier 1 | Every commit | pre-push / PR | No |
| Tier 2 | Daily / PR | scheduled / manual | Yes |
| Tier 3 | Weekly / release | scheduled | Yes |

Tier 1 is the gatekeeper. No code merges if Tier 1 fails. Tier 2 and Tier 3 are quality monitors — their results inform but don't block.

## 10. LLM Gateway Resilience Testing

Gateway retry behavior is a distinct concern from agent logic. The agent delegates LLM calls to a Gateway; the Gateway handles network failures, rate limits, and malformed responses. This should be tested separately.

**What to test:**

| Scenario | Expected Behavior | Tier |
|----------|------------------|------|
| LLM API returns 401 (bad key) | Gateway retries up to N, then raises RuntimeError. Agent catches and routes to errorNode. | Tier 1 |
| LLM API returns 429 (rate limit) | Gateway backs off exponentially. Retries succeed on attempt 2-3. | Tier 1 |
| LLM returns malformed JSON | Gateway retries. After N failures, raises RuntimeError. | Tier 1 |
| LLM times out | Gateway retries. After N timeouts, raises RuntimeError. | Tier 1 |
| LLM succeeds on retry 2 | Gateway returns result. Agent continues normally. | Tier 1 |

**Mock LLM Gateway for retry testing:**

```python
class FlakyMockGateway:
    """Simulates LLM API failures for retry testing."""
    def __init__(self, fail_count: int = 2, max_retries: int = 3):
        self.call_count = 0
        self.fail_count = fail_count
        self.max_retries = max_retries

    def call(self, prompt, output_schema, temperature=0):
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise ConnectionError("simulated network failure")
        return output_schema(intent="greet", confidence=1.0)
```

**Gateway config per environment:**

| Env | Model | Retries | Timeout |
|-----|-------|---------|---------|
| Dev | cheap model | 1 | 5s |
| E2E | prod model | 2 | 10s |
| Prod | prod model | 3 | 15s |

## 11. Test File Structure

```
tests/
├── tier1/                    # Logic tests, deterministic, no API key
│   ├── test_workflow.py      # Happy path + variants (举一反三)
│   ├── test_edge_cases.py    # Corrections, diversions, boundaries, vague input
│   └── test_error_paths.py   # Low confidence, missing entities, DB failures
├── tier2/                    # LLM accuracy tests
│   ├── scenarios/            # One file per scenario or group
│   │   ├── s01_happy_path_type_a.py
│   │   ├── s02_happy_path_type_a_variant.py
│   │   ├── s08_correction.py
│   │   └── ...
│   └── conftest.py           # Shared fixtures, LiveAgent, metrics collector
├── tier3/                    # Completion tests
│   ├── personas/
│   │   ├── p01_persona_a.py
│   │   ├── p02_persona_b.py
│   │   └── ...
│   └── conftest.py           # SimClient, run harness, metrics aggregator
├── mocks/                    # Shared mock implementations
│   ├── mock_gateway.py       # MockGateway base class
│   ├── mock_sms.py           # SMS API mock
│   └── mock_external_api.py  # Other external API mocks
└── sim_client.py             # SimClient for Tier 3 (shared across personas)
```

## 12. Per-Tier Scenario Allocation

| Tier | MVP Count | Expanded Count | What to Test |
|------|-----------|----------------|--------------|
| Tier 1 | 8-10 | 20-25 | Code paths: every state transition, every entity field exhaustion check, error paths |
| Tier 2 | 20 | 50+ | One script per intent + one per user type + edge case variants |
| Tier 3 | 3-5 personas × 3 runs | 8-10 personas × 5 runs | End-to-end completion, loop detection, indirect communication |

Tier 1 scenarios are about **code path coverage** — they don't need LLM, so they can be more numerous and faster. Tier 2 scenarios are about **LLM understanding coverage** — one per intent ensures every classification path is tested with real LLM. Tier 3 scenarios are about **stochastic system behavior** — fewer runs but each run is a complete conversation.

**Single-user-type adaptation:** If your agent has only 1 user type, allocate all scenarios to that type, varying the workflow dimension instead of the user-type dimension. If you have 3+ user types, split the catalog proportionally. The Type A / Type B structure in Section 6.1 is illustrative, not prescriptive.

## 13. Multi-Turn State Assertions

Conversation state accumulates across turns. Tests must verify state persistence:

```python
# After turn 2: verify initial data collected
assert state.collected_data == {"loan_purpose": "purchase"}
assert state.phase == "collecting_info"

# After turn 3: new data added, old data preserved
assert state.collected_data == {"loan_purpose": "purchase", "home_value": 500000}

# After turn 4 (diversion to help): data MUST survive
assert state.collected_data["loan_purpose"] == "purchase"  # still there

# After turn 6 (completion): full state check
assert state.phase == "completed"
assert state.lead_id is not None
assert state.quote is not None
assert state.quote["interest_rate"] > 0
```

**State corruption detection checklist:**
- After a help or greeting diversion, is `collected_data` intact?
- After a correction, did the new value overwrite the old one correctly?
- After completion, are `lead_id`, `quote`, and `borrower_id` all set?
- Does `current_lead_id` track the correct lead after switching?

## 14. API Mock Code Templates

Mock external APIs with classes that implement the same interface but no network calls:

```python
class MockSMSClient:
    """Drop-in replacement for SMS API. Same interface, zero network."""
    def __init__(self):
        self.sent = []

    def send(self, to: str, body: str) -> dict:
        self.sent.append({"to": to, "body": body, "timestamp": datetime.utcnow()})
        return {"status": "sent", "message_id": f"mock-{len(self.sent)}"}

class MockBalanceLedger:
    """In-memory balance ledger. Replaces payment processor API."""
    def __init__(self, initial_balance: float = 0):
        self.balance = initial_balance
        self.transactions = []

    def deduct(self, amount: float, reason: str) -> bool:
        if self.balance < amount:
            return False
        self.balance -= amount
        self.transactions.append({"type": "deduct", "amount": amount, "reason": reason})
        return True

    def recharge(self, amount: float) -> None:
        self.balance += amount
        self.transactions.append({"type": "recharge", "amount": amount})
```

**Injection strategy:** Use dependency injection — the agent accepts an optional `sms_client` or `balance_ledger` parameter that defaults to the real API client in production but receives the mock in tests. Avoid monkey-patching globals.

## 15. Definition of Done

Testing is complete when ALL of the following are satisfied:

- [ ] All Tier 1 scenarios pass (MVP: 8-10, Expanded: 20-25)
- [ ] All Tier 2 scripts pass with metrics at or above targets
- [ ] ≥85% `intent_accuracy` across Tier 2 scripts
- [ ] ≥3 Tier 3 personas, each run N≥3, all metrics at or above targets
- [ ] `completion_rate` ≥70% across Tier 3 runs
- [ ] `loop_count` = 0 (no infinite loops detected in Tier 3)
- [ ] Domain model exhaustion checklist complete (Section 3.3)
- [ ] One Tier 2 script exists per intent
- [ ] One Tier 2 script exists per user type
- [ ] One Tier 2 edge-case script exists per edge case class (correction, diversion, vague)
- [ ] Every mock API has a corresponding GitHub issue for real integration

## 16. Sources

- Tier 1 design: confidence high — 65 passing mock tests in mfangdai-agent demonstrate the pattern
- Tier 2 design: confidence high — LLM accuracy measurement is a standard NLP evaluation pattern
- Tier 3 design: confidence medium — dual-LLM conversation testing is novel; completion rate targets (70%) are provisional
- LayerTrace: confidence high — implemented and verified in mfangdai-agent sim tests
- Scenario catalog: confidence high — derived from Postman collection (42 use cases) adapted to generic form
- 举一反三 principle: confidence high — demonstrated in 34 FT scenarios with 2-3 inference variants each
