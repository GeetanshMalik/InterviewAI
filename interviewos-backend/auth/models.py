from pydantic import BaseModel


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    avatar: str | None = None
    createdAt: str
    updatedAt: str


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class AuthResponse(BaseModel):
    user: UserPublic
    token: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
