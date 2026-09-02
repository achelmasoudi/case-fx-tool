import os
from datetime import date
from decimal import Decimal
import httpx


class FXError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def get_upstream_base_url() -> str:
    return os.getenv("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/")


# In-memory cache keyed by (base, target, asked_date_str) -> (rate, rate_date)
_CACHE: dict[tuple[str, str, str], tuple[Decimal, str]] = {}


async def get_conversion_rate(
    client: httpx.AsyncClient,
    base: str,
    target: str,
    asked_date: date,
) -> tuple[Decimal, str]:
    base = base.strip().upper()
    target = target.strip().upper()
    asked_date_str = asked_date.isoformat()

    if base == target:
        return Decimal("1.0"), asked_date_str

    cache_key = (base, target, asked_date_str)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    base_url = get_upstream_base_url()
    url = f"{base_url}/v1/{asked_date_str}"
    params = {"base": base, "symbols": target}

    try:
        response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise FXError(
            "upstream_timeout",
            "Upstream FX service timed out.",
            status_code=504,
        ) from exc
    except httpx.RequestError as exc:
        raise FXError(
            "upstream_unavailable",
            f"Upstream FX service is unavailable: {exc}",
            status_code=502,
        ) from exc

    if response.status_code == 404:
        raise FXError(
            "not_found",
            f"Exchange rate not found for {base}->{target} on {asked_date_str}.",
            status_code=404,
        )

    if response.status_code != 200:
        raise FXError(
            "upstream_error",
            f"Upstream FX service returned status {response.status_code}.",
            status_code=502,
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise FXError(
            "invalid_upstream_payload",
            "Upstream FX service returned invalid JSON payload.",
            status_code=502,
        ) from exc

    try:
        rates = payload.get("rates", {})
        if not isinstance(rates, dict) or target not in rates:
            raise FXError(
                "invalid_upstream_payload",
                f"Target currency '{target}' not found in upstream rates.",
                status_code=502,
            )
        rate = Decimal(str(rates[target]))
    except FXError:
        raise
    except Exception as exc:
        raise FXError(
            "invalid_upstream_payload",
            f"Unable to parse rate for '{target}' from upstream payload: {exc}",
            status_code=502,
        ) from exc

    rate_date = str(payload.get("date") or asked_date_str)
    result = (rate, rate_date)
    _CACHE[cache_key] = result
    return result
