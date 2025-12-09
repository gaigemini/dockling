import logging
from abc import ABC

class BaseService(ABC):
    """
    Base service class that automatically includes request context in logs
    """
    
    def __init__(self, logger: logging.LoggerAdapter):
        """
        Initialize service with request-scoped logger
        
        Args:
            logger: Logger instance from dependency injection
        """
        # Create service-specific logger that inherits context
        service_name = self.__class__.__name__.lower()
        self.logger = logging.LoggerAdapter(
            logger.logger.getChild(service_name),
            logger.extra  # Preserve all context
        )