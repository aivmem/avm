"""Unit tests for the Todo List API."""

import pytest
from fastapi.testclient import TestClient

from .main import app
from .database import db


@pytest.fixture(autouse=True)
def reset_database():
    """Reset the database before each test."""
    db.clear()
    yield
    db.clear()


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def sample_todo(client):
    """Create a sample todo for tests that need existing data."""
    response = client.post("/todos", json={
        "title": "Test Todo",
        "description": "Test description"
    })
    return response.json()


class TestHealthCheck:
    """Tests for the root health check endpoint."""

    def test_root_returns_ok(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Todo API is running"
        assert "version" in data


class TestCreateTodo:
    """Tests for POST /todos endpoint."""

    def test_create_todo_with_all_fields(self, client):
        response = client.post("/todos", json={
            "title": "Buy groceries",
            "description": "Milk, eggs, bread",
            "completed": False
        })
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Buy groceries"
        assert data["description"] == "Milk, eggs, bread"
        assert data["completed"] is False
        assert "id" in data
        assert "created_at" in data

    def test_create_todo_minimal(self, client):
        response = client.post("/todos", json={"title": "Simple task"})
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Simple task"
        assert data["description"] is None
        assert data["completed"] is False

    def test_create_todo_with_completed_true(self, client):
        response = client.post("/todos", json={
            "title": "Already done",
            "completed": True
        })
        assert response.status_code == 201
        assert response.json()["completed"] is True

    def test_create_todo_missing_title(self, client):
        response = client.post("/todos", json={"description": "No title"})
        assert response.status_code == 422

    def test_create_todo_empty_title(self, client):
        response = client.post("/todos", json={"title": ""})
        assert response.status_code == 422

    def test_create_todo_title_too_long(self, client):
        response = client.post("/todos", json={"title": "x" * 201})
        assert response.status_code == 422

    def test_create_todo_description_too_long(self, client):
        response = client.post("/todos", json={
            "title": "Valid title",
            "description": "x" * 1001
        })
        assert response.status_code == 422

    def test_create_multiple_todos_increments_id(self, client):
        resp1 = client.post("/todos", json={"title": "First"})
        resp2 = client.post("/todos", json={"title": "Second"})
        assert resp1.json()["id"] < resp2.json()["id"]


class TestGetTodos:
    """Tests for GET /todos endpoint."""

    def test_get_todos_empty(self, client):
        response = client.get("/todos")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_todos_with_items(self, client, sample_todo):
        client.post("/todos", json={"title": "Second todo"})
        response = client.get("/todos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_get_todos_returns_all_fields(self, client, sample_todo):
        response = client.get("/todos")
        todo = response.json()[0]
        assert "id" in todo
        assert "title" in todo
        assert "description" in todo
        assert "completed" in todo
        assert "created_at" in todo


class TestGetTodoById:
    """Tests for GET /todos/{todo_id} endpoint."""

    def test_get_todo_by_id(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.get(f"/todos/{todo_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == todo_id
        assert data["title"] == sample_todo["title"]

    def test_get_todo_not_found(self, client):
        response = client.get("/todos/999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_todo_invalid_id_type(self, client):
        response = client.get("/todos/invalid")
        assert response.status_code == 422


class TestUpdateTodo:
    """Tests for PUT /todos/{todo_id} endpoint."""

    def test_update_todo_title(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.put(f"/todos/{todo_id}", json={"title": "Updated title"})
        assert response.status_code == 200
        assert response.json()["title"] == "Updated title"

    def test_update_todo_description(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.put(f"/todos/{todo_id}", json={"description": "New desc"})
        assert response.status_code == 200
        assert response.json()["description"] == "New desc"

    def test_update_todo_completed(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.put(f"/todos/{todo_id}", json={"completed": True})
        assert response.status_code == 200
        assert response.json()["completed"] is True

    def test_update_todo_multiple_fields(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.put(f"/todos/{todo_id}", json={
            "title": "New title",
            "description": "New description",
            "completed": True
        })
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New title"
        assert data["description"] == "New description"
        assert data["completed"] is True

    def test_update_todo_not_found(self, client):
        response = client.put("/todos/999", json={"title": "Test"})
        assert response.status_code == 404

    def test_update_todo_empty_body(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.put(f"/todos/{todo_id}", json={})
        assert response.status_code == 400
        assert "no fields" in response.json()["detail"].lower()

    def test_update_todo_invalid_title(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.put(f"/todos/{todo_id}", json={"title": ""})
        assert response.status_code == 422

    def test_update_preserves_unchanged_fields(self, client, sample_todo):
        todo_id = sample_todo["id"]
        original_title = sample_todo["title"]
        response = client.put(f"/todos/{todo_id}", json={"completed": True})
        assert response.status_code == 200
        assert response.json()["title"] == original_title


class TestDeleteTodo:
    """Tests for DELETE /todos/{todo_id} endpoint."""

    def test_delete_todo(self, client, sample_todo):
        todo_id = sample_todo["id"]
        response = client.delete(f"/todos/{todo_id}")
        assert response.status_code == 204
        # Verify it's deleted
        get_response = client.get(f"/todos/{todo_id}")
        assert get_response.status_code == 404

    def test_delete_todo_not_found(self, client):
        response = client.delete("/todos/999")
        assert response.status_code == 404

    def test_delete_todo_removes_from_list(self, client, sample_todo):
        todo_id = sample_todo["id"]
        client.delete(f"/todos/{todo_id}")
        response = client.get("/todos")
        assert len(response.json()) == 0


class TestIntegration:
    """Integration tests for full CRUD workflow."""

    def test_full_crud_workflow(self, client):
        # Create
        create_resp = client.post("/todos", json={
            "title": "Learn FastAPI",
            "description": "Complete the tutorial"
        })
        assert create_resp.status_code == 201
        todo_id = create_resp.json()["id"]

        # Read
        get_resp = client.get(f"/todos/{todo_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Learn FastAPI"

        # Update
        update_resp = client.put(f"/todos/{todo_id}", json={"completed": True})
        assert update_resp.status_code == 200
        assert update_resp.json()["completed"] is True

        # Delete
        delete_resp = client.delete(f"/todos/{todo_id}")
        assert delete_resp.status_code == 204

        # Verify deleted
        verify_resp = client.get(f"/todos/{todo_id}")
        assert verify_resp.status_code == 404
