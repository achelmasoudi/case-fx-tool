# MangoLab FX Tool

A small, production-minded Foreign Exchange (FX) conversion microservice designed for AI agents and automated workflows. The tool fetches European Central Bank (ECB) reference exchange rates via [Frankfurter API](https://frankfurter.dev) with high precision, caching, resilient error handling, and strict financial validation.

---

## Getting Started

### Prerequisites

- Python 3.10+
- Virtual environment with dependencies installed:
  ```bash
  python -m venv .venv
  source .venv/bin/activate  # On Windows: .venv\Scripts\activate
  pip install -r requirements.txt
  ```

### Running the Service

Start the service using the executable runner script:

```bash
./run.sh
```

- **Default Port**: `8080` (can be overridden via `PORT=9000 ./run.sh`)
- **Upstream Host**: defaults to `https://api.frankfurter.dev` (configurable via `FX_UPSTREAM_BASE`)

To check service health:
```bash
curl http://localhost:8080/health
# {"ok": true}
```

### Running the Offline Test Suite

Run the 100% offline test suite:

```bash
./test.sh
```

`test.sh` automatically exports `FX_UPSTREAM_BASE="http://127.0.0.1:54321"` pointing to a closed local port and runs `pytest -v tests/` with `respx` mocks, guaranteeing no external network dependencies.

---

## API Endpoints

### `GET /tools/convert`

Converts a currency amount from a base currency to a target currency for a given calendar date.

#### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `amount` | `float` | Yes | Amount to convert. Must be strictly greater than zero (`amount > 0`). |
| `from` | `string` | Yes | 3-letter ISO base currency code (e.g. `EUR`, `USD`). |
| `to` | `string` | Yes | 3-letter ISO target currency code (e.g. `TRY`, `GBP`). |
| `date` | `string (YYYY-MM-DD)` | Yes | Target calendar date (`1999-01-04 <= date <= today`). |

#### Success Response (`200 OK`)

```json
{
  "amount": 100.0,
  "from": "EUR",
  "to": "TRY",
  "rate": 37.8912,
  "result": 3789.12,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-29",
  "source": "ECB via frankfurter.dev"
}
```

---

## Edge Case Handling

The following table summarizes how the tool deterministically handles all required edge cases:

| Edge Case Scenario | Trigger Condition | System Behavior & Response | Status & Error Code |
|---|---|---|---|
| **Weekends & Bank Holidays** | Query date lands on a Saturday, Sunday, or ECB holiday | Frankfurter resolves to the previous official ECB trading day. The tool sets `rate_date` to the actual ECB fixing date and preserves `asked_date` as the query date. | `200 OK` |
| **Future Dates** | `date > date.today()` | Validation rejects future dates before upstream dispatch to prevent speculative rates. | `400 Bad Request`<br>`"future_date"` |
| **Dates Before 1999-01-04** | `date < 1999-01-04` | Validation rejects dates prior to the official launch of the ECB reference rate series (Jan 4, 1999). | `400 Bad Request`<br>`"date_before_series"` |
| **Currency Does Not Exist** | Unknown / unsupported currency code (e.g. `XYZ`) | Upstream returns 404; handled cleanly as a non-found exchange rate. | `404 Not Found`<br>`"not_found"` |
| **Same Currency (`from == to`)** | Base equals target (e.g. `EUR -> EUR`) | Resolved immediately in memory with `rate = 1.0` and exact amount, bypassing all network calls. | `200 OK` |
| **Non-Positive Amount** | `amount <= 0` | Input validation rejects zero and negative values. | `400 Bad Request`<br>`"invalid_amount"` |
| **High Precision Amounts** | Fractional amounts or multi-decimal rates | Computed using Python `Decimal` arithmetic without floating-point rounding drift, quantized to 2 decimal places using `ROUND_HALF_UP`. | `200 OK` |
| **Upstream Timeout** | Upstream takes longer than 6.0 seconds | Network timeout caught and mapped to standard gateway timeout. | `504 Gateway Timeout`<br>`"upstream_timeout"` |
| **Upstream 5xx / Network Error** | Upstream unavailable, returns 500/503, or connection dropped | Caught and converted to clean gateway error. | `502 Bad Gateway`<br>`"upstream_error"` / `"upstream_unavailable"` |
| **Invalid Upstream Payload** | Non-JSON response or missing `rates` dictionary | Response payload validation catches malformed data. | `502 Bad Gateway`<br>`"invalid_upstream_payload"` |
| **Cache Hit** | Identical `(base, target, asked_date)` | In-memory cache returns cached `(rate, rate_date)` without making upstream HTTP calls. | `200 OK` |

---

## Machine Error Responses

All error responses return a standardized JSON schema:

```json
{
  "error": "<machine_error_code>",
  "message": "<human_readable_explanation>"
}
```

### Registered Error Codes

- `invalid_amount`: The amount provided is less than or equal to zero.
- `future_date`: The requested date is in the future.
- `date_before_series`: The requested date precedes the ECB reference series start (1999-01-04).
- `not_found`: The requested currency pair or rate date was not found upstream.
- `upstream_timeout`: The upstream FX provider failed to respond within the 6-second timeout limit.
- `upstream_unavailable`: The upstream FX provider could not be reached (DNS, connection reset, etc.).
- `upstream_error`: The upstream FX provider returned an HTTP error code (e.g. 500, 503).
- `invalid_upstream_payload`: The upstream provider returned invalid JSON or unexpected response structure.
