import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100, description="Business / site name")
    description: str = Field(
        min_length=10,
        max_length=1000,
        description="Plain-language description of the site you want",
    )


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    subdomain: str
    description: str
    category: str
    status: str
    status_detail: str | None = None
    url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
