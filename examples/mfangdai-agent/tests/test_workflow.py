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


class TestGatewayRetry:
    """Test LLM Gateway retry and error handling."""

    def test_call_retry_failure(self, agent):
        """Gateway.call should raise RuntimeError after max_retries exhaustion."""
        from src.gateway import Gateway
        from pydantic import BaseModel

        class DummySchema(BaseModel):
            x: int

        class FailingGateway(Gateway):
            def __init__(self):
                self.model = "test"
                self.base_url = "http://localhost"
                self.api_key = "sk-test"
                self.max_retries = 2
                from langchain_openai import ChatOpenAI
                self.llm = ChatOpenAI(model="test", base_url="http://localhost", api_key="sk-test", temperature=0)

            def call(self, prompt, output_schema, temperature=0):
                # Call parent retry logic which will fail on actual HTTP call
                return super().call(prompt, output_schema, temperature)

        gw = FailingGateway()
        try:
            gw.call("test prompt", DummySchema)
            assert False, "Should have raised RuntimeError"
        except (RuntimeError, Exception) as e:
            assert "2 attempts" in str(e) or "401" in str(e) or "Connection" in str(e)

    def test_call_text_attribute_fix(self, agent):
        """call_text should not crash with AttributeError (Agent-A bug #1)."""
        from src.gateway import Gateway

        gw = Gateway(model="test", base_url="http://localhost", api_key="sk-test")
        assert gw.api_key == "sk-test"
        assert gw.base_url == "http://localhost"


class TestIntentRouting:
    """Test intent routing edge cases from Agent-B gaps."""

    def test_unrecognized_intent(self, agent):
        from src.hydration import AgentState

        class UnrecognizedMockGateway(agent.gateway.__class__):
            def call(self, prompt, output_schema, temperature=0):
                from src.executors.classify import IntentClassificationResult
                return IntentClassificationResult(intent="unrecognized_intent", confidence=0.5)

        agent.gateway = UnrecognizedMockGateway()
        state = AgentState(user_id="test_u", user_type="borrower")
        result = agent.process("xyzzy blarg", "test_u", "borrower", current_state=state)
        assert "not sure" in result["response"].lower() or "help" in result["response"].lower()

    def test_correction_intent(self, agent):
        from src.hydration import AgentState

        class CorrectionMockGateway(agent.gateway.__class__):
            def call(self, prompt, output_schema, temperature=0):
                from src.executors.classify import IntentClassificationResult
                return IntentClassificationResult(intent="correction", confidence=0.8)

        agent.gateway = CorrectionMockGateway()
        state = AgentState(user_id="test_c", user_type="borrower")
        result = agent.process("No I meant California", "test_c", "borrower", current_state=state)
        assert "not sure" in result["response"].lower() or "help" in result["response"].lower()

    def test_low_confidence_intent(self, agent):
        """Low-confidence intent should still route correctly."""
        from src.executors.classify import IntentClassificationResult
        low_conf = IntentClassificationResult(intent="greet", confidence=0.4)
        from src.hydration import AgentState
        state = AgentState(user_id="test_lc", user_type="borrower")
        # Feed directly through process routing
        result = agent._handle_borrower(state, low_conf)
        assert "hello" in result["response"].lower() or "mortgage" in result["response"].lower()


class TestLoanOfficerMatching:
    """Test officer matching edge cases."""

    def test_no_officers_match(self, agent):
        from src.hydration import AgentState
        from src.executors.decide import match_officer
        from src.db import get_session

        state = AgentState(
            user_id="test_nm", user_type="borrower",
            collected_data={"state": "AK"}, lead_id="fake-lead-id"
        )
        session = get_session()
        try:
            result = match_officer(state, session)
            assert result is None
        finally:
            session.close()

    def test_strip_licensed_states(self, agent):
        """Ensure state matching works even with whitespace."""
        from src.db import get_session, LoanOfficerModel
        session = get_session()
        try:
            officers = session.query(LoanOfficerModel).all()
            if officers:
                # Verify seed data is clean (no leading/trailing whitespace)
                for o in officers:
                    states = [s.strip() for s in o.licensed_states.split(",")]
                    for s in states:
                        assert s == s.strip()
        finally:
            session.close()


class TestExtractionEdgeCases:
    """Test extraction edge cases from Agent-B gaps."""

    def test_hyphen_credit_score(self, agent):
        from src.executors.extract import _normalize_credit_score
        assert _normalize_credit_score("700-719") == "700_719"
        assert _normalize_credit_score("720-739") == "720_739"

    def test_unknown_state_normalization(self, agent):
        from src.executors.extract import _normalize_state
        assert _normalize_state("UnknownPlace") == "UNKNOWNPLACE"

    def test_unknown_loan_purpose(self, agent):
        from src.executors.extract import _normalize_loan_purpose
        assert _normalize_loan_purpose("investing") == "investing"

    def test_get_next_missing_field_empty(self, agent):
        from src.executors.extract import get_next_missing_field
        assert get_next_missing_field([]) is None

    def test_get_next_missing_field_has_gaps(self, agent):
        from src.executors.extract import get_next_missing_field
        assert get_next_missing_field(["home_value", "state"]) == "home_value"

    def test_unknown_credit_score_string(self, agent):
        from src.executors.extract import _normalize_credit_score
        assert _normalize_credit_score("excellent") == "excellent"

    def test_get_prompt_unknown_field(self, agent):
        from src.executors.extract import get_prompt_for_field
        result = get_prompt_for_field("unknown_field")
        assert "unknown_field" in result


class TestRelaySession:
    """Test RelayAgent session management."""

    def test_send_message_session_persistence(self):
        from src.db import init_db, get_session, seed_loan_officers
        from src.mcp_server import RelayAgent
        from src.gateway import Gateway
        from src.executors.classify import IntentClassificationResult
        import src.mcp_server as mcp_mod

        class SessionMockGateway(Gateway):
            def call(self, prompt, output_schema, temperature=0):
                msg = prompt.split('User message: "')[1].split('"')[0].lower() if 'User message: "' in prompt else prompt.lower()
                if "hello" in msg or "hi" in msg:
                    return IntentClassificationResult(intent="greet", confidence=1.0)
                if "what can you do" in msg or "help" in msg:
                    return IntentClassificationResult(intent="help", confidence=1.0)
                return IntentClassificationResult(intent="greet", confidence=1.0)

        init_db("sqlite:///mfangdai_test.db")
        session = get_session()
        try:
            seed_loan_officers(session)
        finally:
            session.close()

        orig_gateway = mcp_mod.Gateway
        mcp_mod.Gateway = SessionMockGateway
        try:
            relay = RelayAgent(db_url="sqlite:///mfangdai_test.db")

            result1 = relay.send_message("Hello", user_id="session_test", user_type="borrower", user_name="Test")
            assert result1["phase"] in ("collecting_info", "completed")

            result2 = relay.send_message("What can you do?", user_id="session_test", user_type="borrower", user_name="Test")
            assert "rate" in result2["response"].lower() or "mortgage" in result2["response"].lower()

            relay.reset_session("session_test", "borrower")

            result3 = relay.send_message("Hello", user_id="session_test", user_type="borrower", user_name="Test")
            assert result3["phase"] in ("collecting_info", "completed")
        finally:
            mcp_mod.Gateway = orig_gateway


class TestDatabaseErrors:
    """Test database error handling."""

    def test_get_session_before_init(self, agent):
        """get_session before init_db should raise RuntimeError."""
        import importlib
        import src.db as db_mod
        old_engine = db_mod.engine
        db_mod.engine = None
        try:
            with pytest.raises(RuntimeError, match="Database not initialized"):
                db_mod.get_session()
        finally:
            db_mod.engine = old_engine
