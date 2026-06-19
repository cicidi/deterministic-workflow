"""Context Hydration: load user/session data before processing."""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentState:
    """Core agent state hydrated at start of each turn."""
    messages: list[dict] = field(default_factory=list)
    user_id: str = ""
    user_type: str = ""  # "borrower" or "loan_officer"
    user_name: str = ""
    phase: str = "collecting_info"
    collected_data: dict[str, Any] = field(default_factory=dict)
    lead_id: Optional[str] = None
    quote: Optional[dict[str, Any]] = None
    loan_officer_id: Optional[str] = None
    return_stack: list[str] = field(default_factory=list)
    error: Optional[str] = None
