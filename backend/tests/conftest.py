from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ingest_service, get_model_gateway, get_orchestrator, get_repository
from app.core.abstractions import StoredChunk
from app.core.models import Chunk, ChunkMetadata, DocumentMetadata, DocumentType
from app.main import app


class FakeRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, tuple[DocumentMetadata, str, list[Chunk]]] = {}
        self.embeddings: dict[UUID, list[float]] = {}

    def save_document(self, metadata, raw_text, chunks):
        self.documents[metadata.id] = (metadata, raw_text, list(chunks))
        return metadata.id

    def get_document_by_id(self, document_id):
        record = self.documents.get(document_id)
        if record is None:
            return None
        metadata, _, chunks = record
        return metadata, list(chunks)

    def get_document_text(self, document_id):
        record = self.documents.get(document_id)
        if record is None:
            return None
        metadata, raw_text, _ = record
        return metadata, raw_text

    def list_documents(self):
        return [record[0] for record in self.documents.values()]

    def delete_document(self, document_id):
        self.documents.pop(document_id, None)

    def get_chunks_by_document(self, document_id):
        record = self.documents.get(document_id)
        return [] if record is None else list(record[2])

    def replace_document_content(self, document_id, raw_text, chunks):
        record = self.documents.get(document_id)
        if record is None:
            raise ValueError("Document not found")
        self.documents[document_id] = (record[0], raw_text, list(chunks))

    def save_chunk_embedding(self, chunk_id, embedding):
        self.embeddings[chunk_id] = embedding

    def search_chunks_by_embedding(self, query_embedding, top_k=5, document_ids=None):
        allowed = set(document_ids) if document_ids else None
        results = []
        for metadata, _, chunks in self.documents.values():
            if allowed is not None and metadata.id not in allowed:
                continue
            results.extend(
                StoredChunk(
                    id=chunk.id,
                    document_id=metadata.id,
                    text=chunk.text,
                    metadata=chunk.metadata,
                    embedding=self.embeddings.get(chunk.id),
                )
                for chunk in chunks
            )
        return results[:top_k]

    def search_chunks_by_keyword(self, keywords, document_id=None, top_k=5):
        results = []
        for metadata, _, chunks in self.documents.values():
            if document_id is not None and metadata.id != document_id:
                continue
            for chunk in chunks:
                if any(keyword.lower() in chunk.text.lower() for keyword in keywords):
                    results.append(
                        StoredChunk(
                            id=chunk.id,
                            document_id=metadata.id,
                            text=chunk.text,
                            metadata=chunk.metadata,
                            embedding=self.embeddings.get(chunk.id),
                        )
                    )
        return results[:top_k]


class FakeIngestService:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.fail = False

    def ingest(self, filename, content, chunking_strategy="paragraph"):
        if self.fail:
            raise RuntimeError("fake ingestion failure")
        document_type = DocumentType.markdown if filename.endswith(".md") else DocumentType.text
        document_id = uuid4()
        metadata = DocumentMetadata(
            id=document_id,
            filename=filename,
            document_type=document_type,
            uploaded_at=datetime.now(timezone.utc),
        )
        text = content.decode("utf-8")
        chunk = Chunk(
            text=text,
            metadata=ChunkMetadata(document_id=document_id, paragraph_index=1),
        )
        self.repository.save_document(metadata, text, [chunk])
        return document_id


class FakeModelGateway:
    def __init__(self) -> None:
        self.allowed_models = ["fake/model"]

    def get_allowed_models(self):
        return self.allowed_models


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def ingest_service(repository: FakeRepository) -> FakeIngestService:
    return FakeIngestService(repository)


@pytest.fixture
def client(repository: FakeRepository, ingest_service: FakeIngestService) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_ingest_service] = lambda: ingest_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_repository.cache_clear()
    get_ingest_service.cache_clear()
    get_model_gateway.cache_clear()
    get_orchestrator.cache_clear()
