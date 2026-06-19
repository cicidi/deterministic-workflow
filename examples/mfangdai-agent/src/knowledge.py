"""Knowledge Pool — mortgage FAQ document store with keyword retrieval.

Mock documents serve as placeholder. Replace with real documents later.
Uses simple TF-like keyword matching; upgrade to embeddings when needed.
"""
import re
from dataclasses import dataclass, field


@dataclass
class KnowledgeDocument:
    id: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str = "mock"


MOCK_DOCUMENTS = [
    KnowledgeDocument(
        id="doc_001",
        title="What is a conventional loan?",
        content="A conventional loan is a mortgage not backed by a government agency. "
                "It typically requires a credit score of at least 620, a down payment of 3-20%, "
                "and follows guidelines set by Fannie Mae and Freddie Mac. "
                "Conventional loans offer competitive rates and flexible terms (15, 20, or 30 years).",
        tags=["conventional", "loan type", "down payment", "credit score"],
    ),
    KnowledgeDocument(
        id="doc_002",
        title="What is an FHA loan?",
        content="An FHA loan is insured by the Federal Housing Administration. "
                "It requires a minimum credit score of 580 for a 3.5% down payment, "
                "or 500-579 for a 10% down payment. FHA loans are popular with first-time "
                "home buyers and those with lower credit scores. They require mortgage insurance.",
        tags=["FHA", "government", "first-time buyer", "credit score", "down payment"],
    ),
    KnowledgeDocument(
        id="doc_003",
        title="What is a VA loan?",
        content="A VA loan is guaranteed by the Department of Veterans Affairs. "
                "It is available to eligible veterans, active-duty service members, and surviving spouses. "
                "VA loans offer 0% down payment, no mortgage insurance, and competitive rates. "
                "A funding fee may apply unless exempt.",
        tags=["VA", "veteran", "military", "zero down", "no PMI"],
    ),
    KnowledgeDocument(
        id="doc_004",
        title="What is a USDA loan?",
        content="A USDA loan is backed by the U.S. Department of Agriculture for rural properties. "
                "It offers 0% down payment and lower mortgage insurance costs. "
                "Eligibility depends on location (rural area) and income limits. "
                "USDA loans are designed for low-to-moderate income borrowers.",
        tags=["USDA", "rural", "zero down", "government"],
    ),
    KnowledgeDocument(
        id="doc_005",
        title="What is a jumbo loan?",
        content="A jumbo loan exceeds the conforming loan limits set by Fannie Mae and Freddie Mac. "
                "In most areas, the 2024 limit is $766,550 for a single-family home. "
                "Jumbo loans typically require higher credit scores (700+), larger down payments (10-20%), "
                "and more documentation. Rates may be slightly higher than conforming loans.",
        tags=["jumbo", "loan limit", "high value", "credit score"],
    ),
    KnowledgeDocument(
        id="doc_006",
        title="What credit score do I need for a mortgage?",
        content="Minimum credit score requirements vary by loan type: "
                "Conventional: 620 | FHA: 580 (3.5% down) or 500 (10% down) | "
                "VA: No official minimum, but most lenders require 620 | "
                "USDA: 640 | Jumbo: 700+. "
                "Higher scores qualify for better rates. A 740+ score typically gets the best conventional rates.",
        tags=["credit score", "minimum", "FHA", "conventional", "VA", "requirements"],
    ),
    KnowledgeDocument(
        id="doc_007",
        title="How much down payment do I need?",
        content="Down payment requirements by loan type: "
                "Conventional: 3-20% (3% for first-time buyers) | "
                "FHA: 3.5% (credit ≥580) | VA: 0% | USDA: 0% | Jumbo: 10-20%. "
                "A 20% down payment avoids Private Mortgage Insurance (PMI) on conventional loans. "
                "Down payment assistance programs are available in many states.",
        tags=["down payment", "PMI", "first-time buyer", "conventional", "FHA"],
    ),
    KnowledgeDocument(
        id="doc_008",
        title="What is PMI (Private Mortgage Insurance)?",
        content="PMI is insurance that protects the lender if you default on a conventional loan "
                "with less than 20% down payment. PMI costs 0.5-2% of the loan amount annually, "
                "paid monthly. PMI can be cancelled once you reach 20% equity. "
                "FHA loans have MIP (Mortgage Insurance Premium) instead, which may be permanent.",
        tags=["PMI", "mortgage insurance", "conventional", "down payment", "FHA", "MIP"],
    ),
    KnowledgeDocument(
        id="doc_009",
        title="What is the difference between fixed and adjustable rates?",
        content="Fixed-rate mortgages have the same interest rate for the entire loan term "
                "(15, 20, or 30 years). Monthly payments stay constant. "
                "Adjustable-rate mortgages (ARMs) start with a lower fixed rate for 5, 7, or 10 years, "
                "then adjust annually based on market rates. ARMs carry more risk but may save money "
                "if you plan to sell or refinance before the adjustment period.",
        tags=["fixed rate", "ARM", "adjustable", "rate type", "comparison"],
    ),
    KnowledgeDocument(
        id="doc_010",
        title="What is APR vs interest rate?",
        content="The interest rate is the cost of borrowing the principal loan amount. "
                "APR (Annual Percentage Rate) includes the interest rate PLUS fees and other costs "
                "(origination fees, discount points, closing costs). APR gives a more complete "
                "picture of the loan's true cost. Always compare APRs, not just interest rates.",
        tags=["APR", "interest rate", "comparison", "fees", "cost"],
    ),
    KnowledgeDocument(
        id="doc_011",
        title="What are closing costs?",
        content="Closing costs are fees paid when finalizing a mortgage, typically 2-5% of the "
                "loan amount. They include: origination fees, appraisal, title insurance, "
                "credit report, recording fees, and prepaid items (taxes, insurance). "
                "Some lenders offer no-closing-cost options with a higher interest rate.",
        tags=["closing costs", "fees", "origination", "title", "appraisal"],
    ),
    KnowledgeDocument(
        id="doc_012",
        title="What is a rate lock?",
        content="A rate lock guarantees your interest rate for a specified period (typically 30-60 days) "
                "while your loan is processed. If rates rise during the lock period, you keep the lower rate. "
                "If rates fall, you may be able to float down for a fee. Rate locks protect against "
                "market volatility during the mortgage process.",
        tags=["rate lock", "interest rate", "protection", "volatility"],
    ),
    KnowledgeDocument(
        id="doc_013",
        title="What documents do I need for a mortgage application?",
        content="Common required documents: Pay stubs (last 30 days), W-2s (2 years), "
                "tax returns (2 years), bank statements (2-3 months), government ID, "
                "proof of assets, gift letters (if applicable). Self-employed borrowers need "
                "additional documentation: profit/loss statements, business tax returns.",
        tags=["documents", "application", "requirements", "tax returns", "self-employed"],
    ),
    KnowledgeDocument(
        id="doc_014",
        title="What is refinancing?",
        content="Refinancing replaces your current mortgage with a new one, typically to get "
                "a lower interest rate, change the loan term, or switch from an ARM to fixed rate. "
                "Cash-out refinancing lets you borrow against home equity. "
                "Consider closing costs and how long you plan to stay — the breakeven point "
                "is when savings exceed refinancing costs.",
        tags=["refinance", "cash-out", "rate", "equity", "ARM"],
    ),
    KnowledgeDocument(
        id="doc_015",
        title="What is the debt-to-income ratio (DTI)?",
        content="DTI is the percentage of your monthly income that goes to debt payments. "
                "Most lenders prefer a DTI under 43% (front-end DTI: housing costs only; "
                "back-end DTI: all debts). Conventional loans max at 36-45%, FHA up to 50%. "
                "Lower DTI improves your chances of approval and may qualify you for better rates.",
        tags=["DTI", "debt", "income", "qualification", "approval"],
    ),
    KnowledgeDocument(
        id="doc_016",
        title="What are discount points?",
        content="Discount points are upfront fees paid at closing to lower your interest rate. "
                "One point costs 1% of the loan amount and typically reduces the rate by 0.25%. "
                "Points are prepaid interest and may be tax-deductible. "
                "Calculate the breakeven point: how long until the monthly savings exceed the point cost?",
        tags=["points", "discount", "interest rate", "buy down", "closing"],
    ),
    KnowledgeDocument(
        id="doc_017",
        title="Can I buy a home with no down payment?",
        content="Yes, through VA loans (for eligible veterans) and USDA loans (for rural properties). "
                "Both offer 0% down payment. Some state and local programs also offer down payment "
                "assistance. Conventional loans require at least 3% down. "
                "FHA requires 3.5% minimum. No-down-payment loans may have higher rates or fees.",
        tags=["zero down", "no down payment", "VA", "USDA", "first-time buyer"],
    ),
    KnowledgeDocument(
        id="doc_018",
        title="How long does the mortgage process take?",
        content="The typical mortgage process takes 30-45 days from application to closing. "
                "Factors affecting timeline: documentation completeness, appraisal scheduling, "
                "underwriting backlog, and loan complexity. Pre-approval can be done in 1-3 days. "
                "Having all documents ready and responding quickly to lender requests speeds up the process.",
        tags=["timeline", "process", "closing", "underwriting", "pre-approval"],
    ),
    KnowledgeDocument(
        id="doc_019",
        title="What happens after I submit a mortgage application?",
        content="After submission: 1) Loan officer reviews and orders services (appraisal, title). "
                "2) Underwriter evaluates your credit, income, assets, and property. "
                "3) Conditional approval may require additional documents. "
                "4) Final approval and clear-to-close. 5) Closing disclosure sent 3 days before closing. "
                "6) Sign documents, pay closing costs, get keys.",
        tags=["application", "process", "underwriting", "closing", "approval"],
    ),
    KnowledgeDocument(
        id="doc_020",
        title="What mortgage products does mRateQuote offer?",
        content="mRateQuote connects borrowers with licensed loan officers offering: "
                "Conventional loans (15yr, 20yr, 30yr fixed), FHA loans, VA loans, "
                "USDA loans, Jumbo loans, and Non-QM loans for unique situations. "
                "Our loan officers provide competitive rate quotes. "
                "Register or submit a lead to get started with personalized quotes.",
        tags=["mRateQuote", "products", "platform", "conventional", "FHA", "VA"],
    ),
]


class KnowledgePool:
    """Simple keyword-based retrieval from mock mortgage documents."""

    def __init__(self, documents: list[KnowledgeDocument] = None):
        self.documents = documents or MOCK_DOCUMENTS

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r'\w+', text.lower()))

    def search(self, query: str, top_n: int = 3) -> list[KnowledgeDocument]:
        """Retrieve top N documents matching the query by keyword overlap."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        scored = []
        for doc in self.documents:
            doc_tokens = self._tokenize(doc.title + " " + doc.content + " " + " ".join(doc.tags))
            overlap = len(query_tokens & doc_tokens)
            if overlap > 0:
                scored.append((overlap, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_n]]

    def answer(self, query: str) -> str:
        """Return a formatted answer based on retrieved documents."""
        results = self.search(query)
        if not results:
            return (
                "I don't have specific information about that in my knowledge base. "
                "However, I can connect you with a licensed loan officer who can help. "
                "Would you like me to start a rate quote, or is there another mortgage topic I can assist with?"
            )
        if len(results) == 1:
            return f"**{results[0].title}**\n\n{results[0].content}"

        lines = ["Here's what I found:\n"]
        for i, doc in enumerate(results, 1):
            lines.append(f"**{i}. {doc.title}**\n{doc.content}\n")
        return "\n".join(lines)

    def add_document(self, doc: KnowledgeDocument):
        self.documents.append(doc)

    def load_from_yaml(self, path: str):
        """Placeholder: load real documents from YAML file later."""
        pass
