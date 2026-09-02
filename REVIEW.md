# Code Review: `tool.py` (Part B)

This document provides an architectural and financial code review of the legacy prototype `tool.py`. Findings are ranked from **most harmful to a paying customer to least harmful**, followed by immediate remediation priorities and an evaluation of patterns that look suspicious but are acceptable.

---

## Ranked Findings (Highest to Lowest Customer Harm)

### 1. Silent Zero Masking Failures (Critical Severity)
- **Code Pattern**:
  ```python
  except Exception:
      return {"rate": 0.0, "result": 0.0}
  ```
- **Why It's Harmful**:
  When any upstream error occurs (network partition, timeout, rate limit, invalid currency, or upstream 500), this catch-all block suppresses the failure and returns an HTTP `200 OK` with zeroed amounts.
  Downstream AI agents, payment gateways, and invoice generation systems treat this `200 OK` as verified truth. This leads to:
  - Free transactions where customer carts are billed at `$0.00`.
  - Legitimate orders being cancelled due to apparent zero-value thresholds.
  - Critical financial data corruption without alerting on-call engineers.
- **Remediation**:
  Propagate errors explicitly with typed exceptions (e.g. `FXError`), mapping failures to proper HTTP error status codes (`400`, `404`, `502`, `504`) with structured machine-readable error bodies (`{"error": "...", "message": "..."}`).

---

### 2. Cache Key Drops Date Parameter (High Severity)
- **Code Pattern**:
  ```python
  cache_key = f"{base}-{target}"
  ```
- **Why It's Harmful**:
  The cache completely ignores the requested date parameter (`on` / `asked_date`).
  If a customer or agent queries historical rates from 2020 (e.g., for back-tax auditing or refund verification), the 2020 exchange rate is stored under `"EUR-USD"`. Every subsequent request for today's market rate receives that stale 2020 price.
  Conversely, a current price check poisons historical lookups. In volatile FX markets, pricing discrepancies cause severe financial arbitrage and margin loss.
- **Remediation**:
  Key the cache on the 3-tuple `(base, target, asked_date_str)`. Historical dates can be cached indefinitely, while today's rates should have a bounded TTL.

---

### 3. Rate Date Hallucination (Medium Severity)
- **Code Pattern**:
  ```python
  "rate_date": str(on or date.today())
  ```
- **Why It's Harmful**:
  The code fabricates the publication date rather than inspecting `payload.get("date")` from the ECB.
  When a user requests a rate for a Saturday, Sunday, or official bank holiday (Good Friday, Easter Monday, New Year's Day), the code reports that the ECB published a reference rate on that weekend day.
  Financial institutions, enterprise ERPs, and compliance auditors cross-reference trade dates against central bank fixing logs. Fabricating trading dates fails regulatory compliance checks and audit trails.
- **Remediation**:
  Extract the actual rate fixing date from the upstream response (`payload["date"]`) and return it as `rate_date`, while echoing the requested query date separately as `asked_date`.

---

### 4. Premature FX Rate Rounding (Medium Severity)
- **Code Pattern**:
  ```python
  rate = round(float(rates[target]), 2)
  result = round(amount * rate, 2)
  ```
- **Why It's Harmful**:
  FX rates are quoted in pips (often 4 to 6 decimal places). Rounding the rate to 2 decimal places *before* multiplying introduces catastrophic rounding error, especially for high-denomination currency pairs:
  - If `1 EUR = 162.458 JPY`, premature rounding turns the rate into `162.46` (pip distortion).
  - For small base units where rate < 0.01 (e.g. `1 IDR = 0.000058 EUR`), the rate rounds directly to `0.00`, zeroing out every conversion completely.
  - Floating point multiplication (`float * float`) also introduces IEEE-754 representation drift (e.g., `100.0 * 1.0892` becoming `108.92000000000002`).
- **Remediation**:
  Preserve full precision using Python's `Decimal` type directly from the string representation. Multiply unrounded rates with `amount`, and apply `ROUND_HALF_UP` quantization to `0.01` only on the final result.

---

### 5. Query Parameter Schema Mismatch (Low-to-Medium Severity)
- **Code Pattern**:
  ```python
  async def convert(amount: float, from_: str, to: str, on: str = None):
  ```
- **Why It's Harmful**:
  FastAPI expects query parameters to match function parameter names unless explicitly aliased.
  Clients and agents passing `GET /tools/convert?from=EUR&date=2024-03-15` will have `from` and `date` ignored or cause FastAPI validation errors because the Python variables are named `from_` and `on`.
- **Remediation**:
  Use explicit FastAPI `Query(..., alias="from")` and `Query(..., alias="date")` to support standard HTTP naming conventions while respecting Python keyword boundaries.

---

## The One I Would Fix Before Shipping Tonight

**Finding #1: Silent Zero Masking Failures.**

Returning `{"rate": 0.0, "result": 0.0}` on failure is a critical financial hazard. In transactional systems, a clean, immediate `502/504` error halts automated execution pipelines, triggers retries, or alerts operations teams. A silent `200 OK` with zero amounts, by contrast, flows through billing and order engines undetected, resulting in direct revenue loss, undercharged customer accounts, and unrecoverable accounting deficits.

---

## Things That Look Suspicious But Are Fine

1. **Global `httpx.AsyncClient()` Connection Reuse Without Lifespan in Small Services**:
   - *Why it looks suspicious*: Linters and strict design guides warn against module-level unmanaged client sessions or unclosed connections.
   - *Why it's fine in practice*: In lightweight Python ASGI processes, keeping an `AsyncClient` open across requests avoids TLS handshakes and TCP connection overhead for high-throughput upstream polling. On modern OS platforms, the OS reclaims all sockets on process termination without socket leaks. (Note: In our final production version, we formalize this via FastAPI's `lifespan` manager for graceful shutdown).

2. **Relying on Frankfurter's Native Previous-Trading-Day Resolution for Weekends**:
   - *Why it looks suspicious*: The service does not maintain an internal calendar of ECB bank holidays, weekends, or TARGET2 operating schedules.
   - *Why it's fine in practice*: The European Central Bank does not publish fixing rates on weekends or TARGET2 holidays. The Frankfurter API handles calendar rollbacks natively according to official ECB convention, resolving requests on non-trading days to the last valid fixing session. Delegating this to the authoritative upstream service avoids maintaining brittle, hardcoded holiday schedules in application code.
