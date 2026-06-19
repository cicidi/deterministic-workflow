"""LangGraph State Machine for mfangdai loan lead collection chatbot.

Mermaid diagram:
```mermaid
stateDiagram-v2
    [*] --> collecting_info
    collecting_info --> info_collected : all fields filled
    collecting_info --> collecting_info : ask next missing field
    info_collected --> lead_created : persist lead
    lead_created --> officer_matched : match officer
    officer_matched --> quote_generated : generate quote
    quote_generated --> completed : deliver quote
    completed --> collecting_info : new request
    collecting_info --> help : help intent
    help --> collecting_info
    [*] --> error : exception
    error --> [*] : escalate/terminate
```
"""
import dataclasses
import logging
from typing import Optional

from src.db import get_session, LoanOfficerModel, RevealRequestModel
from src.executors.classify import (
    classify_intent,
    is_borrower_intent,
    is_officer_intent,
    IntentClassificationResult,
)
from src.executors.decide import (
    create_borrower,
    create_lead,
    generate_quote,
    get_available_leads_for_officer,
    match_officer,
)
from src.executors.extract import (
    extract_and_merge,
    get_next_missing_field,
    get_prompt_for_field,
)
from src.executors.respond import (
    format_help_response,
    format_leads_response,
    format_quote_response,
)
from src.gateway import Gateway
from src.hydration import AgentState

logger = logging.getLogger(__name__)


def _clone(state: AgentState, **overrides) -> AgentState:
    """Copy-on-Write: return new AgentState with overrides applied."""
    return dataclasses.replace(state, **overrides)


def _error_response(state: AgentState, error_msg: str) -> dict:
    """Unified error handler — escalates or terminates."""
    logger.error(f"Agent error: {error_msg}")
    state = _clone(state, error=error_msg, phase="error")
    response = (
        f"I encountered an error processing your request. "
        f"Please try again or contact support. ({error_msg[:80]})"
    )
    state.messages.append({"role": "assistant", "content": response})
    return {"response": response, "state": state, "phase": "error"}


class Agent:
    """Main agent wrapping the LangGraph state machine."""

    def __init__(self, gateway: Gateway):
        self.gateway = gateway
        from src.knowledge import KnowledgePool
        self.knowledge = KnowledgePool()

    def process(
        self,
        user_message: str,
        user_id: str,
        user_type: str,
        user_name: str = "",
        current_state: Optional[AgentState] = None,
    ) -> dict:
        """Process one user message through the full pipeline."""
        state = _clone(current_state) if current_state else AgentState(
            user_id=user_id, user_type=user_type, user_name=user_name, phase="collecting_info"
        )
        state.messages.append({"role": "user", "content": user_message})

        try:
            intent_result = classify_intent(state, self.gateway, user_message)
            intent = intent_result.intent
            logger.info(f"Intent: {intent}, confidence: {intent_result.confidence}")

            if intent == "greet":
                greeting = f"Hello! {format_help_response(user_type)}"
                state = _clone(state, messages=state.messages + [{"role": "assistant", "content": greeting}])
                return {"response": greeting, "state": state, "phase": state.phase}

            if intent == "help":
                help_text = format_help_response(user_type)
                state = _clone(state, phase="collecting_info",
                               messages=state.messages + [{"role": "assistant", "content": help_text}])
                return {"response": help_text, "state": state, "phase": "collecting_info"}

            if intent in ("unrecognized_intent", "correction"):
                fallback = "I'm not sure I understood. " + format_help_response(user_type)
                state = _clone(state, messages=state.messages + [{"role": "assistant", "content": fallback}])
                return {"response": fallback, "state": state, "phase": state.phase}

            if is_borrower_intent(intent):
                return self._handle_borrower(state, intent_result)
            if is_officer_intent(intent):
                return self._handle_officer(state, intent_result)

            if intent == "ask_mortgage_question":
                return self._handle_knowledge_question(state, user_message)

            fallback = format_help_response(user_type)
            state = _clone(state, messages=state.messages + [{"role": "assistant", "content": fallback}])
            return {"response": fallback, "state": state, "phase": state.phase}

        except Exception as e:
            return _error_response(state, str(e))

    # ── Knowledge handler ──

    def _handle_knowledge_question(self, state: AgentState, user_message: str) -> dict:
        """Answer mortgage questions from the knowledge pool, with fallback to contact support."""
        answer = self.knowledge.answer(user_message)
        if "don't have" in answer:
            answer += (
                "\n\nIf you'd like, I can forward your question to our support team at help@mratequote.com, "
                "or broadcast it to our network of loan officers who may be able to help. "
                "Would you like me to do that?"
            )
        state = _clone(state, messages=state.messages + [{"role": "assistant", "content": answer}])
        return {"response": answer, "state": state, "phase": state.phase}

    def _handle_borrower(self, state: AgentState, intent_result: IntentClassificationResult) -> dict:
        intent = intent_result.intent

        if intent == "check_quote_status":
            response = (
                "Your lead has been submitted and is being reviewed by loan officers in your area. "
                "You'll receive quotes as they come in. Is there anything else I can help with?"
            )
            state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
            return {"response": response, "state": state, "phase": state.phase}

        if intent == "ask_mortgage_question":
            user_msg = state.messages[-1]["content"] if state.messages else ""
            return self._handle_knowledge_question(state, user_msg)

        if intent == "ask_about_rates" and state.phase == "collecting_info" and not state.collected_data:
            prompt = get_prompt_for_field("loan_purpose")
            response = f"I'd be happy to help you get a mortgage rate quote! Let me ask a few questions.\n\n{prompt}"
            state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
            return {"response": response, "state": state, "phase": state.phase}

        if state.phase in ("collecting_info", "info_collected"):
            return self._collect_loan_info(state, intent_result)

        response = "Got it. Your information has been updated. Anything else?"
        state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
        return {"response": response, "state": state, "phase": state.phase}

    def _collect_loan_info(self, state: AgentState, intent_result: IntentClassificationResult) -> dict:
        """Collect loan info, create lead + match officer + generate quote when complete."""
        session = get_session()
        try:
            merged, missing = extract_and_merge(state, intent_result)
            state = _clone(state, collected_data=merged)

            if missing:
                prompt = get_prompt_for_field(get_next_missing_field(missing))
                state = _clone(state, messages=state.messages + [{"role": "assistant", "content": prompt}])
                return {"response": prompt, "state": state, "phase": "collecting_info"}

            # All fields collected
            state = _clone(state, phase="info_collected")
            logger.info("All required fields collected, creating lead")
            return self._create_lead_and_quote(state, session)
        finally:
            session.close()

    def _create_lead_and_quote(self, state: AgentState, session) -> dict:
        """Create borrower, lead, match officer, generate quote."""
        borrower_id = create_borrower(state, session)
        state = _clone(state, borrower_id=borrower_id)
        lead_id = create_lead(state, session, borrower_id)
        state = _clone(state, lead_id=lead_id, phase="lead_created")
        logger.info(f"Lead created: {lead_id}")

        officer = match_officer(state, session)
        if not officer:
            no_match = (
                f"Your information has been collected, but I couldn't find a licensed loan officer "
                f"in {state.collected_data.get('state')} right now. We'll notify you when one becomes available."
            )
            state = _clone(state, messages=state.messages + [{"role": "assistant", "content": no_match}])
            return {"response": no_match, "state": state, "phase": "lead_created"}

        state = _clone(state, loan_officer_id=officer["id"], phase="officer_matched")
        logger.info(f"Officer matched: {officer['first_name']} {officer['last_name']}")

        rate, payment, term = generate_quote(state, session)
        quote = {
            "interest_rate": rate, "monthly_payment": payment,
            "loan_term_months": term, "apr": round(rate + 0.15, 2), "officer": officer,
        }
        state = _clone(state, quote=quote, phase="quote_generated")
        response = format_quote_response(state)
        state = _clone(state, phase="completed",
                       messages=state.messages + [{"role": "assistant", "content": response}])
        return {"response": response, "state": state, "phase": "completed"}

    # ── Officer handlers (each ≤50 lines) ──

    def _handle_officer(self, state: AgentState, intent_result: IntentClassificationResult) -> dict:
        intent = intent_result.intent

        if intent == "ask_mortgage_question":
            user_msg = state.messages[-1]["content"] if state.messages else ""
            return self._handle_knowledge_question(state, user_msg)

        if intent == "ask_for_leads":
            return self._officer_ask_for_leads(state)
        if intent == "submit_quote":
            return self._officer_submit_quote(state)
        if intent == "register_loan_officer":
            return self._officer_register(state, intent_result)

        response = format_help_response(state.user_type)
        state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
        return {"response": response, "state": state, "phase": state.phase}

    def _officer_ask_for_leads(self, state: AgentState) -> dict:
        session = get_session()
        try:
            officers = session.query(LoanOfficerModel).all()
            officer = next((o for o in officers if state.user_id in (o.email, o.id)), officers[0] if officers else None)
            if officer:
                leads = get_available_leads_for_officer(officer.licensed_states, session)
                response = format_leads_response(leads)
            else:
                response = "Please register first. Say 'I want to register as a loan officer'."
            state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
            return {"response": response, "state": state, "phase": state.phase}
        finally:
            session.close()

    def _officer_submit_quote(self, state: AgentState) -> dict:
        response = "Quote received! It will be forwarded to the borrower. Thank you."
        state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
        return {"response": response, "state": state, "phase": state.phase}

    def _officer_register(self, state: AgentState, intent_result: IntentClassificationResult) -> dict:
        entities = intent_result.entities or {}
        name = entities.get("first_name", "New") + " " + entities.get("last_name", "Officer")
        response = (
            f"Thanks for your interest, {name}! To complete registration, "
            f"I'll need your NMLS number, email, and the states you're licensed in. "
            f"Please provide those when ready."
        )
        state = _clone(state, messages=state.messages + [{"role": "assistant", "content": response}])
        return {"response": response, "state": state, "phase": state.phase}
