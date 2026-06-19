"""Layer 3: Response generation — LLM allowed, temperature=0.3."""
from src.hydration import AgentState

RESPOND_SYSTEM_PROMPT = """You are a helpful mortgage assistant agent for mRateQuote. 

Your tone is professional, warm, and concise. You help home buyers get mortgage rate quotes and connect them with licensed loan officers.

Guidelines:
- If you just collected information from the borrower, confirm what you have before proceeding
- When presenting a rate quote, clearly show: interest rate, monthly payment, loan term, APR
- Never make up rates — use the data provided to you
- If asked about loan officer details, share what's available
- Keep responses under 200 words unless presenting a quote
- Always end with a clear next step or question
"""


def build_responder_prompt(state: AgentState, context: dict) -> str:
    """Build a prompt for the response generation LLM."""
    return RESPOND_SYSTEM_PROMPT


def format_quote_response(state: AgentState) -> str:
    """Build a deterministic quote response without LLM."""
    cd = state.collected_data
    q = state.quote or {}

    loan_purpose_label = "Purchase" if cd.get("loan_purpose") == "purchase" else "Refinance"
    rate = q.get("interest_rate", "N/A")
    payment = q.get("monthly_payment", "N/A")
    term = q.get("loan_term_months", 360)
    apr = q.get("apr", "N/A")
    officer = q.get("officer", {})

    return (
        f"Here is your rate quote:\n\n"
        f"- Loan Type: {int(term/12)}-Year Fixed Conventional\n"
        f"- Loan Purpose: {loan_purpose_label}\n"
        f"- Loan Amount: ${cd.get('loan_amount', 0):,.0f}\n"
        f"- Interest Rate: {rate}%\n"
        f"- APR: {apr}%\n"
        f"- Estimated Monthly Payment: ${payment:,.2f}/month\n"
        f"- Based on credit score: {cd.get('credit_score_range', 'N/A')}\n\n"
        f"Your quote was provided by {officer.get('first_name', 'a')} {officer.get('last_name', 'licensed loan officer')}"
        f" from {officer.get('company_name', 'our network')}.\n\n"
        f"Would you like to proceed with this loan officer, or would you like to explore other options?"
    )


def format_leads_response(leads: list[dict]) -> str:
    """Build a response listing available leads for a loan officer."""
    if not leads:
        return "There are currently no new leads available in your licensed states. Check back soon!"

    lines = [f"I found {len(leads)} available leads:\n"]
    for i, lead in enumerate(leads, 1):
        lines.append(
            f"{i}. {lead['loan_purpose'].title()} — "
            f"${lead['loan_amount']:,.0f} loan, "
            f"${lead['home_value']:,.0f} property value, "
            f"Credit: {lead['credit_score_range']}, "
            f"State: {lead['state']}"
        )
    lines.append("\nReply with the lead number and your quote (e.g., 'Offer 6.5% for lead #2').")
    return "\n".join(lines)


def format_help_response(user_type: str) -> str:
    """Build help text based on user type."""
    if user_type == "borrower":
        return (
            "I can help you with:\n"
            "- Getting a mortgage rate quote — just tell me you want to check rates\n"
            "- Providing info about your property (value, loan amount, credit score, state)\n"
            "- Checking the status of a previous inquiry\n\n"
            "What would you like to do?"
        )
    else:
        return (
            "I can help you with:\n"
            "- Viewing available leads in your licensed states — ask 'show me leads'\n"
            "- Submitting rate quotes for leads — tell me the lead number and your rate\n"
            "- Registering as a loan officer — say 'I want to register'\n\n"
            "What would you like to do?"
        )
