"""Placeholder for MCP server wrapping the agent.

Relay mode: Claude forwards raw messages through MCP to the agent.
The MCP server exposes a `send_message` tool.
"""
import asyncio
import json
import logging
from typing import Optional

from src.db import init_db, seed_loan_officers, get_session
from src.gateway import Gateway
from src.hydration import AgentState
from src.state_machine import Agent

logger = logging.getLogger(__name__)


# In-memory session store for conversation continuity
_sessions: dict[str, AgentState] = {}


class RelayAgent:
    """Relay agent that can be wrapped by MCP server or used standalone."""

    def __init__(self, db_url: str = "sqlite:///mfangdai_test.db"):
        init_db(db_url)
        session = get_session()
        try:
            seed_loan_officers(session)
        finally:
            session.close()
        self.gateway = Gateway()
        self.agent = Agent(self.gateway)

    def send_message(
        self,
        message: str,
        user_id: str,
        user_type: str = "borrower",
        user_name: str = "",
    ) -> dict:
        """Process a user message through the agent. Returns response with state."""
        session_key = f"{user_type}:{user_id}"
        current_state = _sessions.get(session_key)
        result = self.agent.process(
            user_message=message,
            user_id=user_id,
            user_type=user_type,
            user_name=user_name,
            current_state=current_state,
        )
        _sessions[session_key] = result["state"]
        return {
            "response": result["response"],
            "phase": result["phase"],
            "collected_data": result["state"].collected_data,
        }

    def reset_session(self, user_id: str, user_type: str = "borrower"):
        """Clear conversation session for a user."""
        session_key = f"{user_type}:{user_id}"
        _sessions.pop(session_key, None)


# CLI entry point for testing without MCP server
def run_cli():
    """Simple CLI for testing the agent."""
    print("=" * 60)
    print("  mRateQuote Mortgage Agent")
    print("  Type 'quit' to exit, 'reset' to clear session")
    print("=" * 60)

    agent = RelayAgent()

    user_type = input("\nAre you a (b)orrower or (l)oan officer? ").strip().lower()
    user_type = "borrower" if user_type.startswith("b") else "loan_officer"
    user_id = input("Your name/ID: ").strip() or f"user_{user_type}"

    print(f"\nWelcome, {user_id}! ({user_type})")
    print(format_help_response(user_type))

    while True:
        msg = input("\n> ").strip()
        if not msg:
            continue
        if msg.lower() == "quit":
            break
        if msg.lower() == "reset":
            agent.reset_session(user_id, user_type)
            print("Session reset.")
            continue

        result = agent.send_message(msg, user_id, user_type, user_id)
        print(f"\nAgent: {result['response']}")


from src.executors.respond import format_help_response

if __name__ == "__main__":
    run_cli()
