"""Layer 1: Intent classification — LLM-primary, temperature=0."""
from enum import Enum

from pydantic import BaseModel, Field

from src.hydration import AgentState

SYSTEM_INTENTS = [
    "greet",
    "help",
    "ask_about_rates",
    "provide_loan_info",
    "check_quote_status",
    "ask_for_leads",
    "submit_quote",
    "register_loan_officer",
    "correction",
    "unrecognized_intent",
]

LEAD_REQUIRED_FIELDS = [
    "loan_purpose",
    "home_value",
    "loan_amount",
    "state",
    "credit_score_range",
]


class IntentClassificationResult(BaseModel):
    intent: str = Field(description="Classified intent")
    confidence: float = Field(description="Confidence score 0.0-1.0", default=1.0)
    entities: dict = Field(description="Extracted entities", default_factory=dict)
    missing_fields: list[str] = Field(description="Required fields still missing", default_factory=list)


CLASSIFY_PROMPT_TEMPLATE = """You are a mortgage assistant agent. Classify the user's intent.

User type: {user_type}
Current phase: {phase}
Collected data so far: {collected_data}

User message: "{message}"

Classify into one of:
- ask_about_rates: user wants mortgage rate quote info
- provide_loan_info: user provides property/loan details (home value, loan amount, credit score, state, etc.)
- check_quote_status: user checking on previous application
- ask_for_leads: loan officer wants available leads
- submit_quote: loan officer providing rate quote
- register_loan_officer: loan officer wants to register
- greet: greeting/small talk
- help: asking what the agent can do
- correction: correcting previous info
- unrecognized_intent: doesn't match any

Also extract any entities from the message:
- loan_purpose: "purchase" or "refinance"
- home_value: number (e.g., 500000)
- loan_amount: number (e.g., 400000)
- state: 2-letter state code (e.g., CA, NY)
- credit_score_range: "below_620", "620_639", "640_659", "660_679", "680_699", "700_719", "720_739", "740_759", "760_779", "780_799", "800_plus"
- zip_code: string
- employment_status: "employed", "self_employed", "retired", "unemployed"
- annual_household_income: number
- first_name: string
- last_name: string
- interest_rate: number (e.g., 6.5)
- loan_term_months: integer (e.g., 360)

If user_type is "loan_officer" and message mentions states (e.g., "leads for California"), extract the state.
If user_type is "loan_officer" and message contains a rate quote, extract interest_rate and loan_term_months.

Return the intent, confidence, extracted entities, and list of missing required fields (for ask_about_rates flow: loan_purpose, home_value, loan_amount, state, credit_score_range)."""


def classify_intent(
    state: AgentState,
    gateway,
    user_message: str,
) -> IntentClassificationResult:
    """Classify user intent via LLM."""
    prompt = CLASSIFY_PROMPT_TEMPLATE.format(
        user_type=state.user_type,
        phase=state.phase,
        collected_data=state.collected_data,
        message=user_message,
    )
    return gateway.call(prompt, IntentClassificationResult)


def is_borrower_intent(intent: str) -> bool:
    return intent in ("ask_about_rates", "provide_loan_info", "check_quote_status", "greet", "help")


def is_officer_intent(intent: str) -> bool:
    return intent in ("ask_for_leads", "submit_quote", "register_loan_officer")
