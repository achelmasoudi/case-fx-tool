from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app.fx import FXError, get_conversion_rate
from app.schemas import ConvertSuccessResponse, ErrorResponse

http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=6.0)
    yield
    if http_client and not http_client.is_closed:
        await http_client.aclose()


app = FastAPI(
    title="MangoLab FX Tool",
    description="Foreign Exchange conversion tool with ECB rates via Frankfurter API",
    lifespan=lifespan,
)


@app.exception_handler(FXError)
async def fx_error_handler(request: Request, exc: FXError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "message": exc.message},
    )


@app.get(
    "/tools/convert",
    response_model=ConvertSuccessResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def convert(
    amount: float = Query(...),
    from_: str = Query(..., alias="from", min_length=3, max_length=3),
    to: str = Query(..., min_length=3, max_length=3),
    asked_date: date = Query(..., alias="date"),
):
    if amount <= 0:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_amount",
                "message": "Conversion amount must be strictly greater than zero.",
            },
        )

    if asked_date > date.today():
        return JSONResponse(
            status_code=400,
            content={
                "error": "future_date",
                "message": f"Cannot fetch exchange rate for future date {asked_date}.",
            },
        )

    if asked_date < date(1999, 1, 4):
        return JSONResponse(
            status_code=400,
            content={
                "error": "date_before_series",
                "message": "ECB reference series begins on 1999-01-04.",
            },
        )

    global http_client
    if http_client is None or http_client.is_closed:
        http_client = httpx.AsyncClient(timeout=6.0)

    rate, rate_date = await get_conversion_rate(http_client, from_, to, asked_date)
    result = (Decimal(str(amount)) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "amount": amount,
        "from": from_.upper().strip(),
        "to": to.upper().strip(),
        "rate": float(rate),
        "result": float(result),
        "rate_date": rate_date,
        "asked_date": asked_date.isoformat(),
        "source": "ECB via frankfurter.dev",
    }


@app.get("/health")
async def health():
    return {"ok": True}
