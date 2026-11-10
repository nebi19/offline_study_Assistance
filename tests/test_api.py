import json

import pytest
from fastapi.testclient import TestClient

from studyassistant.app import create_app

from .test_assistant import quiz_reply, summary_replies


@pytest.fixture
def client(assistant, monkeypatch):
    monkeypatch.delenv("TEACHER_PIN", raising=False)
    return TestClient(create_app(assistant, status=lambda: {"running": True}))


def ndjson(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_library_lists_grades_units_sections(client):
    data = client.get("/api/library").json()
    [grade7] = data["grades"]
    assert grade7["grade"] == 7
    assert [u["id"] for u in grade7["units"]] == ["g7-math:u1", "g7-math:u2"]
    assert grade7["units"][0]["sections"][0]["pages"] == "pp. 1–3"


def test_section_text_has_page_numbers(client):
    sec = client.get("/api/sections/g7-math:u1:s1.1").json()
    assert [p["page"] for p in sec["pages"]] == [1, 2]
    assert client.get("/api/sections/g7-math:u1:s9.9").status_code == 404


def test_ask_streams_ndjson(client):
    res = client.post("/api/ask", json={"unit_id": "g7-math:u1", "question": "What is a proper subset?"})
    assert res.headers["content-type"].startswith("application/x-ndjson")
    events = ndjson(res)
    assert events[0]["type"] == "sources" and events[0]["sources"]
    assert events[-1] == {"type": "done", "answered": True}
    assert client.post("/api/ask", json={"unit_id": "zzz", "question": "hi there"}).status_code == 404


def test_summary_endpoint(client, model):
    model.json_replies = summary_replies()
    res = client.get("/api/units/g7-math:u1/summary?language=en")
    assert res.status_code == 200
    assert res.json()["topics"][0]["pages"] == "pp. 1–3"


def test_quiz_flow_and_teacher_stats(client, model):
    model.json_replies = [quiz_reply(5)]
    quiz = client.post("/api/quizzes", json={"unit_id": "g7-math:u1"}).json()
    answers = [next(i for i, o in enumerate(q["options"]) if o.startswith("right")) for q in quiz["questions"]]
    result = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", json={"answers": answers}).json()
    assert result["score"] == 5

    client.post("/api/ask", json={"unit_id": "g7-math:u1", "question": "What is a proper subset?"})
    client.post("/api/ask", json={"unit_id": "g7-math:u1", "question": "what is a proper subset? "})
    overview = client.get("/api/teacher/overview").json()
    unit = next(u for u in overview["units"] if u["id"] == "g7-math:u1")
    assert unit["quiz_average"] == 100.0
    assert unit["questions"] == 2
    assert unit["top_questions"][0]["count"] == 2


def test_teacher_can_hide_a_unit(client):
    assert client.post("/api/teacher/visibility", json={"unit_id": "g7-math:u2", "hidden": True}).status_code == 200
    units = client.get("/api/library").json()["grades"][0]["units"]
    assert [u["id"] for u in units] == ["g7-math:u1"]
    assert client.get("/api/library?include_hidden=true").json()["grades"][0]["units"][1]["hidden"] is True
    assert client.post("/api/ask", json={"unit_id": "g7-math:u2", "question": "What are integers?"}).status_code == 404


def test_teacher_pin(assistant, monkeypatch):
    monkeypatch.setenv("TEACHER_PIN", "4321")
    client = TestClient(create_app(assistant, status=lambda: None))
    assert client.get("/api/teacher/overview").status_code == 401
    assert client.get("/api/teacher/overview", headers={"X-Teacher-Pin": "4321"}).status_code == 200
    assert client.get("/api/library").status_code == 200  # students need no PIN


def test_home_page_is_served(client):
    res = client.get("/")
    assert res.status_code == 200 and "Study Assistant" in res.text
    assert client.get("/static/vendor/mermaid.min.js").status_code == 200
