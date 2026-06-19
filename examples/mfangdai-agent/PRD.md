# mfangdai-agent — Product Requirements Document

**Status:** MVP Built  
**Last Updated:** 2026-06-19

---

## 1. Product Overview

**mfangdai-agent** is a conversational AI agent that connects home buyers (borrowers) with licensed mortgage loan officers through the mRateQuote platform. Borrowers can inquire about mortgage rates, submit loan leads, and receive structured rate quotes. Loan officers can discover leads, submit competitive quotes, and communicate with borrowers—all through the agent as a privacy-preserving intermediary.

The agent is built on the **Deterministic Workflow Framework**, a three-layer architecture where LLMs assist with natural language understanding but all business logic (routing, validation, rate calculation, officer matching) is 100% deterministic and auditable.

**Target Industry:** Fintech (mortgage lending), with the framework reusable across any regulated industry.

---

## 2. User Personas

### 2.1 Home Owner / Borrower

A person seeking a mortgage loan—either to purchase a new home or refinance an existing one. They interact with the agent to get rate quotes, learn about mortgage products, and connect with loan officers.

**Needs:**
- Get an instant rate quote based on their financial profile
- Understand mortgage products and terminology
- Check the status of their loan application
- Communicate with loan officers without exposing personal contact info prematurely

### 2.2 Loan Officer

A licensed mortgage professional (NMLS-registered) who originates loans in specific states. They use the agent to discover qualified leads and submit competitive rate quotes.

**Needs:**
- Register on the platform with NMLS credentials
- View and filter available leads by licensed state
- Submit rate quotes to compete for borrower business
- Communicate with borrowers via privacy relay before purchasing lead contact info
- Switch between multiple leads in context

---

## 3. Core Workflows

### 3.1 Borrower Rate Inquiry (collect → lead → match → quote)

The primary workflow. Multi-turn conversation where the agent collects 5 required fields, creates a lead, matches a licensed officer, and returns a simulated rate quote.

```
Borrower: "I want to check mortgage rates"
Agent:    "Are you buying a new home (purchase) or refinancing?"

Borrower: "I'm buying a new home"
Agent:    "What is the estimated value of the property?"

Borrower: "My home is worth $800,000"
Agent:    "How much are you looking to borrow?"

Borrower: "I need $400,000"
Agent:    "Which state is the property located in?"

Borrower: "California"
Agent:    "What is your approximate credit score range?"

Borrower: "My credit score is 780"
Agent:    "Here is your rate quote:

          - Loan Type: 30-Year Fixed Conventional
          - Loan Purpose: Purchase
          - Loan Amount: $400,000
          - Interest Rate: 6.1%
          - APR: 6.25%
          - Estimated Monthly Payment: $2,391.69/month
          - Based on credit score: 780_799

          Your quote was provided by Michael Chen from Golden Gate Mortgage.
          Would you like to proceed with this loan officer?"
```

**Required fields:** `loan_purpose`, `home_value`, `loan_amount`, `state`, `credit_score_range`

**State transitions:** `collecting_info → info_collected → lead_created → officer_matched → quote_generated → completed`

### 3.2 Loan Officer Lead Discovery

A registered loan officer queries for leads in their licensed states and receives a numbered list.

```
Officer: "Show me available leads in California"
Agent:   "I found 3 available leads:

         1. Purchase — $300,000 loan, $500,000 property value, Credit: 720_739, State: CA
         2. Refinance — $400,000 loan, $800,000 property value, Credit: 780_799, State: CA
         3. Purchase — $200,000 loan, $300,000 property value, Credit: 620_639, State: CA

         Reply with the lead number and your quote (e.g., 'Offer 6.5% for lead #2')."
```

**Visibility rule:** Officers only see leads in states where they hold an active license.

### 3.3 Loan Officer Registration

A new loan officer expresses interest in joining the platform.

```
Officer: "I want to register as a loan officer"
Agent:   "Thanks for your interest! To complete registration, I'll need your
         NMLS number, email, and the states you're licensed in."
```

**Required fields:** `first_name`, `last_name`, `nmls`, `email`, `licensed_states`

### 3.4 Knowledge Pool Q&A

Users can ask mortgage-related questions at any point in a conversation. The agent retrieves answers from a pool of 20 FAQ documents covering loan types, credit scores, down payments, PMI, APR, closing costs, etc.

```
Borrower: "What is an FHA loan?"
Agent:    "**What is an FHA loan?**

          An FHA loan is insured by the Federal Housing Administration.
          It requires a minimum credit score of 580 for a 3.5% down payment,
          or 500-579 for a 10% down payment..."
```

```
Borrower: "What's the weather in Florida?"  (out-of-domain)
Agent:    "I don't have specific information about that in my knowledge base.
          However, I can connect you with a licensed loan officer..."
```

**Key property:** Knowledge questions are non-destructive. Asking one mid-collection does not lose previously collected fields (e.g., `loan_purpose` remains intact).

### 3.5 Privacy Relay (Borrower ↔ Officer via Agent)

Loan officers can ask borrowers clarifying questions without seeing their contact information. Borrowers respond through the same masked channel. Contact info is only unlocked after a $35 lead purchase.

```
Officer:   "Can you ask the borrower what their employment status is?"
Agent:     "Your question has been forwarded to the borrower. They will be
           notified and can respond here. (Your contact info is hidden until
           you purchase the lead.)"

Borrower:  "I am employed full-time at a tech company"
Agent:     "Your response has been sent to the loan officer."

Officer:   "I want to contact this borrower directly"
Agent:     "To view the borrower's contact information, a $35 lead purchase
           fee applies. Reply 'confirm' to proceed."
```

Messages are persisted in the `reveal_request` table with masking enabled by default.

### 3.6 Lead Context Switching

An officer viewing multiple leads can switch their active context to focus on a specific lead.

```
Officer: "I want to switch to lead 1"
Agent:   "Switched to lead #1: Purchase, $300,000 loan, CA, Credit: 720_739."
```

Switching by number parses `#?(\d+)` from the message. Falls back to showing the full lead list if no match.

---

## 4. Architecture

The agent follows the Deterministic Workflow Framework's three-layer architecture with Context Hydration.

```
User Input
    |
    v
+-----------------------+
| Context Hydration      |  Load AgentState (messages, collected_data, phase, lead_id)
+-----------+-----------+
            v
+-----------------------+
| Layer 1: UNDERSTAND    |  classify_intent → extract_entities
| Intent + Extractions   |  LLM-primary + deterministic regex fallback
+-----------+-----------+
            v
+-----------------------+
| Layer 2: DECIDE         |  route + validate + execute
| Deterministic Business  |  Officer matching, rate calculation, lead persistence
| Logic (no LLM)          |  All executors are pure Python functions
+-----------+-----------+
            v
+-----------------------+
| Layer 3: RESPOND        |  Deterministic formatters for quotes/leads
| Message Generation      |  LLM reserved for free-text responses only
+-----------------------+
```

### 4.1 Layer 1: NLU / Extraction

- **Intent Classification:** LLM-driven (temperature=0) with structured JSON output via Pydantic schema enforcement
- **Entity Extraction:** Co-extracted with intent from the same LLM call; 14 intents recognized
- **Deterministic Fallback:** If LLM returns empty entities, regex-based extraction runs (home value, loan amount, state, credit score, loan purpose)
- **Transform Pipeline (E→V→T):** Entities → Validation → Deterministic Transform (credit score normalization, state normalization, loan purpose normalization)

### 4.2 Layer 2: Decision

100% deterministic Python functions. No LLM involvement.

| Executor | Function |
|----------|----------|
| `create_borrower` | Persist borrower to DB |
| `create_lead` | Persist lead to DB |
| `match_officer` | Find officer licensed in lead's state; create assignment |
| `generate_quote` | Rate matrix lookup + amortization formula; persist quote |
| `get_available_leads_for_officer` | Query leads by licensed states |

### 4.3 Layer 3: Response

- Quote and lead list responses are **deterministically formatted** (no LLM)
- Help text is template-based
- Knowledge pool answers are sourced from documents
- LLM (`call_text`, temperature=0.3) is available for free-text generation but currently used sparingly

### 4.4 AgentState (Context Hydration)

A `dataclass` carried through every turn:

| Field | Purpose |
|-------|---------|
| `messages` | Full conversation history |
| `user_id`, `user_type`, `user_name` | Identity |
| `phase` | Current workflow phase |
| `collected_data` | Merged extracted entities |
| `lead_id`, `borrower_id`, `loan_officer_id` | Persistent entity references |
| `quote` | Generated quote dict |
| `current_lead_id` | Active lead for officer context switching |

---

## 5. Features Built

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | Intent classification (14 intents) | Done | LLM-primary, JSON output enforced by Pydantic |
| 2 | Deterministic extraction fallback (regex) | Done | 5 field types: home_value, loan_amount, state, credit_score, loan_purpose |
| 3 | Entity normalization (state, credit, purpose) | Done | Full state name → 2-letter code; numeric credit → range bucket |
| 4 | Multi-turn lead collection (5 required fields) | Done | Missing-field-aware prompting; corrections overwrite previous values |
| 5 | Lead creation + persistence | Done | SQLAlchemy + SQLite |
| 6 | Officer matching by licensed state | Done | Strips whitespace from CSV state lists |
| 7 | Simulated rate matrix (11 credit tiers) | Done | Rates from 6.0% (800+) to 8.0% (below_620) |
| 8 | Amortization-based monthly payment calculation | Done | Standard formula, 30-year fixed |
| 9 | Quote generation + persistence | Done | Linked to lead and officer |
| 10 | Knowledge pool (20 mortgage FAQ docs) | Done | Keyword TF overlap retrieval; fallback for unknown questions |
| 11 | Loan officer lead discovery | Done | State-filtered; formatted with lead numbers |
| 12 | Loan officer registration flow | Done | Collects NMLS, email, licensed states |
| 13 | Privacy relay (officer ↔ borrower) | Done | `RevealRequestModel` with contact masking |
| 14 | Contact info payment gate ($35) | Done | Prompt displayed; purchase not yet automated |
| 15 | Lead context switching | Done | Parse lead # from message; fallback to full list |
| 16 | Greet / Help intents | Done | Role-aware help text |
| 17 | Check quote status | Done | Status message for pending applications |
| 18 | Multi-model LLM gateway (DeepSeek / GPT-5 Nano) | Done | Env vars: `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` |
| 19 | LLM retry (3 attempts) with backoff | Done | Handles markdown fence stripping and JSON validation |
| 20 | Unrecognized/correction intent fallback | Done | Graceful degradation to help prompt |
| 21 | Error escalation | Done | Unified `_error_response` handler |
| 22 | In-memory session store (RelayAgent) | Done | Session persistence across turns; reset support |
| 23 | No-matching-officer edge case | Done | Polite notification with promise to notify later |
| 24 | Multi-officer competitive quoting | Done | Multiple officers can quote same lead |
| 25 | Seed data: 5 loan officers in 16 states | Done | Michael(CA/OR/WA), Sarah(NY/NJ/CT/PA), David(TX/OK/LA), Emily(FL/GA/SC), James(IL/WI/IN/MI/OH) |

---

## 6. Test Coverage

**64 total tests** (30 unit + 34 functional)

### 6.1 Unit Tests (`tests/test_workflow.py` — 30 tests)

| Category | Tests | Covers |
|----------|-------|--------|
| Borrower workflow | 4 | Greet, rates start, full quote flow, check status |
| Officer workflow | 3 | Leads query, registration interest, quote submission |
| Extraction pipeline | 3 | State normalization, credit score normalization, loan purpose normalization |
| Rate calculation | 2 | Rate matrix lookup, monthly payment formula |
| Database operations | 2 | Seed officers count, create borrower |
| Gateway retry | 2 | Retry exhaustion, call_text attribute |
| Intent routing | 3 | Unrecognized intent, correction intent, low confidence |
| Officer matching | 2 | No match (AK), licensed states whitespace |
| Extraction edge cases | 7 | Hyphen credit score, unknown state, unknown purpose, empty missing fields, next missing field, unknown credit string, unknown field prompt |
| Relay session | 1 | Session persistence + reset |
| Database errors | 1 | get_session before init |

### 6.2 Functional Tests (`tests/test_functional.py` — 34 scenarios)

| # | Scenario |
|---|----------|
| 1 | Full flow: borrower Alice refinances $800k home in CA, gets quote |
| 2 | Diversion: ask rates → ask help mid-flow |
| 3 | Officer sees leads, submits quote |
| 4 | Loan officer registration |
| 5 | Edge case: no matching officer (Alaska) |
| 6 | Check quote status |
| 7 | Agent promotes registration to new officer |
| 8 | Lead → officer quote roundtrip (borrower receives officer's quote) |
| 9 | Rate matrix tool test (correct rates by credit tier) |
| 10 | Correction: wrong value → corrected value |
| 11 | Clarifying question mid-flow (doesn't lose collected data) |
| 12 | Change loan purpose mid-flow (purchase → refinance) |
| 13 | Multiple fields in one message |
| 14 | Stubborn/vague customer — agent persists with guidance |
| 15 | Topic jumping (rates → help → status → back to info) |
| 16 | Interrupt with fees question, then continue |
| 17 | Complete → reject → start over |
| 18 | License-based visibility (NY officer vs CA leads) |
| 19 | Multi-officer competition on same lead |
| 20 | Lead state transitions (created → quoted → funded) |
| 21 | Multiple officers quote same lead |
| 22 | Knowledge pool: borrower asks FHA, down payment, credit score |
| 23 | Knowledge pool: officer asks about mortgage products |
| 24 | Unknown knowledge question → helpful fallback |
| 25 | Knowledge question mid-flow doesn't lose collected data |
| 26 | Privacy relay: officer asks borrower question |
| 27 | Privacy relay: borrower answers officer question |
| 28 | Privacy relay: officer requests contact info ($35 gate) |
| 29 | Lead context switching by number |
| 30 | Deterministic extraction: home value regex |
| 31 | Deterministic extraction: loan amount regex |
| 32 | Deterministic extraction: state regex |
| 33 | Deterministic extraction: loan purpose regex |
| 34 | Deterministic extraction: credit score regex |

### 6.3 Simulated Tests (`tests/test_simulated.py` — LLM-driven)

Real LLM calls against DeepSeek or GPT-5 Nano when `LLM_API_KEY` is set. Skipped otherwise. Covers purchase and refinance personas, loan officer onboarding.

---

## 7. Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Framework | LangChain (ChatOpenAI) |
| State Machine | Custom LangGraph-style agent loop (no LangGraph dependency) |
| LLM Provider | DeepSeek (default) or OpenAI GPT-5 Nano (env-switchable) |
| Database | SQLite (via SQLAlchemy ORM) |
| Schema Validation | Pydantic v2 |
| Testing | pytest |
| Config Format | YAML (domain model, intents, workflow) |

**Key env vars:** `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`

---

## 8. Next Steps (Not Yet Built)

| # | Feature | Why Important | Effort |
|---|---------|---------------|--------|
| 1 | **MCP server** | Expose agent as MCP tool for AI assistants (Claude, etc.) | Medium |
| 2 | **A2A client** | Agent-to-agent communication for cross-platform lead sharing | Medium |
| 3 | **Real data validation** | Current extraction mostly regex; needs entity-level validation (e.g., home value > loan amount, valid ZIP+state pairing) | Small |
| 4 | **Balance system** | Track officer lead purchase credits; automated deduction on contact reveal | Medium |
| 5 | **Hashtag / topic tracking** | Tag conversations for analytics and routing | Small |
| 6 | **PostgreSQL migration** | Replace SQLite for production multi-tenancy | Small |
| 7 | **Authentication integration** | Keycloak integration (config scaffolded but not wired) | Medium |
| 8 | **Observability** | Logging, metrics, tracing for production monitoring | Medium |
| 9 | **Real officer registration with NMLS validation** | Verify NMLS IDs against the NMLS registry | Large |
| 10 | **Real rate engine integration** | Replace simulated rate matrix with live pricing engine API | Medium |
| 11 | **Embedding-based knowledge retrieval** | Replace TF keyword matching with vector embeddings for better FAQ matching | Small |
| 12 | **Multi-language support** | Spanish, Chinese borrower support | Large |
