from typing import Any, Optional


class ErrorResponse(Exception):
    def __init__(
        self,
        error_code: str,
        error_message: str,
        data: Optional[Any] = None,
    ):
        self.error_code = error_code
        self.error_message = error_message
        self.data = data

        super().__init__(error_message)

