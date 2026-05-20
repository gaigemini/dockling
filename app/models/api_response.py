# models/api_response.py
from typing import Optional, Union, Dict, List, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime, timezone
from enum import IntEnum


class StatusCode(IntEnum):
    """HTTP-like status codes untuk response"""
    SUCCESS = 0
    ERROR = 4


class ApiResponse(BaseModel):
    """
    Standard API response structure dengan constraints:
    - data: hanya string, list of dict, atau dict
    - status: 0 = success, 4 = error
    - error_message: hanya diisi jika error
    """
    status: StatusCode = Field(
        StatusCode.SUCCESS, description="0 = success, 4 = error")
    data: Optional[Union[str, List[Dict[str, Any]], Dict[str, Any], BaseModel, List[BaseModel]]] = Field(
        None,
        description="Response data (string, dict, list of dict, or Pydantic Model)"
    )
    error_message: Optional[str] = Field(
        None,
        description="Error message (only populated when error)"
    )
    total_elements: Optional[int] = Field(
        None, description="Total elements (for pagination)")
    page: Optional[int] = Field(
        None, description="Current page number (0-based)")
    page_size: Optional[int] = Field(None, description="Page size")
    total_pages: Optional[int] = Field(None, description="Total pages")
    error_type: Optional[str] = Field(None, description="Type of error")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(
        timezone.utc), description="Response timestamp")

    @field_validator('data')
    @classmethod
    def validate_data_type(cls, v: Any) -> Any:
        """Validasi bahwa data hanya string, dict, list of dict, atau Model"""
        if v is None:
            return v

        allowed_types = (str, dict, list, BaseModel)
        if not isinstance(v, allowed_types):
            raise ValueError(
                f"data must be str, dict, list, or BaseModel, got {type(v).__name__}")

        # Jika list, pastikan elemennya adalah dict atau BaseModel
        if isinstance(v, list):
            for item in v:
                if not isinstance(item, (dict, BaseModel)):
                    raise ValueError(
                        f"list items must be dict or BaseModel, got {type(item).__name__}")

        return v

    @field_validator('error_message')
    @classmethod
    def validate_error_message(cls, v: Optional[str], info: Any) -> Optional[str]:
        """Validasi error_message hanya ada jika status error"""
        values = info.data if hasattr(info, 'data') else {}
        # Note: In V2 validation happens field by field. Accessing other fields can be tricky if they are not yet validated.
        # But 'status' is defined before 'error_message', so it might be available.
        # However, info.data gives access to previously validated fields.
        if v is not None and values.get('status') != StatusCode.ERROR:
             # In V2 we might just warn or ignore, or enforce strictness. 
             # For now, let's keep logic but catch potential missing key if status validation failed or hasn't run.
             pass 
             # Actually, simpler is to rely on defaults. 
             # If status is not in values, it means it failed validation or is missing.
        
        # Re-implementing logic safely:
        status = values.get('status')
        if v is not None and status is not None and status != StatusCode.ERROR:
             raise ValueError("error_message should only be set when status is ERROR")
        return v

    model_config = ConfigDict(
        use_enum_values=True,
        # json_encoders is deprecated but still works in V2 for migration.
        # Better to rely on standard serialization.
    )

    @classmethod
    def success(
        cls,
        data: Optional[Union[str, List[Dict[str, Any]],
                             Dict[str, Any]]] = None,
        total_elements: Optional[int] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        total_pages: Optional[int] = None
    ) -> 'ApiResponse':
        """Factory method untuk response sukses"""
        return cls(
            status=StatusCode.SUCCESS,
            data=data,
            total_elements=total_elements,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )

    @classmethod
    def error(
        cls,
        error_message: str,
        error_type: Optional[str] = None,
        data: Optional[Union[str, List[Dict[str, Any]], Dict[str, Any]]] = None
    ) -> 'ApiResponse':
        """Factory method untuk response error"""
        return cls(
            status=StatusCode.ERROR,
            error_message=error_message,
            error_type=error_type,
            data=data
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with JSON serializable values"""
        # Exclude None values. In V2: model_dump(exclude_none=True)
        result = self.model_dump(exclude_none=True)

        # Convert timestamp to ISO format if needed, but model_dump with mode='json' does it.
        # If we stick to dict, we might get datetime objects.
        if 'timestamp' in result and isinstance(result['timestamp'], datetime):
            result['timestamp'] = result['timestamp'].isoformat()

        # Remove error_message if status is success
        if result.get('status') == StatusCode.SUCCESS and 'error_message' in result:
            del result['error_message']

        return result

    def is_success(self) -> bool:
        """Check if response is successful"""
        return self.status == StatusCode.SUCCESS

    def is_error(self) -> bool:
        """Check if response is error"""
        return self.status == StatusCode.ERROR


class PaginationParams(BaseModel):
    """Pagination parameters"""
    page_number: int = Field(0, ge=0, description="Page number (0-based)")
    page_size: int = Field(10, ge=1, le=1000, description="Page size")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "page_number": 0,
            "page_size": 10
        }
    })


class PaginatedResponse(BaseModel):
    """Paginated response structure"""
    content: List[Dict[str, Any]] = Field(..., description="Data results")
    page_number: int = Field(..., description="Current page number (0-based)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    total_elements: int = Field(..., description="Total number of elements")
    number_of_elements: int = Field(...,
                                    description="Number of elements in current page")
    is_first: bool = Field(..., description="Is this the first page?")
    is_last: bool = Field(..., description="Is this the last page?")
    has_next: bool = Field(..., description="Is there a next page?")
    has_previous: bool = Field(..., description="Is there a previous page?")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "content": [
                {"id": "1", "name": "Item 1"},
                {"id": "2", "name": "Item 2"}
            ],
            "page_number": 0,
            "page_size": 10,
            "total_pages": 1,
            "total_elements": 2,
            "number_of_elements": 2,
            "is_first": True,
            "is_last": True,
            "has_next": False,
            "has_previous": False
        }
    })
