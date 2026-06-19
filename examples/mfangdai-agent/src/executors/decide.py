"""Layer 2: Business logic — 100% deterministic code executors."""
import logging
import math
from typing import Optional

from sqlalchemy.orm import Session

from src.db import (
    BorrowerModel,
    LeadAssignmentModel,
    LeadModel,
    LoanOfficerModel,
    QuoteModel,
)
from src.hydration import AgentState

logger = logging.getLogger(__name__)

# Simulated rate matrix: (min_credit_range, base_rate)
RATE_MATRIX = [
    ("800_plus", 6.0),
    ("780_799", 6.1),
    ("760_779", 6.2),
    ("740_759", 6.3),
    ("720_739", 6.5),
    ("700_719", 6.7),
    ("680_699", 6.9),
    ("660_679", 7.1),
    ("640_659", 7.3),
    ("620_639", 7.5),
    ("below_620", 8.0),
]


def _get_simulated_rate(credit_score_range: str) -> float:
    """Deterministic rate lookup based on credit score range."""
    for cr, rate in RATE_MATRIX:
        if credit_score_range == cr:
            return rate
    return 7.0


def _calculate_monthly_payment(loan_amount: float, annual_rate: float, term_months: int = 360) -> float:
    """Standard amortization formula."""
    monthly_rate = (annual_rate / 100) / 12
    if monthly_rate == 0:
        return loan_amount / term_months
    payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** term_months) / (
        (1 + monthly_rate) ** term_months - 1
    )
    return round(payment, 2)


def create_borrower(state: AgentState, session: Session) -> str:
    """Create a borrower record from collected data. Returns borrower_id."""
    import uuid as _uuid

    name_parts = (state.user_name or state.collected_data.get("first_name", "User")).split()
    first = name_parts[0] if name_parts else "User"
    last = name_parts[1] if len(name_parts) > 1 else ""

    borrower = BorrowerModel(
        first_name=state.collected_data.get("first_name", first),
        last_name=state.collected_data.get("last_name", last),
        email=state.collected_data.get("email", f"{state.user_id}-{_uuid.uuid4().hex[:8]}@placeholder.com"),
        phone=state.collected_data.get("phone"),
        credit_score_range=state.collected_data.get("credit_score_range"),
    )
    session.add(borrower)
    session.commit()
    return borrower.id


def create_lead(state: AgentState, session: Session, borrower_id: str) -> str:
    """Persist lead to database. Returns lead_id."""
    cd = state.collected_data
    lead = LeadModel(
        borrower_id=borrower_id,
        loan_purpose=cd.get("loan_purpose", "purchase"),
        home_value=float(cd.get("home_value", 0)),
        loan_amount=float(cd.get("loan_amount", 0)),
        state=cd.get("state", ""),
        zip_code=cd.get("zip_code"),
        credit_score_range=cd.get("credit_score_range", ""),
        loan_type=cd.get("loan_type", "conventional"),
        employment_status=cd.get("employment_status"),
        annual_household_income=float(cd["annual_household_income"]) if cd.get("annual_household_income") else None,
        message=cd.get("message"),
        first_time_home_buyer=cd.get("first_time_home_buyer"),
        current_mortgage_rate=float(cd["current_mortgage_rate"]) if cd.get("current_mortgage_rate") else None,
    )
    session.add(lead)
    session.commit()
    return lead.id


def match_officer(state: AgentState, session: Session) -> Optional[dict]:
    """Find a loan officer licensed in the lead's state. Returns officer dict or None."""
    target_state = state.collected_data.get("state", "")
    officers = session.query(LoanOfficerModel).all()

    for officer in officers:
        licensed = [s.strip() for s in officer.licensed_states.split(",")] if officer.licensed_states else []
        if target_state in licensed:
            # Assign
            assignment = LeadAssignmentModel(
                lead_id=state.lead_id,
                loan_officer_id=officer.id,
            )
            session.add(assignment)
            session.commit()
            return {
                "id": officer.id,
                "first_name": officer.first_name,
                "last_name": officer.last_name,
                "nmls": officer.nmls,
                "email": officer.email,
                "company_name": officer.company_name,
                "licensed_states": officer.licensed_states,
                "products_provided": officer.products_provided,
            }
    return None


def generate_quote(state: AgentState, session: Session) -> tuple[float, float, float]:
    """Generate simulated quote using rate matrix. Returns (interest_rate, monthly_payment, loan_term)."""
    credit = state.collected_data.get("credit_score_range", "700_719")
    loan_amount = float(state.collected_data.get("loan_amount", 0))
    term = 360  # 30-year fixed default

    rate = _get_simulated_rate(credit)
    payment = _calculate_monthly_payment(loan_amount, rate, term)

    # Persist quote
    if state.loan_officer_id and state.lead_id:
        quote = QuoteModel(
            lead_id=state.lead_id,
            loan_officer_id=state.loan_officer_id,
            interest_rate=rate,
            loan_term_months=term,
            monthly_payment=payment,
            apr=round(rate + 0.15, 2),
            product_name=f"{int(term/12)}-Year Fixed Conventional",
        )
        session.add(quote)
        session.commit()

    return rate, payment, term


def get_available_leads_for_officer(officer_licensed_states: str, session: Session) -> list[dict]:
    """Get leads available for a loan officer based on licensed states."""
    states = [s.strip() for s in officer_licensed_states.split(",")]
    leads = session.query(LeadModel).filter(LeadModel.state.in_(states)).all()
    return [
        {
            "id": lead.id,
            "loan_purpose": lead.loan_purpose,
            "home_value": lead.home_value,
            "loan_amount": lead.loan_amount,
            "state": lead.state,
            "credit_score_range": lead.credit_score_range,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        }
        for lead in leads
    ]
