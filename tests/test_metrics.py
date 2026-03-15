from fastapi.testclient import TestClient
from src.app.main import app


def test_metrics_endpoints():
    client = TestClient(app)
    r = client.get("/metrics/budget")
    assert r.status_code == 200
    j = r.json()
    assert "tokens" in j and "cost" in j

    r2 = client.get("/metrics/usage-by-adapter")
    assert r2.status_code == 200
    assert isinstance(r2.json(), dict)
