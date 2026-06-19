"""Functional Tests — simulated multi-turn conversations.

Scenarios:
  1. Home Owner full flow: greet → ask rates → provide info → receive quote
  2. Home Owner incomplete → help diversion
  3. Loan Officer: ask for leads → get list → submit quote
  4. Loan Officer registration
  5. No-matching-officer edge case
"""
import pytest

from src.db import init_db, seed_loan_officers, get_session, Base
from src.gateway import Gateway
from src.hydration import AgentState
from src.state_machine import Agent


class MockGateway(Gateway):
    """Mock LLM Gateway that reads user message from classify prompt."""

    def _extract_user_message(self, prompt: str) -> str:
        marker = 'User message: "'
        if marker in prompt:
            start = prompt.index(marker) + len(marker)
            end = prompt.index('"', start)
            return prompt[start:end]
        return prompt

    def call(self, prompt, output_schema, temperature=0):
        from src.executors.classify import IntentClassificationResult

        msg = self._extract_user_message(prompt).lower()

        # Help / Greeting
        if "hello" in msg or "hi " in msg or "hey" in msg:
            return IntentClassificationResult(intent="greet", confidence=1.0)
        if "help" in msg or "what can you do" in msg:
            return IntentClassificationResult(intent="help", confidence=1.0)

        # Check status
        if "status" in msg and ("my" in msg or "check" in msg):
            return IntentClassificationResult(intent="check_quote_status", confidence=1.0)
        if "application" in msg or "pending" in msg:
            return IntentClassificationResult(intent="check_quote_status", confidence=1.0)

        # Loan officer: leads
        if "leads" in msg:
            entities = {}
            for state_name, abbr in [("california", "CA"), ("new york", "NY"), ("texas", "TX"),
                                       ("florida", "FL"), ("illinois", "IL")]:
                if state_name in msg or abbr.lower() in msg:
                    entities["state"] = abbr
                    break
            return IntentClassificationResult(intent="ask_for_leads", confidence=1.0, entities=entities)

        # Loan officer: register
        if "register" in msg:
            return IntentClassificationResult(intent="register_loan_officer", confidence=1.0)

        # Loan officer: submit quote
        if "offer" in msg or "give" in msg or ("6." in msg and "%" in msg):
            return IntentClassificationResult(intent="submit_quote", confidence=1.0, entities={"interest_rate": 6.5})

        # Loan officer: providing registration info (NMLS, licensing)
        if "nmls" in msg or "licensed" in msg:
            entities = {}
            if "texas" in msg or " tx" in msg:
                entities["state"] = "TX"
            if "florida" in msg or " fl" in msg:
                entities["state"] = "FL"
            if "california" in msg or " ca" in msg:
                entities["state"] = "CA"
            return IntentClassificationResult(
                intent="register_loan_officer", confidence=1.0, entities=entities
            )

        # Borrower: extract entities from message (context-aware)
        entities = {}

        # Home value: messages with "home", "worth", "property", "value"
        if any(w in msg for w in ("home", "worth", "property", "value")):
            if "800000" in msg or "800k" in msg:
                entities["home_value"] = 800000
            elif "500000" in msg or "500k" in msg:
                entities["home_value"] = 500000
            elif "300000" in msg or "300k" in msg:
                entities["home_value"] = 300000

        # Loan amount: messages with "loan", "borrow", "need"
        if any(w in msg for w in ("loan", "borrow", "need")):
            if "400000" in msg or "400k" in msg:
                entities["loan_amount"] = 400000
            elif "300000" in msg or "300k" in msg:
                entities["loan_amount"] = 300000
            elif "200000" in msg or "200k" in msg:
                entities["loan_amount"] = 200000

        # State
        if "california" in msg or msg.endswith(" ca"):
            entities["state"] = "CA"
        if "nevada" in msg or msg.endswith(" nv"):
            entities["state"] = "NV"
        if "alaska" in msg or msg.endswith(" ak"):
            entities["state"] = "AK"

        # Credit score extraction
        if "780" in msg:
            entities["credit_score_range"] = "780_799"
        elif "720" in msg:
            entities["credit_score_range"] = "720_739"
        elif "620" in msg:
            entities["credit_score_range"] = "620_639"
        elif "credit" in msg and "score" in msg:
            entities["credit_score_range"] = "720_739"
        if "credit" in msg and "score" not in msg and "credit" not in entities:
            entities["credit_score_range"] = entities.get("credit_score_range", "720_739")

        # Loan purpose
        if "refinanc" in msg:
            entities["loan_purpose"] = "refinance"
        elif "purchas" in msg or "buying" in msg or "new home" in msg:
            entities["loan_purpose"] = "purchase"

        return IntentClassificationResult(
            intent="provide_loan_info" if entities else "ask_about_rates",
            confidence=1.0,
            entities=entities,
        )


@pytest.fixture(scope="module")
def agent():
    init_db("sqlite:///mfangdai_ft.db")
    session = get_session()
    try:
        Base.metadata.create_all(session.get_bind())
        seed_loan_officers(session)
    finally:
        session.close()
    gw = MockGateway()
    return Agent(gw)


def _step(agent, state, msg, user_id, user_type, user_name=""):
    """Helper: process one message and return (response_text, new_state)."""
    result = agent.process(msg, user_id, user_type, user_name, state)
    return result["response"], result["state"]


# ─────────────────────────────────────────────────────────────
# Scenario 1: Home Owner Full Flow — Alice refinances in CA
# ─────────────────────────────────────────────────────────────
def test_scenario_home_owner_full_flow(agent):
    """Alice: refinance $800k home in CA, borrow $400k, credit 780 → gets quote."""
    user_id, utype = "alice_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Alice")

    # Turn 1: Greeting
    resp, state = _step(agent, state, "Hello", user_id, utype, "Alice")
    assert "hello" in resp.lower() or "mortgage" in resp.lower()
    assert state.user_name == "Alice"

    # Turn 2: Ask about rates (doesn't mention purchase/refinance so agent asks)
    resp, state = _step(agent, state, "I want to check mortgage rates", user_id, utype, "Alice")
    assert "purchase" in resp.lower() or "refinanc" in resp.lower()
    assert state.phase == "collecting_info"

    # Turn 3: Loan purpose
    resp, state = _step(agent, state, "I'm refinancing my home", user_id, utype, "Alice")
    assert state.collected_data.get("loan_purpose") == "refinance"

    # Turn 4: Home value
    resp, state = _step(agent, state, "My home is worth about 800000", user_id, utype, "Alice")
    assert state.collected_data.get("home_value") == 800000

    # Turn 5: Loan amount
    resp, state = _step(agent, state, "I need to borrow 400000", user_id, utype, "Alice")
    assert state.collected_data.get("loan_amount") == 400000

    # Turn 6: State
    resp, state = _step(agent, state, "The property is in California", user_id, utype, "Alice")
    assert state.collected_data.get("state") == "CA"

    # Turn 7: Credit score — triggers full pipeline
    resp, state = _step(agent, state, "My credit score is 780", user_id, utype, "Alice")
    assert state.phase in ("quote_generated", "completed")
    assert "6." in resp or "%" in resp  # rate appears
    assert "$" in resp  # monthly payment appears
    assert "month" in resp.lower() or "payment" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 2: Home Owner diversion — ask rates then help
# ─────────────────────────────────────────────────────────────
def test_scenario_home_owner_diversion_to_help(agent):
    """Bob starts asking rates, then asks what the agent can do."""
    user_id, utype = "bob_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Bob")

    resp, state = _step(agent, state, "I want a mortgage quote", user_id, utype, "Bob")
    assert state.phase == "collecting_info"

    resp, state = _step(agent, state, "I'm buying a new home", user_id, utype, "Bob")
    assert state.collected_data.get("loan_purpose") == "purchase"

    # Diversion: ask for help
    resp, state = _step(agent, state, "Actually, what can you do exactly?", user_id, utype, "Bob")
    assert "rate quote" in resp.lower() or "mortgage" in resp.lower()
    assert "help" in resp.lower() or "can" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 3: Loan Officer — ask for leads, get list, submit quote
# ─────────────────────────────────────────────────────────────
def test_scenario_loan_officer_leads_and_quote(agent):
    """Mike (CA-licensed officer) asks for CA leads, gets list, submits quote."""
    user_id, utype = "mike_ft", "loan_officer"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Mike")

    # First, create a lead in CA so there's something to show
    alice_state = AgentState(user_id="alice_for_mike", user_type="borrower", user_name="Alice")
    resp, alice_state = _step(agent, alice_state, "Hi", "alice_for_mike", "borrower", "Alice")
    resp, alice_state = _step(agent, alice_state, "I want rates for refinancing", "alice_for_mike", "borrower", "Alice")
    resp, alice_state = _step(agent, alice_state, "I'm refinancing", "alice_for_mike", "borrower", "Alice")
    resp, alice_state = _step(agent, alice_state, "Home is worth 500000", "alice_for_mike", "borrower", "Alice")
    resp, alice_state = _step(agent, alice_state, "Need 300000 loan", "alice_for_mike", "borrower", "Alice")
    resp, alice_state = _step(agent, alice_state, "In California", "alice_for_mike", "borrower", "Alice")
    resp, alice_state = _step(agent, alice_state, "Credit score 720", "alice_for_mike", "borrower", "Alice")

    # Now Mike asks for leads
    resp, state = _step(agent, state, "Show me available leads", user_id, utype, "Mike")
    assert "lead" in resp.lower() or "available" in resp.lower()

    # Mike gives a quote
    resp, state = _step(agent, state, "I can offer 6.5% on that lead", user_id, utype, "Mike")
    assert "quote" in resp.lower() or "forward" in resp.lower() or "received" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 4: Loan Officer Registration
# ─────────────────────────────────────────────────────────────
def test_scenario_loan_officer_registration(agent):
    """New loan officer Sarah registers."""
    user_id, utype = "sarah_ft", "loan_officer"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Sarah")

    resp, state = _step(agent, state, "I want to register as a loan officer on your platform", user_id, utype, "Sarah")
    assert "nmls" in resp.lower() or "regist" in resp.lower() or "email" in resp.lower()
    assert "license" in resp.lower() or "state" in resp.lower() or "register" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 5: No matching officer edge case
# ─────────────────────────────────────────────────────────────
def test_scenario_no_matching_officer(agent):
    """Borrower in Alaska (no seeded officers there) should get appropriate message."""
    user_id, utype = "charlie_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Charlie")

    resp, state = _step(agent, state, "I want mortgage rates", user_id, utype, "Charlie")
    resp, state = _step(agent, state, "I'm buying a home", user_id, utype, "Charlie")
    resp, state = _step(agent, state, "Home is worth 300000", user_id, utype, "Charlie")
    resp, state = _step(agent, state, "Need 200000 loan", user_id, utype, "Charlie")
    resp, state = _step(agent, state, "Property is in Alaska", user_id, utype, "Charlie")
    resp, state = _step(agent, state, "Credit score 720", user_id, utype, "Charlie")

    assert state.phase == "lead_created"
    assert "couldn't" in resp.lower() or "notify" in resp.lower() or "available" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 6: Check quote status
# ─────────────────────────────────────────────────────────────
def test_scenario_check_quote_status(agent):
    """Borrower asks about status of a previous lead."""
    user_id, utype = "dave_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Dave")

    resp, state = _step(agent, state, "What's the status of my application?", user_id, utype, "Dave")
    assert "submitted" in resp.lower() or "review" in resp.lower() or "lead" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 7: Agent explains product to new loan officer,
#             encourages registration with basic info (NMLS, email, states)
# ─────────────────────────────────────────────────────────────
def test_scenario_agent_promotes_to_loan_officer(agent):
    """New loan officer asks about the product — agent explains and encourages registration."""
    user_id, utype = "tony_ft", "loan_officer"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Tony")

    # Tony asks what the platform offers
    resp, state = _step(agent, state, "Hi, I'm a loan officer. What does your platform offer?", user_id, utype, "Tony")
    # Should mention leads, quotes, or registration
    assert any(w in resp.lower() for w in ("lead", "quote", "regist", "view"))

    # Tony says he wants to register
    resp, state = _step(agent, state, "I want to register as a loan officer", user_id, utype, "Tony")
    # Should ask for NMLS, email, or licensed states
    assert any(w in resp.lower() for w in ("nmls", "email", "license", "state"))

    # Tony provides partial registration info
    resp, state = _step(agent, state, "My NMLS is 123456 and I'm licensed in Texas and Florida", user_id, utype, "Tony")
    # Should acknowledge or prompt for more info (email still needed)
    assert any(w in resp.lower() for w in ("nmls", "regist", "email", "complete"))


# ─────────────────────────────────────────────────────────────
# Scenario 8: Lead flows to loan officer who submits a quote,
#             then borrower receives the officer's quote
# ─────────────────────────────────────────────────────────────
def test_scenario_lead_to_officer_quote_roundtrip(agent):
    """Borrower creates lead → officer sees it → officer submits quote → borrower gets it."""
    # Step 1: Borrower completes a full lead flow
    alice_id, alice_type = "alice_rnd", "borrower"
    alice_state = AgentState(user_id=alice_id, user_type=alice_type, user_name="Alice")
    resp, alice_state = _step(agent, alice_state, "Hello", alice_id, alice_type, "Alice")
    resp, alice_state = _step(agent, alice_state, "I want mortgage rates", alice_id, alice_type, "Alice")
    resp, alice_state = _step(agent, alice_state, "I'm buying a home", alice_id, alice_type, "Alice")
    resp, alice_state = _step(agent, alice_state, "Home is worth 500000", alice_id, alice_type, "Alice")
    resp, alice_state = _step(agent, alice_state, "Need 300000 loan", alice_id, alice_type, "Alice")
    resp, alice_state = _step(agent, alice_state, "In California", alice_id, alice_type, "Alice")
    resp, alice_state = _step(agent, alice_state, "Credit score 720", alice_id, alice_type, "Alice")
    assert alice_state.phase == "completed"
    assert "%" in resp
    assert "$" in resp

    # Step 2: Loan officer Mike checks for leads
    mike_id, mike_type = "mike_rnd", "loan_officer"
    mike_state = AgentState(user_id=mike_id, user_type=mike_type, user_name="Mike")
    resp, mike_state = _step(agent, mike_state, "Show me available leads in California", mike_id, mike_type, "Mike")
    assert "lead" in resp.lower() or "available" in resp.lower()

    # Step 3: Mike submits a quote (simulated via agent's submit_quote intent)
    resp, mike_state = _step(agent, mike_state, "I can offer 6.5% for this lead", mike_id, mike_type, "Mike")
    assert "quote" in resp.lower() or "forward" in resp.lower() or "received" in resp.lower()


# ─────────────────────────────────────────────────────────────
# Scenario 9: Rate matrix simulated tool test
# ─────────────────────────────────────────────────────────────
def test_scenario_rate_matrix_tool(agent):
    """Verify the simulated rate matrix returns correct rates for different credit scores."""
    from src.executors.decide import _get_simulated_rate, _calculate_monthly_payment

    # Best credit → lowest rate
    assert _get_simulated_rate("800_plus") == 6.0
    # Mid credit → mid rate
    assert _get_simulated_rate("700_719") == 6.7
    # Poor credit → highest rate
    assert _get_simulated_rate("below_620") == 8.0
    # Unknown range → default
    assert _get_simulated_rate("mystery") == 7.0

    # Payment calculation sanity check
    p1 = _calculate_monthly_payment(400000, 6.0, 360)
    p2 = _calculate_monthly_payment(400000, 8.0, 360)
    assert p2 > p1  # higher rate = higher payment


# ═════════════════════════════════════════════════════════════
# Edge Case Scenarios: wrong values, corrections, topic jumps,
# clarifying questions, stubborn customer guidance
# ═════════════════════════════════════════════════════════════

# ── Scenario 10: Customer gives wrong value → corrects it ──
def test_scenario_correction_wrong_value(agent):
    """Customer says $800k home, then 'wait, I meant $500k' — value overwritten."""
    user_id, utype = "eva_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Eva")

    resp, state = _step(agent, state, "Hi, I want mortgage rates", user_id, utype, "Eva")
    resp, state = _step(agent, state, "I'm buying", user_id, utype, "Eva")
    assert state.collected_data.get("loan_purpose") == "purchase"

    # Give wrong value
    resp, state = _step(agent, state, "Home is worth 800000", user_id, utype, "Eva")
    assert state.collected_data.get("home_value") == 800000

    # Correct it
    resp, state = _step(agent, state, "Oh wait, I meant the home is worth 500000, sorry", user_id, utype, "Eva")
    assert state.collected_data.get("home_value") == 500000


# ── Scenario 11: Customer asks a clarifying question mid-flow ──
def test_scenario_clarifying_question(agent):
    """Customer asks 'what's a conventional loan?' then continues."""
    user_id, utype = "frank_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Frank")

    resp, state = _step(agent, state, "I want to check rates", user_id, utype, "Frank")
    resp, state = _step(agent, state, "I'm buying", user_id, utype, "Frank")
    assert state.collected_data.get("loan_purpose") == "purchase"

    # Frank asks a clarifying question
    resp, state = _step(agent, state, "By the way, what kinds of loans do you offer?", user_id, utype, "Frank")
    # Agent should respond helpfully, not lose collected data
    assert state.collected_data.get("loan_purpose") == "purchase"

    # Frank continues
    resp, state = _step(agent, state, "Home is worth 500000", user_id, utype, "Frank")
    assert state.collected_data.get("home_value") == 500000


# ── Scenario 12: Customer changes loan purpose mid-flow ──
def test_scenario_change_loan_purpose(agent):
    """Customer says buying, then changes to refinance."""
    user_id, utype = "grace_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Grace")

    resp, state = _step(agent, state, "I want mortgage rates", user_id, utype, "Grace")
    resp, state = _step(agent, state, "I'm buying a home", user_id, utype, "Grace")
    assert state.collected_data.get("loan_purpose") == "purchase"

    # Actually, I'm refinancing
    resp, state = _step(agent, state, "Actually I want to refinance, not buy", user_id, utype, "Grace")
    assert state.collected_data.get("loan_purpose") == "refinance"


# ── Scenario 13: Customer provides multiple fields in one message ──
def test_scenario_multiple_fields_at_once(agent):
    """Customer says home value, loan amount, and location in one message."""
    user_id, utype = "henry_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Henry")

    resp, state = _step(agent, state, "I want rates for buying a home in California, it's worth 500000 and I need 300000 loan", user_id, utype, "Henry")
    assert state.collected_data.get("loan_purpose") == "purchase"
    assert state.collected_data.get("state") == "CA"
    assert state.collected_data.get("home_value") == 500000
    assert state.collected_data.get("loan_amount") == 300000

    # Agent should ask for remaining field (credit score)
    assert "credit" in resp.lower()


# ── Scenario 14: Stubborn customer gives vague answers — agent persists ──
def test_scenario_agent_guides_vague_customer(agent):
    """Customer says 'I don't know' — agent should offer guidance."""
    user_id, utype = "iris_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Iris")

    resp, state = _step(agent, state, "Hi, can I get a mortgage?", user_id, utype, "Iris")
    resp, state = _step(agent, state, "I'm not sure, I want to buy something", user_id, utype, "Iris")
    # Agent should still ask for next field, collected_data should capture what it can
    assert "value" in resp.lower() or "home" in resp.lower() or "property" in resp.lower()

    # Iris gives more vague info
    resp, state = _step(agent, state, "I guess the home is worth something like 500000 maybe?", user_id, utype, "Iris")
    assert state.collected_data.get("home_value") == 500000

    # Iris is confused about credit
    resp, state = _step(agent, state, "I don't really know my credit score, is that bad?", user_id, utype, "Iris")
    # Agent should still be guiding — credit score range extracted or asking again
    assert resp  # at least got a response


# ── Scenario 15: Customer jumps between topics ──
def test_scenario_topic_jumping(agent):
    """Customer: rates → help → status → back to providing info."""
    user_id, utype = "jack_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Jack")

    resp, state = _step(agent, state, "What rates do you have?", user_id, utype, "Jack")
    resp, state = _step(agent, state, "I'm buying", user_id, utype, "Jack")

    # Jump: ask what the agent can do
    resp, state = _step(agent, state, "Wait, what exactly can you help me with?", user_id, utype, "Jack")
    assert "rate" in resp.lower() or "quote" in resp.lower()

    # Jump: check status (even though no lead yet)
    resp, state = _step(agent, state, "Do I have any pending applications?", user_id, utype, "Jack")
    assert "submitted" in resp.lower() or "review" in resp.lower() or "lead" in resp.lower()

    # Back to providing info
    resp, state = _step(agent, state, "OK the home is worth 500000", user_id, utype, "Jack")
    assert state.collected_data.get("home_value") == 500000


# ── Scenario 16: Customer asks about fees before completing ──
def test_scenario_asks_about_fees(agent):
    """Customer asks 'what are the fees?' mid-collection, then finishes."""
    user_id, utype = "karen_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Karen")

    resp, state = _step(agent, state, "I want to check mortgage rates", user_id, utype, "Karen")
    resp, state = _step(agent, state, "Buying a home", user_id, utype, "Karen")
    resp, state = _step(agent, state, "Home is worth 500000", user_id, utype, "Karen")

    # Interrupt: ask about costs
    resp, state = _step(agent, state, "What kind of fees should I expect?", user_id, utype, "Karen")
    # Agent should respond — at least not crash, ideally mention something about fees or continue
    assert resp

    # Continue providing info — collected data from before should be intact
    assert state.collected_data.get("home_value") == 500000
    resp, state = _step(agent, state, "Need 300000 loan", user_id, utype, "Karen")
    assert state.collected_data.get("loan_amount") == 300000


# ── Scenario 17: Customer rejects quote, starts over ──
def test_scenario_reject_quote_restart(agent):
    """Customer completes flow, gets quote, then starts a new inquiry."""
    user_id, utype = "leo_ft", "borrower"
    state = AgentState(user_id=user_id, user_type=utype, user_name="Leo")

    # First inquiry
    resp, state = _step(agent, state, "Hi, I want rates", user_id, utype, "Leo")
    resp, state = _step(agent, state, "Buying", user_id, utype, "Leo")
    resp, state = _step(agent, state, "Home worth 500000", user_id, utype, "Leo")
    resp, state = _step(agent, state, "Need 300000 loan", user_id, utype, "Leo")
    resp, state = _step(agent, state, "In California", user_id, utype, "Leo")
    resp, state = _step(agent, state, "Credit score 720", user_id, utype, "Leo")
    assert state.phase == "completed"

    # Leo wants to try again with different numbers
    resp, state = _step(agent, state, "I want to check rates for another property", user_id, utype, "Leo")
    # For now, post-completion stays completed — agent acknowledges but doesn't auto-restart
    assert state.phase == "completed"
    assert resp  # got a response
