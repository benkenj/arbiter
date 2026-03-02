import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
DATA_API_BASE_URL = "https://data-api.polymarket.com"

logger = logging.getLogger(__name__)


def _parse_json_field(value: str | list | None, field_name: str = "") -> list:
    """Gamma API sometimes returns list fields as JSON strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        if field_name:
            logger.warning("Failed to parse JSON field '%s': %r", field_name, str(value)[:100])
        return []


class Market(BaseModel):
    id: str
    question: str
    description: Optional[str] = None
    end_date: Optional[str] = None
    closed: bool = False
    resolved: bool = False
    # Outcome labels, e.g. ["Yes", "No"]
    outcomes: list[str] = []
    # Implied probabilities matching outcomes, e.g. ["0.65", "0.35"]
    outcome_prices: list[str] = []
    # Token IDs used for CLOB order book lookups
    clob_token_ids: list[str] = []
    condition_id: Optional[str] = None
    volume: Optional[float] = None
    liquidity: Optional[float] = None
    fetched_at: Optional[datetime] = None

    @property
    def yes_price(self) -> Optional[float]:
        """Implied probability of the first (Yes) outcome."""
        if self.outcome_prices:
            try:
                return float(self.outcome_prices[0])
            except ValueError:
                return None
        return None

    @property
    def no_price(self) -> Optional[float]:
        """Implied probability of the second (No) outcome."""
        if len(self.outcome_prices) > 1:
            try:
                return float(self.outcome_prices[1])
            except ValueError:
                return None
        return None


class Trade(BaseModel):
    proxy_wallet: str = Field(alias="proxyWallet")
    side: str                       # "BUY" | "SELL"
    size: float
    price: float
    timestamp: int                  # Unix seconds (integer)
    condition_id: str = Field(alias="conditionId")
    outcome: Optional[str] = None   # "Yes" | "No" — which outcome token was traded

    model_config = ConfigDict(populate_by_name=True)


class PolymarketClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=GAMMA_BASE_URL,
            timeout=30.0,
            headers={"Accept": "application/json"},
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._data_client = httpx.AsyncClient(
            base_url=DATA_API_BASE_URL,
            timeout=30.0,
            headers={"Accept": "application/json"},
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    def _parse_market(self, item: dict) -> Market:
        """Parse a single market dict from the Gamma API into a Market model."""
        return Market(
            id=str(item.get("id", "")),
            question=item.get("question", ""),
            description=item.get("description"),
            end_date=item.get("endDate"),
            closed=item.get("closed", False),
            resolved=item.get("resolved", False),
            outcomes=_parse_json_field(item.get("outcomes"), "outcomes"),
            outcome_prices=_parse_json_field(item.get("outcomePrices"), "outcomePrices"),
            clob_token_ids=_parse_json_field(item.get("clobTokenIds"), "clobTokenIds"),
            condition_id=item.get("conditionId"),
            volume=item.get("volume"),
            liquidity=item.get("liquidityClob"),
        )

    @retry(
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException)
        ),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _fetch_page(self, offset: int, limit: int) -> list[Market]:
        """Fetch a single page of active markets from the Gamma API (with retry)."""
        params = {
            "active": True,
            "closed": False,
            "archived": False,
            "limit": limit,
            "offset": offset,
        }
        response = await self._client.get("/markets", params=params)
        response.raise_for_status()
        return [self._parse_market(item) for item in response.json()]

    async def fetch_all_active_markets(self) -> list[Market]:
        """Fetch all active markets across all pages."""
        all_markets: list[Market] = []
        offset = 0
        limit = 100
        while True:
            batch = await self._fetch_page(offset=offset, limit=limit)
            all_markets.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        return all_markets

    async def list_markets(
        self,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Market]:
        """Fetch markets from the Gamma API (single page, backward compat)."""
        return await self._fetch_page(offset=offset, limit=limit)

    async def get_market(self, market_id: str) -> Market:
        """Fetch a single market by ID."""
        response = await self._client.get(f"/markets/{market_id}")
        response.raise_for_status()
        item = response.json()
        return self._parse_market(item)

    @retry(
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException)
        ),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _fetch_clob_page(
        self, condition_id: str, offset: int, limit: int
    ) -> list[Trade]:
        params = {
            "market": condition_id,
            "takerOnly": "false",   # MUST be false — get all trades, not just taker-side
            "limit": limit,
            "offset": offset,
        }
        response = await self._data_client.get("/trades", params=params)
        response.raise_for_status()
        return [Trade.model_validate(item) for item in response.json()]

    async def get_trades_for_market(
        self,
        condition_id: str,
        since: Optional[datetime] = None,
        page_size: int = 500,
    ) -> list[Trade]:
        """
        Fetch trades for a market, returning only those newer than `since`.
        API returns newest-first; stops paging when a page is fully older than watermark.
        Returns all trades if since is None (initial backfill).
        """
        all_trades: list[Trade] = []
        offset = 0
        since_ts: Optional[int] = int(since.timestamp()) if since else None

        while True:
            page = await self._fetch_clob_page(condition_id, offset, page_size)
            if not page:
                break

            if since_ts is not None:
                new_trades = [t for t in page if t.timestamp > since_ts]
                all_trades.extend(new_trades)
                if len(new_trades) < len(page):
                    break
            else:
                all_trades.extend(page)

            if len(page) < page_size:
                break
            offset += page_size

        return all_trades

    async def close(self):
        await self._client.aclose()
        await self._data_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
