from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.adapters import (
    AdapterRegistry,
    DoclingSupportedAdapter,
    MarkdownAdapter,
    PlainTextAdapter,
)
from app.core.models import DocumentType
from app.core.strategies import (
    ChunkingStrategyRegistry,
    ParagraphChunkingStrategy,
    SlidingWindowChunkingStrategy,
    TokenChunkingStrategy,
)
from app.services.document_store import InMemoryDocumentStore, _chunk_text, _detect_document_type
from app.services.edit_manager import EditCommand
from app.services.model_gateway import ModelGateway, ModelSelectionStrategy, RoutingContext


def test_model_selection_prefers_fast_and_quality_models():
    strategy = ModelSelectionStrategy(
        primary_model="primary",
        fallback_model="quality-model",
        allowed_models=["fast-mini", "quality-model", "other"],
    )

    fast, _ = strategy.select(RoutingContext(task_type="qa", estimated_tokens=10))
    quality, _ = strategy.select(RoutingContext(task_type="synthesis", estimated_tokens=10))
    large_edit, _ = strategy.select(RoutingContext(task_type="edit", estimated_tokens=3001))

    assert fast == "fast-mini"
    assert quality == "quality-model"
    assert large_edit == "quality-model"


def test_model_selection_falls_back_when_configured_models_are_not_allowed():
    strategy = ModelSelectionStrategy(
        primary_model="missing-primary",
        fallback_model="missing-fallback",
        allowed_models=["available-mini"],
    )

    selected, _ = strategy.select(RoutingContext(task_type="other", estimated_tokens=0))
    fast, _ = strategy.select(RoutingContext(task_type="qa", estimated_tokens=0))
    quality, _ = strategy.select(RoutingContext(task_type="synthesis", estimated_tokens=0))

    assert selected == "available-mini"
    assert fast == "available-mini"
    assert quality == "available-mini"


def test_model_gateway_estimates_tokens_and_uses_fallback(monkeypatch):
    gateway = ModelGateway("primary", "fallback", ["primary", "fallback"])
    monkeypatch.setattr("app.services.model_gateway.litellm.token_counter", lambda **kwargs: 12)
    assert gateway.estimate_tokens("hello") == 12

    def fail_counter(**kwargs):
        raise RuntimeError("counter unavailable")

    monkeypatch.setattr("app.services.model_gateway.litellm.token_counter", fail_counter)
    assert gateway.estimate_tokens("12345678") == 2


def test_model_gateway_complete_uses_successful_primary(monkeypatch):
    gateway = ModelGateway("primary", "fallback", ["primary", "fallback"])
    monkeypatch.setattr("app.services.model_gateway.litellm.token_counter", lambda **kwargs: 1)
    monkeypatch.setattr(
        "app.services.model_gateway.litellm.completion",
        lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))]),
    )

    result = gateway.complete("question")

    assert result[0:3] == ("answer", "primary", False)


def test_model_gateway_complete_falls_back_after_primary_failure(monkeypatch):
    gateway = ModelGateway("primary", "fallback", ["primary", "fallback"])
    monkeypatch.setattr("app.services.model_gateway.litellm.token_counter", lambda **kwargs: 1)
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise RuntimeError("primary unavailable")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fallback answer"))])

    monkeypatch.setattr("app.services.model_gateway.litellm.completion", complete)

    result = gateway.complete("question")

    assert result[0:3] == ("fallback answer", "fallback", True)
    assert calls == ["primary", "fallback"]


def test_model_gateway_complete_returns_error_when_all_models_fail(monkeypatch):
    gateway = ModelGateway("primary", "fallback", ["primary", "fallback"])
    monkeypatch.setattr("app.services.model_gateway.litellm.token_counter", lambda **kwargs: 1)
    monkeypatch.setattr("app.services.model_gateway.litellm.completion", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("down")))

    result = gateway.complete("question")

    assert result[1:] == ("primary", True, "Selected the default primary model for this task type. All candidate models failed in fallback chain.")
    assert "Failed to get response" in result[0]


def test_adapters_extract_text_sections_and_registry_fallback():
    markdown = MarkdownAdapter()
    sections = markdown.extract_sections("notes.md", b"intro\n# First\nbody\n# Second\nmore")
    assert [section["section_name"] for section in sections] == ["Preamble", "First", "Second"]
    assert markdown.extract_text("notes.md", b"caf\xc3\xa9") == "caf\u00e9"

    plain = PlainTextAdapter()
    assert plain.extract_sections("notes.txt", b"plain")[0]["text"] == "plain"
    assert AdapterRegistry.get_adapter_for_file("unknown.bin").supported_types == [DocumentType.text]


def test_docling_adapter_uses_fallback_without_docling():
    adapter = DoclingSupportedAdapter()
    adapter.docling_available = False
    adapter.converter = None

    assert adapter.extract_text("file.pdf", b"text") == "text"
    assert adapter.extract_sections("file.pdf", b"text")[0]["section_name"] == "Full Document"


def test_chunking_strategies_and_registry():
    document_id = uuid4()
    paragraph_chunks = ParagraphChunkingStrategy(max_chunk_size=10).chunk(
        document_id, "One. Two. Three.\n\nShort", page_num=2
    )
    token_chunks = TokenChunkingStrategy(chunk_size_tokens=1, overlap_tokens=0).chunk(document_id, "abcdefgh")
    windows = SlidingWindowChunkingStrategy(window_size=3, step_size=2).chunk(document_id, "abcdef")

    assert len(paragraph_chunks) == 3
    assert paragraph_chunks[0].metadata.page_number == 2
    assert len(token_chunks) == 2
    assert [chunk.text for chunk in windows] == ["abc", "cde", "ef"]
    assert isinstance(ChunkingStrategyRegistry.get_strategy("unknown"), ParagraphChunkingStrategy)


def test_document_store_detects_files_chunks_and_deletes():
    store = InMemoryDocumentStore()
    stored = store.save_uploaded_file("notes.md", b"first\nsecond")
    assert stored.metadata.document_type == DocumentType.markdown
    assert len(stored.chunks) == 2
    assert store.get_document(stored.metadata.id) is stored

    assert _detect_document_type("file.pdf") == DocumentType.pdf
    assert _detect_document_type("file.docx") == DocumentType.docx
    assert _detect_document_type("file.pptx") == DocumentType.pptx
    assert _detect_document_type("file.bin") == DocumentType.unknown
    assert _chunk_text(stored.metadata.id, "") == []

    store.delete_document(stored.metadata.id)
    assert store.list_documents() == []


def test_long_document_is_split_into_fixed_chunks():
    document_id = uuid4()
    chunks = _chunk_text(document_id, "x" * 801)

    assert [len(chunk.text) for chunk in chunks] == [800, 1]
    assert chunks[0].metadata.source_label.endswith("part1")


def test_edit_command_generates_insert_delete_equal_diff():
    command = EditCommand(uuid4(), "replace", "before\nkeep", "after\nkeep")

    proposal = command.to_proposal()

    assert proposal.original_text == "before\nkeep"
    assert [(line.kind, line.content) for line in proposal.diff] == [
        ("delete", "before"),
        ("insert", "after"),
        ("equal", "keep"),
    ]
