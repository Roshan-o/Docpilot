from __future__ import annotations

from uuid import uuid4

from app.api.routes import qa
from app.core.models import Chunk, ChunkMetadata, DocumentMetadata, DocumentType


def test_root_and_health(client):
    root_response = client.get("/")
    health_response = client.get("/api/health")

    assert root_response.status_code == 200
    assert root_response.json()["status"] == "ok"
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert health_response.json()["service"] == "DocPilot"


def test_available_models(monkeypatch, client):
    class Gateway:
        def get_allowed_models(self):
            return ["fake/model"]

    monkeypatch.setattr(qa, "get_model_gateway", lambda: Gateway())

    response = client.get("/api/qa/models")

    assert response.status_code == 200
    assert response.json() == {"available_models": ["fake/model"]}


def test_documents_can_be_uploaded_listed_read_downloaded_and_deleted(client, repository):
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("notes.md", b"# Notes\nUseful content", "text/markdown")},
    )
    document_id = upload.json()["document"]["id"]

    assert upload.status_code == 201
    assert upload.json()["document"]["document_type"] == "markdown"
    assert upload.json()["chunk_count"] == 1
    assert client.get("/api/documents").json()[0]["document"]["id"] == document_id
    assert client.get(f"/api/documents/{document_id}/content").json()["content"] == "# Notes\nUseful content"

    download = client.get(f"/api/documents/{document_id}/download")
    assert download.status_code == 200
    assert download.text == "# Notes\nUseful content"
    assert download.headers["content-disposition"] == 'attachment; filename="notes.md"'

    delete = client.delete(f"/api/documents/{document_id}")
    assert delete.status_code == 204
    assert document_id not in {str(item.id) for item in repository.list_documents()}


def test_upload_rejects_empty_files(client):
    response = client.post(
        "/api/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "File is empty"


def test_upload_rejects_missing_filename(client):
    response = client.post(
        "/api/documents/upload",
        files={"file": ("", b"content", "text/plain")},
    )

    assert response.status_code == 422


def test_document_endpoints_reject_unknown_and_malformed_ids(client):
    unknown_id = uuid4()
    assert client.get(f"/api/documents/{unknown_id}/content").status_code == 404
    assert client.get(f"/api/documents/{unknown_id}/download").status_code == 404
    assert client.delete(f"/api/documents/{unknown_id}").status_code == 404

    assert client.get("/api/documents/not-a-uuid/content").status_code == 422


def test_document_listing_includes_chunk_count(client, repository):
    document_id = uuid4()
    metadata = DocumentMetadata(id=document_id, filename="existing.txt", document_type=DocumentType.text)
    chunk = Chunk(text="existing", metadata=ChunkMetadata(document_id=document_id, paragraph_index=1))
    repository.save_document(metadata, "existing", [chunk, chunk.model_copy()])

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json()[0]["chunk_count"] == 2


def test_upload_maps_ingestion_failure_to_server_error(client, ingest_service):
    ingest_service.fail = True

    response = client.post(
        "/api/documents/upload",
        files={"file": ("notes.md", b"content", "text/markdown")},
    )

    assert response.status_code == 500
    assert "fake ingestion failure" in response.json()["detail"]
