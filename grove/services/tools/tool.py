from abc import ABC, abstractmethod
from grove.extensions import logger


class Tool(ABC):
    """Base class for all tools. Enforces the pattern: db_read → run → db_write."""

    name: str = "tool"

    def request(self, job_id: str, **kwargs):
        """Entry point. Reads from DB, runs the tool, writes results."""
        logger.info(msg=f"Request received [{self.name}]", extra={"job_id": job_id}, stacklevel=2)
        data = self.db_read(job_id, **kwargs)
        result = self.run(job_id, data, **kwargs)
        self.db_write(job_id, result, **kwargs)

    def db_read(self, job_id: str, **kwargs):
        """Read input data from the database. Override if needed."""
        return None

    @abstractmethod
    def run(self, job_id: str, data, **kwargs):
        """Core tool logic. Must be implemented by subclasses."""
        pass

    def db_write(self, job_id: str, result, **kwargs):
        """Write results to the database. Override if needed."""
        pass
