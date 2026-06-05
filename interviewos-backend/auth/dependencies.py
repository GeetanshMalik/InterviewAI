from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from config import settings
from auth.service import get_user_for_token
from services.repositories.manager import persistence_manager
from services.store import store


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials:
        if persistence_manager.enabled:
            user = await run_in_threadpool(get_user_for_token, credentials.credentials)
        else:
            user = get_user_for_token(credentials.credentials)
        if user:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    if settings.app_env == "development" and settings.allow_dev_auth_fallback:
        return store.get_demo_user()

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


async def get_optional_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    return credentials.credentials if credentials else None
