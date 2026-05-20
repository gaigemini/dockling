---
trigger: always_on
---

# Project Rules

## 1. Tech Stack
- **Language**: Python 3.10+
- **Framework**: FastAPI (Asynchronous)
- **Validation**: Pydantic v2
- **Server**: Uvicorn
- **Database**: PostgreSQL (with pgvector), Redis
- **Testing**: Pytest, Pytest-Asyncio

## 2. Project Structure
All source code is located in the `app/` directory. Configuration and environments are in root.
```
.
├── .agents/                # AI Assistant Context
├── app/                    # Main application code
│   ├── auth/               # Authentication logic
│   ├── config/             # App-level config (DB, Redis)
│   ├── dependencies/       # FastAPI Dependencies
│   ├── endpoints/          # API Routes
│   ├── models/             # Pydantic Models
│   ├── repository/         # Data Access Layer
│   ├── services/           # Business Logic Layer
│   ├── templates/          # Jinja2 Templates
│   ├── utils/              # Utility functions
│   ├── main.py             # Application Entry Point
│   ├── middleware.py       # Custom Middleware
│   └── init_data.py        # Data Initialization
├── config/                 # Root Configuration Package (Settings)
├── env/                    # Environment Variable Files
├── tests/                  # Test Suite
│   ├── api/                # Integration Tests
│   └── unit/               # Unit Tests
├── logs/                   # Application Logs
├── pytest.ini              # Pytest Configuration
└── requirements.txt        # Python Dependencies
```

## 3. Architecture & Patterns
The project follows a layered architecture:
`Endpoint (Controller)` -> `Service` -> `Repository` -> `Database`

### Guidelines
- **Endpoints**: Handle HTTP requests/responses, payload validation, and call Services. Do not contain business logic.
- **Services**: Contain business logic. Call Repositories for data access.
- **Repositories**: 
    - Handle direct database interactions.
    - **MUST** inherit from `app.repository.base_repository.BaseRepository`.
    - Use `_execute` for INSERT/UPDATE/DELETE.
    - Use `_query` or `_query_x` (Mongo-style filter) for SELECT.
    - Use `_bulk` for batch operations.
- **Models**:
    - Use `BaseModel` from `pydantic` for all models.
    - Use separate models for `Base`, `Create`, `Update`, and `Response`.
    - `Response` models should include audit fields (`rec_by`, `rec_at`, `mod_by`, `mod_at`).
    - Audit fields are mandatory for all models.
      - rec_by: "string", // The client created by.
      - rec_at: "datetime", // The client created at.
      - mod_by: "string", // The client updated by.
      - mod_at: "datetime", // The client updated at.
    - **Usage Rules**:
        - `rec_by` and `rec_at` **MUST** be populated when creating a new record.
        - `mod_by` and `mod_at` **MUST** be updated whenever a record is modified.

## 4. API Standards
### Response Structure
All API endpoints MUST return responses using the `ApiResponse` class from `app.models.api_response`.
- **Success**: Use `ApiResponse.success(data=...)`
- **Error**: Use `ApiResponse.error(error_message=...)`
- **Pagination**: Use `PaginatedResponse` for list endpoints.

### Error Handling
- **Custom Exceptions**: ALWAYS raise `ErrorResponse` from `app.utils.error` for known application errors.
- **HTTP Exceptions**: Handled by global exception handlers in `main.py` which convert them to `ApiResponse` format.

## 5. Logging & Observability
- **System**: Centralized logging via `config.logger` and `app.middleware`.
- **Correlation ID**:
    - Automatically handled by `CorrelationIdMiddleware`.
    - `X-Request-ID` header is propagated to all logs via `ContextFilter`.
- **Strict Rule**:
    - **FORBIDDEN**: `print()`, `logging.getLogger(__name__)` (in app code).
    - **MANDATORY**: Use `config.get_request_logger`.
    - **Usage**:
      ```python
      from config import get_request_logger
      logger = get_request_logger(__name__)
      logger.info("Message")
      ```
    - For endpoints, use the logger dependency:
      ```python
      async def endpoint(logger = Depends(get_request_logger_dep)):
          logger.info("Accessing endpoint")
      ```

## 6. Naming Conventions
- **Files**: `snake_case.py` (e.g., `sample_model.py`, `sample_service.py`)
- **Classes**: `PascalCase` (e.g., `SampleCreate`, `DatabaseManager`)
- **Variables/Functions**: `snake_case`
- **Constants**: `UPPER_CASE`
- **Directories**: `snake_case`
- **Repositories**: Class names must end with `Repository`
- **Services**: Class names must end with `Service` 
- **Models**: Class names must end with `Model` (unless specific scenarios require otherwise)

## 7. Coding Standards
- **Type Hinting**: Mandatory for all function arguments and return values.
- **Docstrings**: Required for modules, classes, and complex functions.
- **Asynchronous**: Use `async/await` for all I/O bound operations (DB, API calls).
- **Imports**: Organize imports: 
    1. Standard library
    2. Third-party libraries
    3. Local application imports
- **Error Handling**: Use custom exceptions or `HTTPException` with clear error messages.

## 8. Version Control
- **Branching**: Feature branches (e.g., `feature/add-login`)
- **Commits**: Clear, descriptive commit messages.

## 9. Configuration & Environment
- **Library**: `pydantic-settings`
- **Mechanism**:
    1. `config/loader.py` loads `.env` to determine `APP_ENV` (default: `dev`).
    2. Loads corresponding file from `env/{APP_ENV}.env`.
    3. Instantiates config class (e.g., `DevConfig`, `ProdConfig`) inherited from `BaseConfig`.
- **Files**:
    - `env/*.env`: Store secrets and environment-specific variables. **DO NOT COMMIT SECRETS**.
    - `config/base.py`: Define setting schema and defaults.
- **Database Connection**: Managed by `app/config/database_manager.py` using `psycopg_pool`.
- **Strict Rule**:
    - ALL environment variables MUST be defined in `config/base.py` (`BaseConfig`).
    - Usage of `config.settings` is **MANDATORY**.
    - **FORBIDDEN**: Direct usage of `os.getenv()` or `load_dotenv()` in application code (except in `config/loader.py`).

## 10. Testing Standards
- **Mandatory**: Every new feature or bug fix MUST include corresponding unit tests.
- **Scope**:
    - **Unit Tests**: Required for all Services, Repositories, and Utility functions. Isolate dependencies using `unittest.mock`.
    - **Integration Tests**: Required for API endpoints to verify request/response flows (happy path & error cases).
- **Tools**:
    - Runner: `pytest`
    - Async: `pytest-asyncio`
    - API Client: `httpx.AsyncClient`
    - Mocking: `unittest.mock` (Standard Library)
- **Structure**:
    - Place tests in `tests/` directory.
    - Mirror app structure: `tests/unit/` for logic, `tests/api/` for endpoints.
    - File naming: `test_{module_name}.py`.
- **Best Practices**:
    - Test success scenarios (Happy Path).
    - Test failure scenarios (Edge Cases, Exceptions).
    - Use `conftest.py` for shared fixtures (e.g., client, database reset).
    - Do not depend on external services (Redis, DB) for *Unit* tests; mock them.