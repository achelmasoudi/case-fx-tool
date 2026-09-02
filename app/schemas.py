from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ConvertSuccessResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    amount: float
    from_: str = Field(..., serialization_alias="from", validation_alias=AliasChoices("from", "from_"))
    to: str
    rate: float
    result: float
    rate_date: str
    asked_date: str
    source: str = "ECB via frankfurter.dev"


class ErrorResponse(BaseModel):
    error: str
    message: str
