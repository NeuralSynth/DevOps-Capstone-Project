import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    # Fresh SQLite database for every test run; never the real Postgres database
    if os.path.exists("test.db"):
        os.remove("test.db")
    # The context manager runs the app lifespan, which creates the tables
    with TestClient(app) as c:
        yield c


def create(client, **fields):
    payload = {"title": "Deploy application", "priority": "HIGH", "assignee": "Student", **fields}
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201
    return response.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "UP"}

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "TaskBoard API"

def test_create_task_validation(client):
    response = client.post("/api/tasks", json={"title": "Deploy application", "priority": "HIGH", "assignee": "Student"})
    assert response.status_code == 201
    assert response.json()["title"] == "Deploy application"

def test_create_task_rejects_invalid_payload(client):
    assert client.post("/api/tasks", json={"title": ""}).status_code == 422
    assert client.post("/api/tasks", json={"title": "Bad priority", "priority": "URGENT"}).status_code == 422

def test_list_and_get_task(client):
    task = create(client, title="Write Helm chart")
    listed = client.get("/api/tasks").json()
    assert task["id"] in [t["id"] for t in listed]
    fetched = client.get(f"/api/tasks/{task['id']}").json()
    assert fetched["title"] == "Write Helm chart"
    assert fetched["status"] == "TODO"

def test_update_task(client):
    task = create(client, title="Provision EKS")
    response = client.put(f"/api/tasks/{task['id']}", json={"status": "IN_PROGRESS", "assignee": "Shreyas"})
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"
    assert response.json()["assignee"] == "Shreyas"
    assert response.json()["title"] == "Provision EKS"  # untouched fields are kept

def test_delete_task(client):
    task = create(client, title="Temporary task")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404

def test_missing_task_returns_404(client):
    assert client.get("/api/tasks/999999").status_code == 404
    assert client.put("/api/tasks/999999", json={"status": "DONE"}).status_code == 404
    assert client.delete("/api/tasks/999999").status_code == 404

def test_stats_count_by_status(client):
    before = client.get("/api/tasks/stats").json()
    create(client, title="Finished task", status="DONE")
    after = client.get("/api/tasks/stats").json()
    assert after["total"] == before["total"] + 1
    assert after["done"] == before["done"] + 1
    assert after["total"] == after["todo"] + after["inProgress"] + after["done"]
