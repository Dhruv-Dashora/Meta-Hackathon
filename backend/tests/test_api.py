"""Basic API + schema tests (scaffold — no external calls)."""

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.common import Confidence, Finding

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_alias():
    resp_api = client.get("/api/health")
    resp_root = client.get("/health")
    assert resp_api.status_code == 200
    assert resp_root.status_code == 200
    assert resp_root.json() == resp_api.json()


def test_early_warning_placeholder():
    resp = client.post("/api/early-warning/analyze", json={})
    assert resp.status_code == 200
    assert resp.json()["incident_id"] == "scaffold"


def test_disaster_response_placeholder():
    resp = client.post("/api/disaster-response/assess", json={})
    assert resp.status_code == 200
    assert resp.json()["incident_id"] == "scaffold"


def test_confidence_is_uncalibrated_by_default():
    f = Finding(
        finding_id="f1",
        label="test",
        confidence=Confidence(value=0.5),
    )
    assert f.confidence.calibrated is False
    assert f.review_status.value == "pending"
