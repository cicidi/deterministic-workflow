# Agent Types — Specialized Execution Agents

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Two agent abstractions that execute tasks after intent classification and state machine routing. Write operations are handled by the deterministic state machine — not by an agent.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-18 | 0.2.0 | Remove WriteAgent — write operations are state machine territory, not agent territory |
| 2026-06-18 | 0.1.0 | Initial agent types spec — ReadOnlyAgent, WriteAgent, EscalationAgent |

---

## 1. Role

After Layer 1 classifies intent and Layer 2 decides the next state, **Layer 3 delegates execution to a specialized agent** for specific intent categories. Write/transactional operations (quote, claim, policy changes) are handled deterministically by the state machine — not delegated to an agent.

```
Intent Classification → State Machine → Agent Dispatch
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    │                                                   │
              ReadOnlyAgent                                      EscalationAgent
              (ask, help, chitchat)                              (complaint, escalate)
                    │                                                   │
                    └─────────────────────────┬─────────────────────────┘
                                              │
                                     State Machine (write ops)
                                     RAG Pipeline
                                     LLM Gateway
```

### Design Principles

1. **Capability-bounded.** Each agent declares its allowed operations. A ReadOnlyAgent cannot write. All writes go through the state machine.
2. **State-aware.** Agents receive `agentState` context — they know what phase the user is in, what data has been collected.
3. **Protocol-based.** Like the RAG interface, all agents are `Protocol` classes. Any conforming implementation works.
4. **Single responsibility.** Agents handle ONE category of intents. No agent does everything.
5. **Writes are deterministic.** Write operations (create, update, delete, execute) are handled by the state machine with auditable transitions. No LLM decides to write.

---

## 2. Agent Interfaces

### 2.1 ReadOnlyAgent

Answers questions, retrieves information, handles casual conversation. **Cannot modify state or execute transactions.**

```python
from typing import Protocol, Any

class ReadOnlyAgent(Protocol):
    """Agent for information retrieval and Q&A. Read-only — no state mutation.

    Assigned intents:
        - ask_question
        - help
        - chitchat
        - repeat
        - check_coverage (domain-specific: policy lookup)
        - ask_about_claim_status (domain-specific: claim status lookup)

    Backend examples:
        - A RAG pipeline backed by Haystack/LlamaIndex/LangChain
        - A simple FAQ matching engine
        - A knowledge base search with LLM summarization
    """

    def query(
        self,
        prompt: str,
        intent: str,
        agent_state: dict[str, Any],
        **kwargs: Any,
    ) -> ReadOnlyResult:
        """Answer a question or retrieve information.

        prompt:       The user's original message or a rephrased query
        intent:       The classified intent label (e.g., 'ask_question')
        agent_state:  Current agent state (phase, collected fields, conversation history)
        kwargs:       Agent-specific parameters

        Returns a ReadOnlyResult with the answer and source citations.
        """
        ...

    def capabilities(self) -> list[str]:
        """Return the list of operations this agent supports.
        Example: ['search_kb', 'summarize', 'translate', 'faq_lookup']
        """
        ...


@dataclass
class ReadOnlyResult:
    """Result from a ReadOnlyAgent query."""
    response: str                              # the answer text
    sources: list[RetrievedDocument] = field(default_factory=list)  # cited documents
    confidence: float = 1.0                    # agent's confidence in the answer
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 2.2 EscalationAgent

Routes to a human operator. Collects context, determines urgency, initiates handoff. **Does not resolve the issue itself.**

```python
from typing import Protocol, Any, Optional

class EscalationAgent(Protocol):
    """Agent for human handoff. Collects context and escalates — never resolves.

    Assigned intents:
        - escalate
        - complaint

    Backend examples:
        - Ticket creation (Zendesk, Jira Service Desk, ServiceNow)
        - Live chat transfer (Intercom, LiveChat, custom)
        - Email/SMS notification to on-call team
    """

    def escalate(
        self,
        intent: str,
        reason: str,
        urgency: str,
        agent_state: dict[str, Any],
        **kwargs: Any,
    ) -> EscalationResult:
        """Escalate to a human operator.

        intent:       'escalate' or 'complaint'
        reason:       User-provided reason or extracted complaint subject
        urgency:      'low' | 'medium' | 'high' | 'critical'
        agent_state:  Full agent state (phase, conversation history, collected data)
        kwargs:       Agent-specific parameters

        Returns an EscalationResult with handoff status.
        """
        ...

    def capabilities(self) -> list[str]:
        """Return the list of operations this agent supports.
        Example: ['create_ticket', 'live_transfer', 'schedule_callback', 'notify_team']
        """
        ...


@dataclass
class EscalationResult:
    """Result from an EscalationAgent handoff."""
    status: str                                # "transferred" | "ticket_created" | "queued"
    ticket_id: Optional[str] = None             # reference ID for the escalation
    estimated_wait: Optional[str] = None        # e.g., "~5 minutes"
    response: str = ""                         # user-facing message while waiting
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

## 3. Agent Dispatch

The state machine resolves which agent handles a given intent:

```
def dispatch_agent(intent: str, intent_defs: dict) -> type[Protocol]:
    agent_map = {
        # ReadOnlyAgent intents
        "ask_question":          ReadOnlyAgent,
        "help":                  ReadOnlyAgent,
        "chitchat":              ReadOnlyAgent,
        "repeat":                ReadOnlyAgent,
        "check_coverage":        ReadOnlyAgent,     # policy lookup → read
        "ask_about_claim_status": ReadOnlyAgent,     # claim lookup → read

        # EscalationAgent intents
        "escalate":              EscalationAgent,
        "complaint":             EscalationAgent,
    }
    return agent_map.get(intent)
```

**Intents without a dedicated agent** (`start_conversation`, `finish_conversation`, `pause`, `restart`, `confirm`, `decline`, `correction`, `provide_information`, `ambiguous_request`, `out_of_scope`, `unrecognized_intent`, and all write intents like `get_quote`, `file_claim`, `renew_policy`, `update_policy`, `cancel_policy`) are handled directly by the state machine — they are conversation control, slot-filling, or deterministic write operations.

---

## 4. Agent → Tool Permission Model

Each agent type has a bounded set of allowed operations. The tool ecosystem enforces these bounds:

| Agent Type | Can Read (RAG) | Can Call APIs | Can Write DB | Can Send to Human |
|------------|---------------|--------------|-------------|-------------------|
| **ReadOnlyAgent** | Yes | No | No | No |
| **EscalationAgent** | Yes (context) | No | No | Yes |
| **State Machine (write ops)** | No | Yes | Yes | No |

Write operations are NEVER delegated to an agent. They execute as deterministic state machine transitions with full audit trail.

---

## 5. Configuration

```yaml
# framework.yaml — agent configuration
agents:
  read_only:
    backend: "rag_pipeline"    # rag_pipeline | faq_engine | custom
    rag:
      top_k: 5
      max_context_length: 4000
    fallback_response: "I'm sorry, I couldn't find an answer to that question."

  escalation:
    backend: "ticket"          # ticket | live_chat | custom
    ticket:
      system: "zendesk"        # zendesk | jira | servicenow | custom
      default_priority: "medium"
    live_chat:
      enabled: false
      provider: "intercom"     # intercom | livechat | custom
```

---

## 6. What This Spec Does NOT Cover

- **Implementation of any agent backend.** Agents are dispatched to backend implementations configured by the adopting team.
- **Agent-to-agent communication.** Agents never call each other. The state machine orchestrates all transitions.
- **Write operations.** All writes (create, update, delete, execute) are deterministic state machine transitions. No agent performs writes.
- **Multi-agent debate or voting.** This is a deterministic framework, not an agent swarm. One agent handles one intent.
- **Agent lifecycle or memory management.** Agents are stateless per invocation. State lives in `AgentState`.

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent document
- [Intent Classification Design](./2026-06-16-intent-classification-design.md) — intent → agent mapping (§5.2)
- [RAG Interface](./2026-06-18-rag-interface.md) — ReadOnlyAgent's primary backend
- [State Machine Design](./2026-06-16-state-machine-design.md) — agent dispatch and transition orchestration
- [Tool Ecosystem](./2026-06-17-tool-ecosystem.md) — per-agent tool allowlists
