"""Todo List REST API using FastAPI."""

from typing import List
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from .models import TodoCreate, TodoUpdate, TodoResponse
from .database import db

app = FastAPI(
    title="Todo List API",
    description="A REST API for managing todo items",
    version="1.0.0"
)


@app.get("/")
def root():
    """Health check endpoint."""
    return {"message": "Todo API is running", "version": "1.0.0"}


@app.post(
    "/todos",
    response_model=TodoResponse,
    status_code=status.HTTP_201_CREATED
)
def create_todo(todo: TodoCreate):
    """Create a new todo item."""
    new_todo = db.create(
        title=todo.title,
        description=todo.description,
        completed=todo.completed
    )
    return new_todo.to_dict()


@app.get("/todos", response_model=List[TodoResponse])
def get_todos(
    completed: bool | None = None,
    limit: int = 100,
    offset: int = 0
):
    """Get all todo items with optional filtering and pagination."""
    todos = db.get_all()
    if completed is not None:
        todos = [t for t in todos if t.completed == completed]
    return [todo.to_dict() for todo in todos[offset:offset + limit]]


@app.get("/todos/{todo_id}", response_model=TodoResponse)
def get_todo(todo_id: int):
    """Get a specific todo item by ID."""
    todo = db.get(todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )
    return todo.to_dict()


@app.put("/todos/{todo_id}", response_model=TodoResponse)
def update_todo(todo_id: int, todo_update: TodoUpdate):
    """Update a todo item."""
    # Check if at least one field is provided
    update_data = todo_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )

    updated_todo = db.update(
        todo_id=todo_id,
        title=todo_update.title,
        description=todo_update.description,
        completed=todo_update.completed
    )

    if not updated_todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )

    return updated_todo.to_dict()


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int):
    """Delete a todo item."""
    deleted = db.delete(todo_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with id {todo_id} not found"
        )
    return None
