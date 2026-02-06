"""
Base class for all skills.
Provides common functionality and interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging
from datetime import datetime


class BaseSkill(ABC):
    """Abstract base class for all agent skills."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"skill.{name}")
        self.last_run: Optional[datetime] = None
        self.run_count: int = 0
        self.error_count: int = 0

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the skill's main function.
        Must be implemented by each skill.

        Returns:
            Dict containing the result of the skill execution
        """
        pass

    def log_start(self):
        """Log skill execution start."""
        self.logger.info(f"Starting {self.name}")
        self.run_count += 1

    def log_complete(self, result: Dict[str, Any]):
        """Log skill execution completion."""
        self.last_run = datetime.utcnow()
        self.logger.info(f"Completed {self.name}: {result.get('summary', 'OK')}")

    def log_error(self, error: Exception):
        """Log skill execution error."""
        self.error_count += 1
        self.logger.error(f"Error in {self.name}: {str(error)}")

    def get_stats(self) -> Dict[str, Any]:
        """Get skill execution statistics."""
        return {
            "name": self.name,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "success_rate": (
                (self.run_count - self.error_count) / self.run_count * 100
                if self.run_count > 0
                else 0
            ),
        }
