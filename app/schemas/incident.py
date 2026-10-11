
from pydantic import BaseModel, ConfigDict, Field


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    service: str = Field(min_length=2, max_length=100)
    error_message: str | None = Field(default=None, max_length=2000)
    affected_users: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    service: str
    error_message: str | None
    affected_users: int
    error_count: int
    severity: str
    status: str
    created_by: int
    assigned_to: int | None
    root_cause: str | None
    resolution: str | None


class IncidentResolve(BaseModel):
    root_cause: str = Field(min_length=5, max_length=2000)
    resolution: str = Field(min_length=5, max_length=2000)
