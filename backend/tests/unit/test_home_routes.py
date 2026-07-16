import pytest

pytestmark = pytest.mark.unit


def test_health_endpoint_reports_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_page_returns_assessment_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Last Mile Health" in response.text
