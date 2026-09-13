# ADR 001: Adopt a Pipeline-Centric Document Intelligence Architecture

## Status
Accepted

## Context
DocPilot must support multiple high-level operations: grounded Q&A, scoped editing, draft generation, and cross-document synthesis. A monolithic request handler would make it difficult to enforce latency constraints, evolve individual stages, and reason about failures. The proposal and requirements emphasize that system value comes from architecture around LLM calls, not from a single model invocation.

## Decision
We will structure core request execution as a pipeline with explicit stages:
- intent resolution
- document abstraction and retrieval preparation
- context assembly and budgeting
- agent orchestration
- model invocation through gateway
- response post-processing and rendering

Each stage will be independently testable and replaceable. Cross-cutting concerns (logging, tracing, and policy checks) will be inserted at stage boundaries.

## Consequences
- Positive: Clear subsystem boundaries and better maintainability as features expand.
- Positive: Easier performance tuning because latency can be measured per stage.
- Positive: Supports incremental implementation and parallel team development.
- Negative: Added orchestration complexity compared to direct endpoint-to-model calls.
- Negative: More interface contracts must be maintained between stages.

---

# ADR 002: Normalize All Supported File Types Through a Document Adapter Layer

## Status
Accepted

## Context
DocPilot must ingest heterogeneous sources (PDF, DOCX, Markdown, and others). Downstream components (RAG, editing, citations, generation) require consistent structure, but native formats expose very different parsing semantics. Without normalization, every downstream feature would need file-type-specific logic.

## Decision
We will introduce a Document Adapter layer that converts each source format into a unified internal representation (block-oriented structure containing headings, paragraphs, tables, and metadata anchors).

Adapter responsibilities:
- parse raw format using format-specific tooling
- preserve structural metadata needed for citations and edits
- emit a common schema consumed by all downstream services

Downstream services will only consume the unified representation, never raw format-specific objects.

## Consequences
- Positive: Feature logic remains format-agnostic and easier to extend.
- Positive: New file formats can be added by implementing a new adapter only.
- Positive: Citation and edit scopes become more consistent across formats.
- Negative: Some native format fidelity may be reduced during normalization.
- Negative: Adapter quality becomes a critical dependency for all higher-level capabilities.

---

# ADR 003: Use Embedding-Based Retrieval with a Strict 90% Context Budget

## Status
Accepted

## Context
Keyword retrieval was insufficient for grounded responses and citation accuracy targets. The project also defines a non-functional requirement that prompt payloads stay within 90% of model context window capacity to avoid overflow and unstable behavior. Context selection must prioritize relevance while respecting token limits.

## Decision
We will implement RAG retrieval and context assembly as follows:
- generate embeddings for document chunks during ingestion
- generate query embeddings at request time
- rank chunks by cosine similarity
- discard chunks at or below a similarity threshold of 0.6
- allocate context budget using the model's input token capacity
- reserve baseline tokens for instructions and user query
- fill remaining budget with relevant chunks first
- use leftover budget for recent chat history only after chunk inclusion

## Consequences
- Positive: Higher grounding quality and better citation alignment than keyword-only retrieval.
- Positive: Predictable prompt sizing and reduced token overflow risk.
- Positive: Behavior aligns directly with context-budgeting NFRs.
- Negative: Additional embedding latency and ingestion cost.
- Negative: Older uploads without embeddings require re-ingestion.
- Negative: Threshold tuning may need dataset-specific calibration.

---

# ADR 004: Introduce a Multi-Provider Model Gateway with Routing Strategy and Fallback Chain

## Status
Accepted

## Context
DocPilot targets diverse workloads: low-latency inline suggestions, deep long-context analysis, and potential multimodal reasoning. No single model optimizes all three dimensions (quality, speed, cost). Provider lock-in would reduce adaptability and increase operational risk.

## Decision
We will centralize model access through a Model Gateway facade that:
- abstracts provider SDK differences behind a common interface
- selects a model using task-aware routing strategy (task type, latency, cost)
- applies chain-of-responsibility fallback on failure or policy rejection
- standardizes request/response metadata for observability and evaluation

Application services and agents must call the gateway, not provider SDKs directly.

## Consequences
- Positive: Reduces coupling to any single provider and simplifies switching.
- Positive: Enables workload-specific optimization and cost controls.
- Positive: Improves resiliency through transparent fallback.
- Negative: Adds abstraction overhead and routing-policy maintenance.
- Negative: Output normalization across providers can mask provider-specific nuances.

---

# ADR 005: Manage AI Edits as Reversible Commands with Explicit User Commit

## Status
Accepted

## Context
DocPilot includes scoped rewriting and generated edits. Directly mutating source content from model output is unsafe and undermines user trust. Requirements call for structured diffs, per-change accept/reject, and undo support. The edit system must preserve auditability and scope control.

## Decision
We will represent AI edit operations as command objects executed against an editable working state, with snapshot-based rollback support.

Edit workflow:
- generate proposed edits scoped to requested sections
- materialize edits as command objects
- render structured diff for user review
- apply changes only after explicit accept/commit action
- maintain mementos for undo/redo and traceability

## Consequences
- Positive: Safer editing with strong user control over final document state.
- Positive: Clear audit trail of AI-suggested and user-approved changes.
- Positive: Supports reversible operations and better error recovery.
- Negative: More complex state management than immediate-write updates.
- Negative: Diff merge logic can become complex for overlapping edits.
