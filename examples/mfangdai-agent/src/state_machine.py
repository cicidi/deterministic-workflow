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
```
"""
import logging
from typing import Optional

from src.db import get_session
from src.executors.classify import (
    IntentClassificationResult,
    classify_intent,
    is_borrower_intent,
    is_officer_intent,
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


class Agent:
    """Main agent wrapping the LangGraph state machine."""

    def __init__(self, gateway: Gateway):
        self.gateway = gateway

    def process(
        self,
        user_message: str,
        user_id: str,
        user_type: str,
        user_name: str = "",
        current_state: Optional[AgentState] = None,
    ) -> dict:
        """Process one user message through the full pipeline. Returns response dict."""
        state = current_state or AgentState(
            user_id=user_id,
            user_type=user_type,
            user_name=user_name,
            phase="collecting_info",
        )
        state.messages.append({"role": "user", "content": user_message})

        # Layer 1: Classify intent
        intent_result = classify_intent(state, self.gateway, user_message)
        intent = intent_result.intent
        logger.info(f"Intent: {intent}, confidence: {intent_result.confidence}")

        # Route based on intent
        if intent == "greet":
            greeting = f"Hello! {format_help_response(user_type)}"
            state.messages.append({"role": "assistant", "content": greeting})
            return {"response": greeting, "state": state, "phase": state.phase}

        if intent == "help":
            help_text = format_help_response(user_type)
            state.messages.append({"role": "assistant", "content": help_text})
            state.phase = "collecting_info"
            return {"response": help_text, "state": state, "phase": state.phase}

        if intent in ("unrecognized_intent", "correction"):
            fallback = "I'm not sure I understood. " + format_help_response(user_type)
            state.messages.append({"role": "assistant", "content": fallback})
            return {"response": fallback, "state": state, "phase": state.phase}

        # Borrower flows
        if is_borrower_intent(intent):
            return self._handle_borrower(state, intent_result)

        # Loan Officer flows
        if is_officer_intent(intent):
            return self._handle_officer(state, intent_result)

        fallback = format_help_response(user_type)
        state.messages.append({"role": "assistant", "content": fallback})
        return {"response": fallback, "state": state, "phase": state.phase}

    def _handle_borrower(self, state: AgentState, intent_result: IntentClassificationResult) -> dict:
        """Handle borrower-side conversation flows."""
        intent = intent_result.intent
        session = get_session()

        try:
            if intent == "check_quote_status":
                response = (
                    "Your lead has been submitted and is being reviewed by loan officers in your area. "
                    "You'll receive quotes as they come in. Is there anything else I can help with?"
                )
                state.messages.append({"role": "assistant", "content": response})
                return {"response": response, "state": state, "phase": state.phase}

            if intent == "ask_about_rates" and state.phase == "collecting_info" and not state.collected_data:
                # Fresh start — first question
                response = "I'd be happy to help you get a mortgage rate quote! Let me ask a few questions.\n\n"
                response += get_prompt_for_field("loan_purpose")
                state.phase = "collecting_info"
                state.messages.append({"role": "assistant", "content": response})
                return {"response": response, "state": state, "phase": state.phase}

            if state.phase in ("collecting_info", "info_collected"):
                merged, missing = extract_and_merge(state, intent_result)
                state.collected_data = merged

                if missing:
                    next_field = get_next_missing_field(missing)
                    prompt = get_prompt_for_field(next_field)
                    state.phase = "collecting_info"
                    state.messages.append({"role": "assistant", "content": prompt})
                    return {"response": prompt, "state": state, "phase": state.phase}

                # All fields collected — transition to info_collected
                state.phase = "info_collected"
                logger.info("All required fields collected, creating lead")

                # Create borrower
                borrower_id = create_borrower(state, session)
                state.user_id = borrower_id

                # Create lead
                lead_id = create_lead(state, session, borrower_id)
                state.lead_id = lead_id
                state.phase = "lead_created"
                logger.info(f"Lead created: {lead_id}")

                # Match officer
                officer = match_officer(state, session)
                if officer:
                    state.loan_officer_id = officer["id"]
                    state.phase = "officer_matched"
                    logger.info(f"Officer matched: {officer['first_name']} {officer['last_name']}")

                    # Generate quote
                    rate, payment, term = generate_quote(state, session)
                    state.quote = {
                        "interest_rate": rate,
                        "monthly_payment": payment,
                        "loan_term_months": term,
                        "apr": round(rate + 0.15, 2),
                        "officer": officer,
                    }
                    state.phase = "quote_generated"

                    response = format_quote_response(state)
                    state.phase = "completed"
                    state.messages.append({"role": "assistant", "content": response})
                    return {"response": response, "state": state, "phase": "completed"}
                else:
                    no_match = (
                        f"Your information has been collected, but I couldn't find a licensed loan officer "
                        f"in {state.collected_data.get('state')} right now. We'll notify you when one becomes available."
                    )
                    state.messages.append({"role": "assistant", "content": no_match})
                    state.phase = "lead_created"
                    return {"response": no_match, "state": state, "phase": "lead_created"}

            # Default: provide info
            merged, missing = extract_and_merge(state, intent_result)
            state.collected_data = merged
            if missing:
                next_field = get_next_missing_field(missing)
                prompt = get_prompt_for_field(next_field)
                state.messages.append({"role": "assistant", "content": prompt})
                return {"response": prompt, "state": state, "phase": "collecting_info"}

            response = f"Got it. Your information has been updated. Anything else?"
            state.messages.append({"role": "assistant", "content": response})
            return {"response": response, "state": state, "phase": state.phase}
        finally:
            session.close()

    def _handle_officer(self, state: AgentState, intent_result: IntentClassificationResult) -> dict:
        """Handle loan officer-side conversation flows."""
        intent = intent_result.intent
        session = get_session()

        try:
            if intent == "ask_for_leads":
                from src.db import LoanOfficerModel

                state_param = (intent_result.entities or {}).get("state", "")
                officers = session.query(LoanOfficerModel).all()

                officer = None
                for o in officers:
                    if o.email and state.user_id in (o.email, o.id):
                        officer = o
                        break

                if not officer:
                    # Use any officer for demo
                    officer = officers[0] if officers else None

                if officer:
                    leads = get_available_leads_for_officer(officer.licensed_states, session)
                    response = format_leads_response(leads)
                else:
                    response = "Please register first to see available leads. Say 'I want to register as a loan officer'."

                state.messages.append({"role": "assistant", "content": response})
                return {"response": response, "state": state, "phase": state.phase}

            if intent == "submit_quote":
                response = "Quote received! It will be forwarded to the borrower. Thank you."
                state.messages.append({"role": "assistant", "content": response})
                return {"response": response, "state": state, "phase": state.phase}

            if intent == "register_loan_officer":
                entities = intent_result.entities or {}
                name = entities.get("first_name", "New") + " " + entities.get("last_name", "Officer")
                response = (
                    f"Thanks for your interest, {name}! To complete registration, "
                    f"I'll need your NMLS number, email, and the states you're licensed in. "
                    f"Please provide those when ready."
                )
                state.messages.append({"role": "assistant", "content": response})
                return {"response": response, "state": state, "phase": state.phase}

            response = format_help_response(state.user_type)
            state.messages.append({"role": "assistant", "content": response})
            return {"response": response, "state": state, "phase": state.phase}
        finally:
            session.close()
