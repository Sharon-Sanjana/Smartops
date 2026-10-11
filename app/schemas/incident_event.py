
from pydantic import BaseModel, ConfigDict, Field


class IncidentEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=50)
    description: str = Field(min_length=5, max_length=1000)


class IncidentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    user_id: int
    event_type: str
    description: str
