"""Database layer: SQLAlchemy models + SQLite setup for mfangdai agent."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BorrowerModel(Base):
    __tablename__ = "borrower"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    credit_score_range: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LoanOfficerModel(Base):
    __tablename__ = "loan_officer"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    nmls: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    licensed_states: Mapped[str] = mapped_column(String, nullable=False)  # comma-separated
    company_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    products_provided: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # comma-separated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LeadModel(Base):
    __tablename__ = "lead"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    borrower_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("borrower.id"), nullable=True)
    loan_purpose: Mapped[str] = mapped_column(String, nullable=False)
    home_value: Mapped[float] = mapped_column(Float, nullable=False)
    loan_amount: Mapped[float] = mapped_column(Float, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    zip_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    credit_score_range: Mapped[str] = mapped_column(String, nullable=False)
    loan_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    employment_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    annual_household_income: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_time_home_buyer: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_real_estate_agent: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    current_mortgage_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LeadAssignmentModel(Base):
    __tablename__ = "lead_assignment"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("lead.id"), nullable=False)
    loan_officer_id: Mapped[str] = mapped_column(String, ForeignKey("loan_officer.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QuoteModel(Base):
    __tablename__ = "quote"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("lead.id"), nullable=False)
    loan_officer_id: Mapped[str] = mapped_column(String, ForeignKey("loan_officer.id"), nullable=False)
    interest_rate: Mapped[float] = mapped_column(Float, nullable=False)
    loan_term_months: Mapped[int] = mapped_column(Integer, nullable=False, default=360)
    monthly_payment: Mapped[float] = mapped_column(Float, nullable=False)
    apr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# Database setup
engine = None


def init_db(db_url: str = "sqlite:///mfangdai_test.db"):
    global engine
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session() -> Session:
    if engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return Session(engine)


# Seed data: 5 fake loan officers
SEED_LOAN_OFFICERS = [
    {
        "first_name": "Michael",
        "last_name": "Chen",
        "nmls": "NMLS-100001",
        "email": "michael.chen@mortgagepro.com",
        "phone": "415-555-0101",
        "licensed_states": "CA,OR,WA",
        "company_name": "Golden Gate Mortgage",
        "products_provided": "conventional,FHA,VA,jumbo",
    },
    {
        "first_name": "Sarah",
        "last_name": "Johnson",
        "nmls": "NMLS-100002",
        "email": "sarah.j@lendingtree.com",
        "phone": "212-555-0102",
        "licensed_states": "NY,NJ,CT,PA",
        "company_name": "Empire Lending Group",
        "products_provided": "conventional,FHA,jumbo",
    },
    {
        "first_name": "David",
        "last_name": "Martinez",
        "nmls": "NMLS-100003",
        "email": "david.m@texashomeloans.com",
        "phone": "512-555-0103",
        "licensed_states": "TX,OK,LA",
        "company_name": "Lone Star Home Loans",
        "products_provided": "conventional,FHA,VA,USDA",
    },
    {
        "first_name": "Emily",
        "last_name": "Williams",
        "nmls": "NMLS-100004",
        "email": "emily.w@floridamortgage.com",
        "phone": "305-555-0104",
        "licensed_states": "FL,GA,SC",
        "company_name": "Sunshine State Lending",
        "products_provided": "conventional,FHA,VA",
    },
    {
        "first_name": "James",
        "last_name": "Brown",
        "nmls": "NMLS-100005",
        "email": "james.b@midwestlending.com",
        "phone": "312-555-0105",
        "licensed_states": "IL,WI,IN,MI,OH",
        "company_name": "Midwest Mortgage Partners",
        "products_provided": "conventional,FHA,VA,jumbo,USDA",
    },
]


def seed_loan_officers(session: Session):
    existing = session.query(LoanOfficerModel).count()
    if existing > 0:
        return
    for data in SEED_LOAN_OFFICERS:
        officer = LoanOfficerModel(**data)
        session.add(officer)
    session.commit()
