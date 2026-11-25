"""Long-term approved-memory facade."""

from memory.memory_manager import MemoryManager


class LongTermMemory:
    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    def remember(self, content: str, *, approved: bool = False, **kwargs):
        return self.manager.add_memory(
            content,
            memory_type="long_term",
            approved=approved,
            **kwargs,
        )
