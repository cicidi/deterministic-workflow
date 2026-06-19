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

        # Borrower: extract entities from message
        entities = {}
        if "800000" in msg or "800k" in msg or "800,000" in msg:
            entities["home_value"] = 800000
        if "500000" in msg or "500k" in msg:
            entities["home_value"] = 500000
        if "300000" in msg or "300k" in msg:
            entities["home_value"] = 300000
        if "400000" in msg or "400k" in msg:
            entities["loan_amount"] = 400000
        if "200000" in msg or "200k" in msg:
            entities["loan_amount"] = 200000
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
