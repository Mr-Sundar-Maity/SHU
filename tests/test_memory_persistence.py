"""Cross-process persistence checks for user-approved memory records."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_approved_memory_is_available_in_a_later_python_process(tmp_path):
    database_path = tmp_path / "memory.db"
    environment = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (project_root, existing_pythonpath) if item
    )

    save_memory = r"""
import sys
from database.database import Database
from memory.memory_manager import MemoryManager
database = Database(sys.argv[1])
database.initialize()
MemoryManager(database).add_memory(
    "The preferred response language is Bengali",
    memory_type="preference",
    approved=True,
    source="user_confirmed",
)
"""
    saved = subprocess.run(
        [sys.executable, "-c", save_memory, str(database_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    assert saved.stdout == ""

    retrieve_memory = r"""
import json
import sys
from database.database import Database
from memory.memory_manager import MemoryManager
from memory.memory_retriever import MemoryRetriever
database = Database(sys.argv[1])
database.initialize()
context = MemoryRetriever(MemoryManager(database)).context_messages("language")
print(json.dumps(context, ensure_ascii=False))
"""
    retrieved = subprocess.run(
        [sys.executable, "-c", retrieve_memory, str(database_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    context = json.loads(retrieved.stdout)

    assert len(context) == 1
    assert context[0]["role"] == "user"
    assert "The preferred response language is Bengali" in context[0]["content"]
    assert "user_confirmed" in context[0]["content"]

