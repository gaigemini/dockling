import logging
from abc import ABC
from typing import Optional


class BaseService(ABC):
    """
    Base service class that automatically includes request context in logs.
    """

    def __init__(self, logger: Optional[logging.LoggerAdapter] = None):
        """
        Initialize service with optional request-scoped logger.

        Args:
            logger: Logger instance from dependency injection.
                     If None, creates a basic logger for the service.
        """
        service_name = self.__class__.__name__.lower()
        if logger is not None:
            self.logger = logging.LoggerAdapter(
                logger.logger.getChild(service_name),
                logger.extra  # Preserve all context
            )
        else:
            self.logger = logging.LoggerAdapter(
                logging.getLogger(f"app.services.{service_name}"),
                {"request_id": "system"}
            )