"""Tests for mfangdai agent — borrower and loan officer workflows."""
import pytest

from src.db import init_db, seed_loan_officers, get_session, Base
from src.gateway import Gateway
from src.hydration import AgentState
from src.state_machine import Agent


class MockGateway(Gateway):
    """Mock LLM Gateway for deterministic testing."""

    def _extract_user_message(self, prompt: str) -> str:
        """Extract just the user message from the full classify prompt."""
        marker = 'User message: "'
        if marker in prompt:
            start = prompt.index(marker) + len(marker)
            end = prompt.index('"', start)
            return prompt[start:end]
        return prompt

    def call(self, prompt, output_schema, temperature=0):
        """Return pre-defined intent based on user message, ignoring template boilerplate."""
        from src.executors.classify import IntentClassificationResult

        msg = self._extract_user_message(prompt).lower()

        # Greeting
        if any(w in msg for w in ("hello", "hi ", "hey")):
            return IntentClassificationResult(intent="greet", confidence=1.0)

        # Help
        if "help" in msg or "what can you do" in msg:
            return IntentClassificationResult(intent="help", confidence=1.0)

        # Check status
        if "status" in msg:
            return IntentClassificationResult(intent="check_quote_status", confidence=1.0)

        # Loan officer intents
        if "leads" in msg:
            entities = {}
            if "california" in msg or "ca" in msg:
                entities["state"] = "CA"
            return IntentClassificationResult(intent="ask_for_leads", confidence=1.0, entities=entities)

        if "register" in msg:
            return IntentClassificationResult(intent="register_loan_officer", confidence=1.0)

        if "offer" in msg or ("6." in msg and "%" in msg):
            return IntentClassificationResult(intent="submit_quote", confidence=1.0, entities={"interest_rate": 6.5})

        # Borrower intents: extract entities from user message
        entities = {}
        if "500000" in msg or "500k" in msg:
            entities["home_value"] = 500000
        if "300000" in msg or "300k" in msg:
            entities["loan_amount"] = 300000
        if "california" in msg or " ca " in msg or msg.endswith(" ca"):
            entities["state"] = "CA"
        if "720" in msg:
            entities["credit_score_range"] = "720_739"
        if "credit" in msg:
            entities["credit_score_range"] = "720_739"
        if "buying" in msg or "purchas" in msg:
            entities["loan_purpose"] = "purchase"

        return IntentClassificationResult(
            intent="provide_loan_info" if entities else "ask_about_rates",
            confidence=1.0,
            entities=entities,
        )


@pytest.fixture(scope="module")
def agent():
    """Create agent with mock gateway and in-memory SQLite DB."""
    init_db("sqlite:///mfangdai_test.db")
    session = get_session()
    try:
        Base.metadata.create_all(session.get_bind())
        seed_loan_officers(session)
    finally:
        session.close()

    gw = MockGateway()
    return Agent(gw)


class TestBorrowerWorkflow:
    """Test home owner / borrower flows."""

    def test_greet(self, agent):
        state = AgentState(user_id="b1", user_type="borrower", user_name="Alice")
        result = agent.process("Hello", "b1", "borrower", "Alice", state)
        assert "Hello" in result["response"]
        assert "help" in result["response"].lower() or "mortgage" in result["response"].lower()

    def test_ask_about_rates_starts_collection(self, agent):
        state = AgentState(user_id="b1", user_type="borrower", user_name="Alice")
        result = agent.process("I want to check mortgage rates", "b1", "borrower", "Alice", state)
        assert "purchase" in result["response"].lower() or "refinanc" in result["response"].lower()
        assert result["phase"] == "collecting_info"

    def test_full_quote_flow(self, agent):
        """Full end-to-end: borrower provides info → lead created → officer matched → quote generated."""
        state = AgentState(user_id="b2", user_type="borrower", user_name="Bob")

        # Step 1: Start
        result = agent.process("I want a mortgage quote", "b2", "borrower", "Bob", state)
        assert result["phase"] == "collecting_info"

        # Step 2: Provide loan purpose
        result = agent.process("I'm buying a home", "b2", "borrower", "Bob", result["state"])
        assert result["phase"] == "collecting_info"

        # Step 3: Provide home value
        result = agent.process("Home is worth 500000", "b2", "borrower", "Bob", result["state"])
        assert result["state"].collected_data.get("home_value") == 500000

        # Step 4: Provide loan amount
        result = agent.process("I want to borrow 300000", "b2", "borrower", "Bob", result["state"])
        assert result["state"].collected_data.get("loan_amount") == 300000

        # Step 5: Provide state
        result = agent.process("Property is in California", "b2", "borrower", "Bob", result["state"])
        assert result["state"].collected_data.get("state") == "CA"

        # Step 6: Provide credit score — should trigger full pipeline
        result = agent.process("My credit score is 720", "b2", "borrower", "Bob", result["state"])
        assert result["phase"] in ("quote_generated", "completed")
        assert "interest" in result["response"].lower() or "%" in result["response"]
        assert "payment" in result["response"].lower() or "$" in result["response"]

    def test_check_status(self, agent):
        state = AgentState(user_id="b3", user_type="borrower", user_name="Carol")
        result = agent.process("What's the status of my quote?", "b3", "borrower", "Carol", state)
        assert "submitted" in result["response"].lower() or "review" in result["response"].lower()


class TestLoanOfficerWorkflow:
    """Test loan officer flows."""

    def test_ask_for_leads(self, agent):
        state = AgentState(user_id="o1", user_type="loan_officer", user_name="Mike")
        result = agent.process("Show me leads in California", "o1", "loan_officer", "Mike", state)
        assert "lead" in result["response"].lower() or "available" in result["response"].lower()

    def test_register_interest(self, agent):
        state = AgentState(user_id="o2", user_type="loan_officer", user_name="Sarah")
        result = agent.process("I want to register as a loan officer", "o2", "loan_officer", "Sarah", state)
        assert "nmls" in result["response"].lower() or "regist" in result["response"].lower()

    def test_submit_quote(self, agent):
        state = AgentState(user_id="o1", user_type="loan_officer", user_name="Mike")
        result = agent.process("I'll offer 6.5% for this lead", "o1", "loan_officer", "Mike", state)
        assert "quote" in result["response"].lower() or "forward" in result["response"].lower()


class TestExtractionPipeline:
    """Test E→V→T extraction pipeline."""

    def test_state_normalization(self, agent):
        from src.executors.extract import _normalize_state
        assert _normalize_state("California") == "CA"
        assert _normalize_state("CA") == "CA"
        assert _normalize_state("ca") == "CA"
        assert _normalize_state("NEW YORK") == "NY"

    def test_credit_score_normalization(self, agent):
        from src.executors.extract import _normalize_credit_score
        assert _normalize_credit_score("720") == "720_739"
        assert _normalize_credit_score("740") == "740_759"
        assert _normalize_credit_score("580") == "below_620"

    def test_loan_purpose_normalization(self, agent):
        from src.executors.extract import _normalize_loan_purpose
        assert _normalize_loan_purpose("buying") == "purchase"
        assert _normalize_loan_purpose("refinancing") == "refinance"
        assert _normalize_loan_purpose("Purchase") == "purchase"


class TestRateCalculation:
    """Test rate matrix and payment calculation."""

    def test_rate_lookup(self, agent):
        from src.executors.decide import _get_simulated_rate
        assert _get_simulated_rate("800_plus") == 6.0
        assert _get_simulated_rate("720_739") == 6.5
        assert _get_simulated_rate("below_620") == 8.0

    def test_monthly_payment(self, agent):
        from src.executors.decide import _calculate_monthly_payment
        payment = _calculate_monthly_payment(300000, 6.5, 360)
        assert 1800 < payment < 2000  # ~$1,896


class TestDatabaseOperations:
    """Test database CRUD operations."""

    def test_seed_officers(self, agent):
        session = get_session()
        try:
            from src.db import LoanOfficerModel
            count = session.query(LoanOfficerModel).count()
            assert count >= 5
        finally:
            session.close()

    def test_create_borrower(self, agent):
        from src.executors.decide import create_borrower
        from src.hydration import AgentState

        session = get_session()
        try:
            state = AgentState(
                user_id="test_b", user_type="borrower",
                collected_data={
                    "first_name": "Test", "last_name": "User",
                    "email": "test@example.com", "credit_score_range": "720_739"
                }
            )
            bid = create_borrower(state, session)
            assert bid is not None
        finally:
            session.close()
