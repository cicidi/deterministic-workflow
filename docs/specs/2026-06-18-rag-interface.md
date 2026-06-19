# RAG Interface — Retrieval-Augmented Generation Abstraction

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Framework-level interface for RAG capabilities. Adopts interfaces from mainstream solutions; no implementation discussion.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-18 | 0.1.0 | Initial RAG interface spec — Document, DocumentStore, Embedder, Retriever, RAGPipeline |

---

## 1. Role

RAG is a cross-cutting infrastructure service within the framework:

```
Layer 1 (NLU/Extract)  ──→  entity resolution, knowledge lookup
Layer 3 (Response)      ──→  context augmentation for LLM generation
                                │
                    ┌───────────┴───────────┐
                    │     RAG Interface      │
                    │  (this spec)           │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
         Haystack          LlamaIndex         LangChain
        (reference)       (adapter)          (adapter)
```

The framework defines **interfaces only**. Backend implementations are adapted from existing open-source solutions. This spec does NOT design a new RAG engine — it adopts proven interfaces from the ecosystem.

### Design Principles

1. **Adopt, don't invent.** Interfaces are modeled after Haystack's protocol-based design (cleanest separation of concerns), with LangChain's Runnable composition pattern.
2. **Pluggable backends.** The same interface can be backed by Haystack, LlamaIndex, LangChain, or a custom implementation.
3. **Protocol-based typing.** All interfaces use `Protocol` classes — any object conforming to the method signatures is a valid implementation.
4. **Query vs Document embedding separation.** `TextEmbedder` (query) and `DocumentEmbedder` (docs) are distinct interfaces, preventing the common pitfall of asymmetric query/doc handling.

---

## 2. Interface Contracts

### 2.1 Document

The universal data unit. Modeled after Haystack's `Document` with sparse embedding support.

```python
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class Document:
    """A single document in the RAG system."""
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None          # dense vector
    sparse_embedding: Optional[dict[int, float]] = None  # sparse (BM25) vector
    score: Optional[float] = None                     # assigned by retriever/reranker

@dataclass
class RetrievedDocument:
    """A document returned by a retriever, with relevance score."""
    document: Document
    score: float
```

### 2.2 DocumentStore

Persistent storage and management of documents. Modeled after Haystack's `DocumentStore` protocol.

```python
from typing import Protocol, Optional

class DocumentStore(Protocol):
    """Protocol for document storage backends.

    Backend examples:
        - Haystack: InMemoryDocumentStore, ElasticsearchDocumentStore, WeaviateDocumentStore
        - LlamaIndex: VectorStoreIndex (wraps vector DB)
        - LangChain: VectorStore implementations (FAISS, Chroma, Pinecone, etc.)
    """

    def count_documents(self) -> int:
        """Return total number of documents in the store."""
        ...

    def write_documents(self, documents: list[Document], policy: str = "replace") -> int:
        """Write documents to the store. Returns number of documents written.

        policy: "replace" (overwrite duplicates) | "skip" (ignore duplicates) | "fail" (raise on duplicate)
        """
        ...

    def delete_documents(self, document_ids: list[str]) -> None:
        """Delete documents by ID."""
        ...

    def filter_documents(self, filters: Optional[dict[str, Any]] = None) -> list[Document]:
        """Return documents matching metadata filters.

        filters: e.g. {"field": "product", "operator": "==", "value": "home_insurance"}
        """
        ...

    def get_document_by_id(self, document_id: str) -> Optional[Document]:
        """Retrieve a single document by ID."""
        ...
```

### 2.3 Embedder

**Explicit separation** of query-side and document-side embedding — modeled after Haystack's `TextEmbedder` / `DocumentEmbedder` distinction.

```python
from typing import Protocol

class TextEmbedder(Protocol):
    """Embed a single query string into a vector.

    Backend examples:
        - Haystack: SentenceTransformersTextEmbedder, OpenAITextEmbedder
        - LlamaIndex: HuggingFaceEmbedding, OpenAIEmbedding
        - LangChain: OpenAIEmbeddings, HuggingFaceEmbeddings
    """

    def embed(self, text: str) -> list[float]:
        """Embed a query string. Returns dense vector."""
        ...


class DocumentEmbedder(Protocol):
    """Embed a batch of documents into vectors. Embeddings are stored in Document.embedding.

    Backend examples:
        - Haystack: SentenceTransformersDocumentEmbedder, OpenAIDocumentEmbedder
        - LlamaIndex: HuggingFaceEmbedding (via _get_text_embeddings)
        - LangChain: OpenAIEmbeddings (via embed_documents)
    """

    def embed(self, documents: list[Document]) -> list[Document]:
        """Embed documents in-place. Returns documents with .embedding populated."""
        ...
```

> **Why separate?** Some models use different encoding strategies for short queries vs. long documents (e.g., asymmetric bi-encoders, instruction-tuned embeddings). A single `Embeddings` class with `embed_query`/`embed_documents` hides this asymmetry. Explicit separation makes the distinction unavoidable at the type level.

### 2.4 Retriever

Query → relevant documents. Modeled after Haystack's retriever components + LangChain's `BaseRetriever`.

```python
from typing import Protocol, Optional

class Retriever(Protocol):
    """Retrieve relevant documents for a query.

    Backend examples:
        - Haystack: InMemoryEmbeddingRetriever, InMemoryBM25Retriever
        - LlamaIndex: VectorIndexRetriever, BM25Retriever
        - LangChain: VectorStoreRetriever, MultiQueryRetriever
    """

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievedDocument]:
        """Retrieve top-k relevant documents for a query.

        query:   Natural language query string
        top_k:   Number of documents to return
        filters: Optional metadata filters for pre-filtering
        """
        ...


class Reranker(Protocol):
    """Re-rank retrieved documents for improved relevance.

    Backend examples:
        - Cohere Rerank API, Jina Reranker API
        - HuggingFace cross-encoder models (BGE-reranker, etc.)
        - rerankers library (unified interface over multiple providers)
    """

    def rerank(
        self,
        query: str,
        documents: list[RetrievedDocument],
        top_k: int = 5,
    ) -> list[RetrievedDocument]:
        """Re-rank documents and return top-k. Documents are returned with updated scores."""
        ...
```

### 2.5 RAG Pipeline

Composition of retrieval → augmentation → generation. Modeled after LangChain's `Runnable` protocol (functional pipe composition).

```python
from typing import Protocol, Any

class RAGPipeline(Protocol):
    """One-shot RAG execution: retrieve + augment + generate.

    This is the primary interface consumed by Layer 3 (Response Generation).
    The pipeline composes a Retriever (optionally with Reranker) + LLM Generator
    to produce a context-aware response.

    Backend examples:
        - Haystack: RAG Pipeline (custom DAG of components)
        - LlamaIndex: QueryEngine (retriever + response_synthesizer)
        - LangChain: create_retrieval_chain (retriever | prompt | llm)
    """

    def query(
        self,
        prompt: str,
        top_k: int = 5,
        filters: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> RAGResult:
        """Execute RAG: retrieve context, augment prompt, generate response.

        prompt:  User query or prompt template
        top_k:   Number of documents to retrieve
        filters: Metadata filters for retrieval
        kwargs:  Backend-specific parameters (temperature, model override, etc.)
        """
        ...


@dataclass
class RAGResult:
    """Result of a RAG pipeline execution."""
    response: str                              # generated text
    sources: list[RetrievedDocument]            # documents used for context
    metadata: dict[str, Any] = field(default_factory=dict)  # backend-specific metadata
```

---

## 3. Integration Points

### 3.1 With Layer 3 (Response Generation)

```
ResponseGenerator
    │
    ├─ intent == "ask_question"  ──→  RAGPipeline.query(prompt)
    │                                    │
    │                                    ├─ Retriever.retrieve(query)
    │                                    ├─ [optional] Reranker.rerank(query, docs)
    │                                    └─ LLM.generate(augmented_prompt)
    │
    └─ Other intents  ──→  Non-RAG response path
```

### 3.2 With Layer 1 (Entity Resolution)

```
ExtractionNode
    │
    └─ Unresolved entity  ──→  Retriever.retrieve(entity_name, top_k=1)
                                  │
                                  └─ Resolved entity from knowledge base
```

### 3.3 Configuration

```yaml
# framework.yaml — RAG backend selection
rag:
  backend: "haystack"          # haystack | llamaindex | langchain | custom
  document_store:
    type: "elasticsearch"      # elasticsearch | weaviate | chroma | etc.
  embedder:
    model: "text-embedding-3-small"
    provider: "openai"         # openai | huggingface | cohere
  retriever:
    type: "embedding"          # embedding | bm25 | hybrid
    top_k_default: 10
  reranker:
    enabled: true
    provider: "cohere"         # cohere | jina | huggingface | none
  pipeline:
    max_context_length: 4000   # max tokens for retrieved context
```

---

## 4. Backend Adapter Mapping

| Interface | Haystack Implementation | LlamaIndex Implementation | LangChain Implementation |
|-----------|------------------------|---------------------------|--------------------------|
| `Document` | `haystack.Document` | `llama_index.core.schema.Document` | `langchain_core.documents.Document` |
| `DocumentStore` | `InMemoryDocumentStore`, `ElasticsearchDocumentStore`, etc. | `VectorStoreIndex` (wraps store) | `VectorStore` subclasses |
| `TextEmbedder` | `SentenceTransformersTextEmbedder`, `OpenAITextEmbedder` | `OpenAIEmbedding`, `HuggingFaceEmbedding` | `OpenAIEmbeddings`, `HuggingFaceEmbeddings` |
| `DocumentEmbedder` | `SentenceTransformersDocumentEmbedder`, `OpenAIDocumentEmbedder` | `OpenAIEmbedding`, `HuggingFaceEmbedding` | `OpenAIEmbeddings`, `HuggingFaceEmbeddings` |
| `Retriever` | `InMemoryEmbeddingRetriever`, `InMemoryBM25Retriever` | `VectorIndexRetriever`, `BM25Retriever` | `VectorStoreRetriever` |
| `Reranker` | N/A (can wrap `rerankers` library) | `SentenceTransformerRerank` | `CohereRerank`, `FlashrankRerank` |
| `RAGPipeline` | Custom `Pipeline` DAG | `RetrieverQueryEngine`, `SubQuestionQueryEngine` | `create_retrieval_chain()` |

Each adapter is a thin wrapper that translates framework `Protocol` calls to the backend's native API. No business logic lives in the adapter — it is purely interface translation.

---

## 5. What This Spec Does NOT Cover

- **Implementation of any RAG backend.** This spec defines interfaces. Backends are chosen and configured by the adopting team.
- **Embedding model selection or benchmarking.** Teams choose models based on their accuracy/cost/latency requirements.
- **Vector database operations.** Chunking strategies, indexing, and storage optimization are backend concerns.
- **Advanced RAG patterns** (HyDE, self-query, parent-document retrieval, etc.). These are exposed through the backend's native API, not the framework interface.
- **RAG evaluation or quality metrics.** Covered by the observability/monitoring spec and CI/CD eval pipeline.

---

## References

- [Haystack Documentation](https://docs.haystack.deepset.ai/) — reference design for `DocumentStore`, `TextEmbedder`/`DocumentEmbedder` separation
- [LangChain RAG Tutorial](https://python.langchain.com/docs/tutorials/rag/) — `Runnable` composition pattern
- [LlamaIndex RAG Guide](https://docs.llamaindex.ai/en/stable/understanding/rag/) — rich data model with `Node` / `QueryBundle`
- [rerankers library](https://github.com/AnswerDotAI/rerankers) — unified reranking interface
- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — parent document
- [LLM Gateway](./2026-06-17-llm-gateway.md) — LLM invocation (used by RAG pipeline for generation)
- [Response Generation Layer](./2026-06-17-response-generation-layer-design.md) — primary consumer of RAG
- [Agent Types](./2026-06-18-agent-types.md) — ReadOnlyAgent uses RAG as primary backend
