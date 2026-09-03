# Engineering Notes & Architecture Decisions

This document outlines key engineering decisions, future architecture enhancements, tooling notes, and reflections from the MangoLab FX Tool implementation.

---

## 1. Architectural & Design Decisions

### Non-Trading ECB Dates (Weekends & Holidays)
- **Problem**: The European Central Bank does not publish currency reference rates on Saturdays, Sundays, or TARGET2 bank holidays (e.g. Good Friday, Easter Monday, Christmas Day).
- **Decision**: Rely on Frankfurter API's calendar mapping to the prior trading day while distinguishing between `asked_date` (the user's calendar query) and `rate_date` (the ECB's actual fixing publication date).
- **Rationale**: Preserving both fields allows downstream audit logs to verify that the query was for a weekend (e.g., Saturday 2026-08-29) while confirming that the rate applied was from the preceding Friday fixing (2026-08-28).

### High-Precision Decimal Math
- **Problem**: Standard IEEE-754 floating-point arithmetic introduces rounding drift (e.g., `100.0 * 1.0892` can produce `108.92000000000002`). Premature rounding on small base currencies (like JPY or IDR) leads to compounding errors or zeroed figures.
- **Decision**: Read upstream rates directly from strings into Python `Decimal` instances (`Decimal(str(rates[target]))`). Compute intermediate results at full precision and quantize the final result to two decimal places using deterministic commercial rounding (`ROUND_HALF_UP`).
- **Rationale**: Eliminates precision loss across high-volume conversion pipelines and ensures predictable currency calculations.

### Strict Input Validation
- **Problem**: Malformed or speculative requests cause upstream thrashing and bad data in downstream models.
- **Decision**:
  - Rejection of `amount <= 0` with `400 Bad Request` (`invalid_amount`).
  - Rejection of `asked_date > date.today()` with `400 Bad Request` (`future_date`).
  - Rejection of `asked_date < 1999-01-04` with `400 Bad Request` (`date_before_series`).
- **Rationale**: Bounding valid dates and positive amounts upfront prevents wasted upstream network calls and provides clear, immediate feedback to calling agents.

### Local Same-Currency Bypass
- **Problem**: When `from == to` (e.g. `EUR -> EUR`), network calls to upstream APIs introduce unnecessary latency, consume rate limits, and risk external failure points.
- **Decision**: Detect identical currency codes after whitespace trimming and uppercase normalization, returning `rate = 1.0` immediately in memory.
- **Rationale**: Instant sub-millisecond execution, zero network overhead, and 100% availability for identical-currency conversions even during external upstream outages.

---

## 2. With Another Day: Next-Level Enhancements

If given an additional development sprint, the following production enhancements would be implemented:

1. **Distributed Caching (Redis) with Differentiated TTLs**:
   - Replace the single-process in-memory dictionary with a distributed Redis cluster.
   - **Historical Dates** (`asked_date < today`): Cache permanently (immutable TTL), since central bank historical fixing rates never change once published.
   - **Today's Rates** (`asked_date == today`): Cache with a 1-hour sliding TTL until the ECB publishes the official 16:00 CET daily fixing.

2. **Circuit Breaker Pattern**:
   - Implement a circuit breaker (e.g. using `tenacity` or `pybreaker`).
   - If the upstream provider experiences consecutive 5xx errors or connection timeouts exceeding a threshold (e.g., 5 failures in 30 seconds), trip the breaker to fast-fail subsequent requests and spare connection pools until the upstream recovers.

3. **Active Health Probing / Ping Probes**:
   - Enhance the `/health` endpoint into a deep health check that can run periodic background pings against Frankfurter's `/v1/latest` endpoint, providing real-time upstream latency metrics and operational status to Kubernetes / cloud load balancers.

---

## 3. AI Tooling Usage

Development was conducted inside **Google Antigravity**, leveraging its agentic IDE capabilities:
- **Project Scaffolding**: Fast generation of Pydantic v2 data models, FastAPI lifespan configuration, and HTTP connection management.
- **Comprehensive Mock Test Generation**: Rapid construction of offline integration tests using `respx` and `pytest-asyncio`, ensuring complete isolation from external networks.
- **Codebase Auditing**: Deep static analysis to identify subtle edge-case flaws in prototype implementations, such as silent exception suppression and cache poisoning.

---

## 4. One Thing the AI Got Wrong

- **Initial Issue**:
  During the initial calculation logic, the assistant suggested multiplying the raw floating-point values directly (`result = round(amount * float(rate), 2)`).
- **Why It Was Inadequate**:
  In financial applications, converting currency rates to standard Python floats before multiplication exposes calculations to binary floating-point representation artifacts (e.g. `0.1 + 0.2 != 0.3`). For large transaction volumes or currencies with very small exchange rates (e.g. `1 IDR = 0.000058 EUR`), float operations lose precision and can round down to zero prematurely.
- **The Correction**:
  The approach was explicitly overridden with Python's native `decimal` module:
  ```python
  rate = Decimal(str(rates[target]))
  result = (Decimal(str(amount)) * rate).quantize(
      Decimal("0.01"), rounding=ROUND_HALF_UP
  )
  ```
  This guarantees exact decimal arithmetic and deterministic rounding according to financial standards.
