"""Simulated LLM-driven functional tests.

Multi-model support via environment variables:
  LLM_MODEL     — model name (deepseek-v4-flash | gpt-5-nano | ...)
  LLM_BASE_URL  — API base URL
  LLM_API_KEY   — API key

Quick switch:
  # DeepSeek (default)
  export LLM_MODEL=deepseek-v4-flash LLM_BASE_URL=https://api.deepseek.com/v1 LLM_API_KEY=sk-...

  # GPT-5 Nano
  export LLM_MODEL=gpt-5-nano LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-...
"""
import os
import pytest

from src.db import init_db, get_session, seed_loan_officers, Base
from src.gateway import Gateway
from src.state_machine import Agent
from tests.sim_client import (
    PERSONA_PURCHASE_CA,
    PERSONA_REFINANCE_TX,
    PERSONA_OFFICER_ONBOARDING,
    run_borrower_scenario,
    run_officer_scenario,
)

needs_llm = pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"),
    reason="LLM_API_KEY not set — export LLM_API_KEY=sk-... to run simulated LLM tests",
)


@pytest.fixture(scope="module")
def live_agent():
    init_db("sqlite:///mfangdai_sim.db")
    session = get_session()
    try:
        Base.metadata.create_all(session.get_bind())
        seed_loan_officers(session)
    finally:
        session.close()
    gw = Gateway(
        model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=os.environ.get("LLM_API_KEY", "sk-placeholder"),
    )
    return Agent(gw)


class TestSimulatedBorrower:
    """End-to-end tests with LLM-simulated borrower persona."""

    @needs_llm
    def test_simulated_purchase_ca(self, live_agent):
        """Alice (CA, 780 credit, $800k home, $400k loan) gets a quote."""
        result = run_borrower_scenario(
            live_agent, live_agent.gateway, PERSONA_PURCHASE_CA, max_turns=10
        )
        print(f"\nConversation ({len(result['turns'])} turns):")
        for t in result["turns"]:
            print(f"  User: {t['user']}")
            print(f"  Agent: {t['agent'][:120]}...")
        assert result["success"], f"Expected completed phase, got: {result['phase']}"
        assert result["state"].phase == "completed"
        assert result["state"].quote is not None

    @needs_llm
    def test_simulated_refinance_tx(self, live_agent):
        """Bob (TX, 680 credit, $500k home, $300k refinance) gets a quote."""
        result = run_borrower_scenario(
            live_agent, live_agent.gateway, PERSONA_REFINANCE_TX, max_turns=10
        )
        print(f"\nConversation ({len(result['turns'])} turns):")
        for t in result["turns"]:
            print(f"  User: {t['user']}")
            print(f"  Agent: {t['agent'][:120]}...")
        assert result["success"], f"Expected completed phase, got: {result['phase']}"
        assert result["state"].collected_data.get("loan_purpose") == "refinance"


class TestSimulatedOfficer:
    """End-to-end tests with LLM-simulated loan officer persona."""

    @needs_llm
    def test_simulated_officer_onboarding(self, live_agent):
        """Mike (CA/OR/WA officer) registers on the platform."""
        result = run_officer_scenario(
            live_agent, live_agent.gateway, PERSONA_OFFICER_ONBOARDING, max_turns=8
        )
        print(f"\nConversation ({len(result['turns'])} turns):")
        for t in result["turns"]:
            print(f"  User: {t['user']}")
            print(f"  Agent: {t['agent'][:120]}...")
        assert result["success"], f"Expected onboarding flow, got phase: {result['phase']}"
