# Coding Conventions

**Analysis Date:** 2026-02-22

## Naming Patterns

**Files:**
- Lowercase with underscores: `polymarket.py`, `__init__.py`
- Helper/internal functions prefixed with single underscore: `_parse_json_field`
- Module structure follows function grouping: API clients in `clients/`, database models in `db/`, etc.

**Functions:**
- Snake_case for all function names: `list_markets()`, `get_market()`, `get_prices()`, `main_sync()`
- Async functions use `async def`: `async def main()`, `async def list_markets()`
- Private/internal functions prefixed with underscore: `_parse_json_field()`
- Dunder methods allowed: `__init__()`, `__aenter__()`, `__aexit__()`

**Variables:**
- Snake_case for all variables: `yes_price`, `clob_token_ids`, `end_date`, `condition_id`
- Constants in UPPERCASE: `GAMMA_BASE_URL`
- Private variables prefixed with underscore: `self._client`, `self._parse_json_field()`

**Types:**
- PascalCase for class names: `Market`, `PolymarketClient`, `BaseModel`
- Type hints use modern Python 3.12+ syntax: `list[str]` not `List[str]`, union with `|` not `Union`
- Optional fields use `Optional[str]` from typing: `description: Optional[str] = None`

## Code Style

**Formatting:**
- No explicit formatter configuration found in `pyproject.toml`
- No `.prettierrc`, `.ruff.toml`, or other formatting config present
- Following Python standard conventions: 4-space indentation observed
- Blank lines between class definitions and between function definitions

**Linting:**
- No explicit linter configuration in project
- No `.eslintrc`, `ruff.toml`, or `pyproject.toml` tool sections for linting
- Project appears to rely on manual adherence to conventions

## Import Organization

**Order:**
1. Standard library imports: `import json`, `import asyncio`
2. Third-party imports: `import httpx`, `from pydantic import BaseModel`
3. Local imports: `from arbiter.clients.polymarket import PolymarketClient`

**Pattern:**
- Each import on separate line within groups
- Relative imports not used; fully qualified imports preferred
- Standard library and third-party clearly separated

**Path Aliases:**
- No path aliases detected; fully qualified paths used throughout: `from arbiter.clients.polymarket import ...`

## Error Handling

**Patterns:**
- Try-except blocks used for specific error cases
- Specific exception types caught: `except (json.JSONDecodeError, TypeError)`
- Empty except blocks return safe defaults rather than raising: `_parse_json_field()` returns `[]` on error
- HTTP errors surfaced explicitly: `response.raise_for_status()` called after API requests
- Property methods handle conversion errors gracefully: `except ValueError: return None`

**Example:**
```python
try:
    return float(self.outcome_prices[0])
except ValueError:
    return None
```

## Logging

**Framework:** Console output via `print()` statements

**Patterns:**
- Informational print statements in main execution flow: `print("Fetching markets...")`
- F-strings used for formatted output: `print(f"Returned {len(markets)} markets\n")`
- Structured output with newlines for readability: triple-spaced market display in `main.py`
- No logger abstraction layer; direct `print()` calls

## Comments

**When to Comment:**
- Used sparingly, only for non-obvious API behavior
- Comment clarifies Gamma API quirk: `"""Gamma API sometimes returns list fields as JSON strings."""`
- Field-level comments explain data format: `# Outcome labels, e.g. ["Yes", "No"]`
- Implementation detail comments on complex parsing logic

**JSDoc/TSDoc:**
- Docstrings on function definitions: `def _parse_json_field(value: str | list | None) -> list:`
- Triple-quoted docstrings with explanation: `"""Fetch markets from the Gamma API."""`
- Property docstrings explain intent: `"""Implied probability of the first (Yes) outcome."""`

## Function Design

**Size:**
- Narrow scope: `_parse_json_field()` handles single responsibility (JSON field parsing)
- Client methods focused: `list_markets()` does pagination query, `get_market()` gets single market
- Main entry point short: `main_sync()` is 1-line async runner

**Parameters:**
- Optional parameters with defaults: `limit: int = 100, offset: int = 0`
- Type hints on all parameters: `market_id: str`, `value: str | list | None`
- Async context managers use `*args` for cleanup: `async def __aexit__(self, *args)`

**Return Values:**
- Type hints on all return statements: `-> list[Market]`, `-> Optional[float]`
- Consistent return types across function signatures
- Models returned as Pydantic BaseModel instances for validation

## Module Design

**Exports:**
- Public classes exported at module level: `class Market(BaseModel)`, `class PolymarketClient`
- Private functions prefixed with underscore not exported: `_parse_json_field()`
- Empty `__init__.py` files allow package imports but no explicit exports

**Barrel Files:**
- `arbiter/clients/__init__.py` is empty (no re-exports)
- `arbiter/__init__.py` is empty
- Clients imported directly: `from arbiter.clients.polymarket import PolymarketClient`

---

*Convention analysis: 2026-02-22*
