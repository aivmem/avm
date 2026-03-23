"""In-memory database for todo items."""

from datetime import datetime
from typing import Dict, Optional, List
from .models import TodoItem


class TodoDatabase:
    """Simple in-memory storage for todo items."""

    def __init__(self):
        self._todos: Dict[int, TodoItem] = {}
        self._counter: int = 0

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        completed: bool = False
    ) -> TodoItem:
        """Create a new todo item."""
        todo = TodoItem(
            id=self._next_id(),
            title=title,
            description=description,
            completed=completed,
            created_at=datetime.utcnow()
        )
        self._todos[todo.id] = todo
        return todo

    def get(self, todo_id: int) -> Optional[TodoItem]:
        """Get a todo item by ID."""
        return self._todos.get(todo_id)

    def get_all(self) -> List[TodoItem]:
        """Get all todo items."""
        return list(self._todos.values())

    def update(
        self,
        todo_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        completed: Optional[bool] = None
    ) -> Optional[TodoItem]:
        """Update a todo item. Returns None if not found."""
        todo = self._todos.get(todo_id)
        if not todo:
            return None

        if title is not None:
            todo.title = title
        if description is not None:
            todo.description = description
        if completed is not None:
            todo.completed = completed

        return todo

    def delete(self, todo_id: int) -> bool:
        """Delete a todo item. Returns True if deleted, False if not found."""
        if todo_id in self._todos:
            del self._todos[todo_id]
            return True
        return False

    def clear(self) -> None:
        """Clear all todos (useful for testing)."""
        self._todos.clear()
        self._counter = 0


# Global database instance
db = TodoDatabase()
