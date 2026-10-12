
from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    


class UserUpdate(BaseModel):
    name: str
    email: str
    role: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str


class UserLogin(BaseModel):
    email: str
    password: str
