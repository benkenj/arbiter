# Testing Patterns

**Analysis Date:** 2026-02-22

## Test Framework

**Runner:**
- pytest 8.0+
- pytest-asyncio 0.23+ for async test support
- Config: Not explicitly configured; defaults used

**Assertion Library:**
- pytest built-in assertions (not using dedicated library)

**Run Commands:**
```bash
pytest                 # Run all tests (expected)
pytest -v              # Verbose output (expected)
pytest --asyncio-mode=auto  # Run async tests (pytest-asyncio)
pytest -k test_name    # Run specific test (expected)
pytest --cov=arbiter   # Coverage report (expected, if coverage installed)
```

## Test File Organization

**Location:**
- Not detected in current codebase
- Project structure suggests co-located pattern would be used (e.g., `tests/` directory at root)

**Naming:**
- No existing test files; following convention: `test_*.py` or `*_test.py`

**Structure:**
```
tests/
├── test_clients/
│   ├── test_polymarket.py
│   └── test_kalshi.py
├── test_matching/
│   ├── test_embedder.py
│   └── test_matcher.py
├── test_detection/
│   └── test_detector.py
├── test_notifications/
│   └── test_discord.py
└── conftest.py
```

## Test Structure

**Suite Organization:**
```python
# Expected pattern based on project structure
import pytest
from arbiter.clients.polymarket import PolymarketClient, Market

@pytest.mark.asyncio
class TestPolymarketClient:
    async def test_list_markets_success(self):
        # Test implementation
        pass

    async def test_get_market_single(self):
        # Test implementation
        pass

    async def test_parse_json_field_handles_strings(self):
        # Test implementation
        pass
```

**Patterns:**
- Async test functions use `@pytest.mark.asyncio` decorator
- Async context managers use `async with` in fixtures
- Class-based test grouping by component (PolymarketClient, KalshiClient, etc.)
- Setup/teardown likely via pytest fixtures

## Mocking

**Framework:** Not explicitly configured; unittest.mock expected

**Patterns:**
```python
# Expected mocking pattern based on httpx usage
from unittest.mock import AsyncMock, patch
from arbiter.clients.polymarket import PolymarketClient

@pytest.mark.asyncio
async def test_list_markets_mocked():
    with patch('arbiter.clients.polymarket.httpx.AsyncClient') as mock_client:
        mock_client.get = AsyncMock(return_value=mock_response)
        client = PolymarketClient()
        markets = await client.list_markets()
        assert len(markets) > 0
```

**What to Mock:**
- HTTP requests (httpx.AsyncClient): All API calls should be mocked
- Claude API calls (Anthropic SDK): Expensive LLM calls must be mocked
- Database operations: Use fixtures or in-memory test database
- Discord webhook calls: Mock outbound notifications

**What NOT to Mock:**
- Pydantic model validation
- Local embedding generation (sentence-transformers running locally is acceptable)
- pgvector similarity calculations (use test database)
- Core business logic functions

## Fixtures and Factories

**Test Data:**
```python
# Expected fixture pattern
@pytest.fixture
async def polymarket_client():
    async with PolymarketClient() as client:
        yield client
        # teardown

@pytest.fixture
def sample_market():
    return Market(
        id="123",
        question="Will Bitcoin reach $100k?",
        description="Test market",
        end_date="2026-12-31",
        outcomes=["Yes", "No"],
        outcome_prices=["0.65", "0.35"],
        clob_token_ids=["token1", "token2"],
    )

@pytest.fixture
def sample_markets_list(sample_market):
    return [sample_market, sample_market]
```

**Location:**
- `tests/conftest.py` for shared fixtures across test suite
- Local fixtures within test modules for component-specific setup

## Coverage

**Requirements:** Not enforced; no coverage configuration in `pyproject.toml`

**View Coverage:**
```bash
pytest --cov=arbiter --cov-report=html
# Coverage report generated in htmlcov/index.html
```

## Test Types

**Unit Tests:**
- Scope: Individual functions and methods
- Approach: Test client methods with mocked HTTP responses
- Focus: `PolymarketClient.list_markets()`, `_parse_json_field()`, property methods
- Example: Verify `yes_price` property returns float when data valid, None when invalid

**Integration Tests:**
- Scope: API client + HTTP layer
- Approach: Mock httpx responses, verify full Market parsing flow
- Focus: End-to-end response handling, error cases
- Example: Verify malformed JSON in API response handled gracefully

**E2E Tests:**
- Framework: Not present in current codebase
- Expected approach: Use testcontainers or live API with rate limiting
- Focus: Real market discovery against Kalshi/Polymarket APIs (slow, run separately)

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_async_operation():
    async with PolymarketClient() as client:
        result = await client.list_markets()
        assert isinstance(result, list)

# Alternative: use pytest-asyncio auto mode
# Configure in pyproject.toml:
# [tool.pytest.ini_options]
# asyncio_mode = "auto"
```

**Error Testing:**
```python
@pytest.mark.asyncio
async def test_api_error_raised():
    with patch('arbiter.clients.polymarket.httpx.AsyncClient.get') as mock_get:
        mock_get.side_effect = httpx.HTTPError("API down")
        client = PolymarketClient()
        with pytest.raises(httpx.HTTPError):
            await client.list_markets()

@pytest.mark.asyncio
async def test_malformed_response_returns_defaults():
    # Verify _parse_json_field returns [] on JSONDecodeError
    result = _parse_json_field("{invalid json}")
    assert result == []
```

---

*Testing analysis: 2026-02-22*
