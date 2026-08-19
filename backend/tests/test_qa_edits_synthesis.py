from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.api.routes import edits, qa, synthesis
from app.core.models import EditProposal, EditResponse, QueryResponse


class FakeOrchestrator:
    def __init__(self):
        self.query_requests = []
        self.edit_requests = []
        self.synthesis_requests = []
        self.fail_edit = None
        self.pending_id = uuid4()

    def answer_question(self, request):
        self.query_requests.append(request)
        return QueryResponse(answer="Grounded answer", model_used="fake/model")

    def propose_edit(self, request):
        self.edit_requests.append(request)
        if self.fail_edit:
            raise ValueError(self.fail_edit)
        proposal = EditProposal(
            command_id=self.pending_id,
            document_id=request.document_id,
            instruction=request.instruction,
            original_text="before",
            proposed_text="after",
        )
        return EditResponse(proposal=proposal, model_used="fake/model", status="pending")

    def apply_edit(self, command_id):
        if command_id != self.pending_id:
            raise ValueError("Unknown edit proposal")
        return EditResponse(
            proposal=EditProposal(command_id=command_id, document_id=uuid4(), instruction="edit"),
            status="applied",
        )

    def reject_edit(self, command_id):
        if command_id != self.pending_id:
            raise ValueError("Unknown edit proposal")
        return EditResponse(
            proposal=EditProposal(command_id=command_id, document_id=uuid4(), instruction="edit"),
            status="rejected",
        )

    def synthesize(self, request):
        self.synthesis_requests.append(request)
        return "Synthesized answer"


class FakeGateway:
    def get_allowed_models(self):
        return ["fake/model"]


def test_qa_rejects_empty_query(client, monkeypatch):
    monkeypatch.setattr(qa, "get_orchestrator", lambda: FakeOrchestrator())

    response = client.post("/api/qa", json={"query": ""})

    assert response.status_code == 422


def test_qa_forwards_valid_request(client, monkeypatch):
    orchestrator = FakeOrchestrator()
    monkeypatch.setattr(qa, "get_orchestrator", lambda: orchestrator)
    document_id = uuid4()

    response = client.post(
        "/api/qa",
        json={
            "query": "What matters?",
            "document_ids": [str(document_id)],
            "requested_model": "fake/model",
            "conversation_history": [
                {"query": "Earlier", "model_used": "fake/model", "answer": "Context"}
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Grounded answer"
    assert orchestrator.query_requests[0].document_ids == [document_id]
    assert orchestrator.query_requests[0].conversation_history[0].answer == "Context"


def test_qa_models_uses_route_gateway(monkeypatch, client):
    monkeypatch.setattr(qa, "get_model_gateway", lambda: FakeGateway())

    assert client.get("/api/qa/models").json() == {"available_models": ["fake/model"]}


@pytest.mark.parametrize("path", ["/api/edits", "/api/edits/propose"])
def test_edit_routes_accept_valid_requests(path, client, monkeypatch):
    orchestrator = FakeOrchestrator()
    monkeypatch.setattr(edits, "get_orchestrator", lambda: orchestrator)
    document_id = uuid4()

    response = client.post(
        path,
        json={"document_id": str(document_id), "instruction": "Rewrite this"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert orchestrator.edit_requests[0].document_id == document_id


def test_edit_rejects_missing_required_fields(client, monkeypatch):
    monkeypatch.setattr(edits, "get_orchestrator", lambda: FakeOrchestrator())

    response = client.post("/api/edits", json={"instruction": "Rewrite this"})

    assert response.status_code == 422


def test_edit_maps_service_errors_to_bad_request(client, monkeypatch):
    orchestrator = FakeOrchestrator()
    orchestrator.fail_edit = "Document not found"
    monkeypatch.setattr(edits, "get_orchestrator", lambda: orchestrator)

    response = client.post(
        "/api/edits",
        json={"document_id": str(uuid4()), "instruction": "Rewrite this"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Document not found"


def test_edit_resolution_maps_unknown_commands_to_bad_request(client, monkeypatch):
    monkeypatch.setattr(edits, "get_orchestrator", lambda: FakeOrchestrator())

    response = client.post(f"/api/edits/{uuid4()}/apply")

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown edit proposal"
    assert client.post("/api/edits/not-a-uuid/apply").status_code == 422


def test_synthesis_returns_answer_and_document_ids(client, monkeypatch):
    orchestrator = FakeOrchestrator()
    monkeypatch.setattr(synthesis, "get_orchestrator", lambda: orchestrator)
    document_ids = [uuid4(), uuid4()]

    response = client.post(
        "/api/synthesis",
        json={"query": "Compare these", "document_ids": [str(item) for item in document_ids]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Synthesized answer",
        "citations": [],
        "document_ids": [str(item) for item in document_ids],
    }
    assert orchestrator.synthesis_requests[0].document_ids == document_ids


def test_synthesis_rejects_malformed_document_ids(client, monkeypatch):
    monkeypatch.setattr(synthesis, "get_orchestrator", lambda: FakeOrchestrator())

    response = client.post(
        "/api/synthesis",
        json={"query": "Compare these", "document_ids": ["bad-id"]},
    )

    assert response.status_code == 422
