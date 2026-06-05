from fastapi import APIRouter, Depends

from auth.dependencies import get_current_user, get_optional_token
from auth.models import AuthResponse, LoginRequest, LogoutRequest, RefreshRequest, SignupRequest, UserPublic
from auth.service import delete_session_refresh_token, delete_session_token
from auth.service import login as login_user
from auth.service import refresh_session
from auth.service import signup as signup_user
from services.store import store


router = APIRouter()


@router.post("/signup", response_model=AuthResponse)
def signup(payload: SignupRequest):
    return signup_user(payload.name, payload.email, payload.password)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    return login_user(payload.email, payload.password)


@router.get("/me", response_model=UserPublic)
async def me(current_user: dict = Depends(get_current_user)):
    return store.public_user(current_user)


@router.post("/logout")
def logout(payload: LogoutRequest | None = None, token: str | None = Depends(get_optional_token)):
    if token:
        delete_session_token(token)
    if payload and payload.refresh_token:
        delete_session_refresh_token(payload.refresh_token)
    return {"message": "Logged out"}


@router.post("/refresh", response_model=AuthResponse)
def refresh(payload: RefreshRequest):
    return refresh_session(payload.refresh_token)
