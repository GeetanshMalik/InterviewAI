import asyncio
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import get_current_user
from auth.service import hash_password, verify_password
from services.repository_service import repository_service
from services.store import iso_now, store


router = APIRouter()


class ProfileUpdate(BaseModel):
    name: str | None = None
    avatar_url: str | None = None
    avatar: str | None = None
    headline: str | None = None
    location: str | None = None
    website: str | None = None
    linkedin: str | None = None
    github: str | None = None
    bio: str | None = None


class AIPreferencesUpdate(BaseModel):
    preferred_language: str | None = None
    ai_memory_enabled: bool | None = None
    defaultDifficulty: str | None = None
    personality: str | None = None
    voiceEnabled: bool | None = None
    language: str | None = None
    interviewVoiceProfile: str | None = None


class AppearanceUpdate(BaseModel):
    theme: str = "dark"


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile: dict[str, Any] | None = None
    ai: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    integrations: dict[str, Any] | None = None
    appearance: dict[str, Any] | None = None
    security: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    interview: dict[str, Any] | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


def practice_question_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 20
    return min(30, max(5, parsed))


def default_settings_for(user: dict) -> dict[str, Any]:
    return {
        "profile": {
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "avatar": user.get("avatar"),
            "headline": user.get("headline", ""),
            "location": user.get("location", ""),
            "website": user.get("website", ""),
            "linkedin": user.get("linkedin", ""),
            "github": user.get("github", ""),
            "bio": user.get("bio", ""),
        },
        "ai": {
            "defaultDifficulty": user.get("default_difficulty", "medium"),
            "personality": user.get("ai_personality", "professional"),
            "voiceEnabled": bool(user.get("voice_enabled", True)),
            "language": user.get("ai_language", "en"),
            "interviewVoiceProfile": user.get("interview_voice_profile", "en-IN-female-1"),
            "memoryEnabled": bool(user.get("ai_memory_enabled", True)),
            "responseStyle": user.get("ai_response_style", "balanced"),
        },
        "memory": {
            "dataRetentionDays": int(user.get("data_retention_days", 90)),
            "allowDataCollection": bool(user.get("allow_data_collection", True)),
            "storeChatHistory": bool(user.get("store_chat_history", True)),
            "includeResumeContext": bool(user.get("include_resume_context", True)),
        },
        "integrations": {
            "calendar": {"enabled": False, "provider": ""},
            "linkedin": {"connected": False},
            "github": {"connected": False},
        },
        "appearance": {
            "theme": user.get("appearance_theme", "dark"),
            "accentColor": user.get("accent_color", "#6670f0"),
            "fontSize": user.get("font_size", "medium"),
            "compactDashboard": bool(user.get("compact_dashboard", False)),
            "reduceMotion": bool(user.get("reduce_motion", False)),
        },
        "security": {
            "twoFactorEnabled": bool(user.get("two_factor_enabled", False)),
            "activeSessions": [],
        },
        "notifications": {
            "emailReports": bool(user.get("email_reports", True)),
            "weeklyDigest": bool(user.get("weekly_digest", True)),
            "practiceReminders": bool(user.get("practice_reminders", False)),
            "roadmapReminders": bool(user.get("roadmap_reminders", True)),
        },
        "interview": {
            "defaultRole": user.get("default_role", ""),
            "defaultCompanyStyle": user.get("default_company_style", "product"),
            "defaultLanguage": user.get("preferred_language", "javascript"),
            "practiceQuestionCount": practice_question_count(user.get("practice_question_count", 20)),
            "showExecutionLogs": bool(user.get("show_execution_logs", True)),
            "autoSaveAnswers": bool(user.get("auto_save_answers", True)),
        },
    }


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def public_settings(user: dict) -> dict[str, Any]:
    settings = deep_merge(default_settings_for(user), user.get("settings") or {})
    interview = settings.setdefault("interview", {})
    interview["practiceQuestionCount"] = practice_question_count(interview.get("practiceQuestionCount", 20))
    return settings


def persist_settings(user: dict, updates: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
    settings = deep_merge(public_settings(user), updates)
    profile = settings.get("profile") or {}
    ai = settings.get("ai") or {}
    memory = settings.get("memory") or {}
    appearance = settings.get("appearance") or {}
    notifications = settings.get("notifications") or {}
    interview = settings.get("interview") or {}

    user["settings"] = settings
    user["name"] = profile.get("name") or user.get("name", "")
    user["avatar"] = profile.get("avatar")
    user["headline"] = profile.get("headline", "")
    user["location"] = profile.get("location", "")
    user["website"] = profile.get("website", "")
    user["linkedin"] = profile.get("linkedin", "")
    user["github"] = profile.get("github", "")
    user["bio"] = profile.get("bio", "")
    user["ai_language"] = ai.get("language", "en")
    user["preferred_language"] = interview.get("defaultLanguage") or user.get("preferred_language", "javascript")
    user["default_difficulty"] = ai.get("defaultDifficulty", "medium")
    user["ai_personality"] = ai.get("personality", "professional")
    user["voice_enabled"] = bool(ai.get("voiceEnabled", True))
    user["interview_voice_profile"] = ai.get("interviewVoiceProfile", "en-IN-female-1")
    user["ai_memory_enabled"] = bool(ai.get("memoryEnabled", True))
    user["ai_response_style"] = ai.get("responseStyle", "balanced")
    user["appearance_theme"] = appearance.get("theme", "dark")
    user["accent_color"] = appearance.get("accentColor", "#6670f0")
    user["font_size"] = appearance.get("fontSize", "medium")
    user["compact_dashboard"] = bool(appearance.get("compactDashboard", False))
    user["reduce_motion"] = bool(appearance.get("reduceMotion", False))
    user["data_retention_days"] = int(memory.get("dataRetentionDays", 90))
    user["allow_data_collection"] = bool(memory.get("allowDataCollection", True))
    user["store_chat_history"] = bool(memory.get("storeChatHistory", True))
    user["include_resume_context"] = bool(memory.get("includeResumeContext", True))
    user["email_reports"] = bool(notifications.get("emailReports", True))
    user["weekly_digest"] = bool(notifications.get("weeklyDigest", True))
    user["practice_reminders"] = bool(notifications.get("practiceReminders", False))
    user["roadmap_reminders"] = bool(notifications.get("roadmapReminders", True))
    user["default_role"] = interview.get("defaultRole", "")
    user["default_company_style"] = interview.get("defaultCompanyStyle", "product")
    interview["practiceQuestionCount"] = practice_question_count(interview.get("practiceQuestionCount", 20))
    user["practice_question_count"] = interview["practiceQuestionCount"]
    user["show_execution_logs"] = bool(interview.get("showExecutionLogs", True))
    user["auto_save_answers"] = bool(interview.get("autoSaveAnswers", True))
    user["updatedAt"] = iso_now()
    repository_service.update_user(user, commit=commit)
    return public_settings(user)


@router.get("")
async def get_settings(current_user: dict = Depends(get_current_user)):
    return public_settings(current_user)


@router.put("")
async def update_settings(payload: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    updates = payload.model_dump(exclude_unset=True)
    settings = persist_settings(current_user, updates, commit=False)
    await repository_service.commit_async()
    return settings


@router.put("/profile")
async def update_profile(payload: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    updates = {"profile": payload.model_dump(exclude_unset=True)}
    if payload.avatar_url is not None:
        updates["profile"]["avatar"] = payload.avatar_url
        updates["profile"].pop("avatar_url", None)
    persist_settings(current_user, updates, commit=False)
    await repository_service.commit_async()
    return store.public_user(current_user)


@router.put("/ai-preferences")
async def update_ai_preferences(payload: AIPreferencesUpdate, current_user: dict = Depends(get_current_user)):
    updates = payload.model_dump(exclude_unset=True)
    ai_updates: dict[str, Any] = {}
    interview_updates: dict[str, Any] = {}
    if "language" in updates:
        ai_updates["language"] = updates["language"]
    if "preferred_language" in updates:
        interview_updates["defaultLanguage"] = updates["preferred_language"]
    if "ai_memory_enabled" in updates:
        ai_updates["memoryEnabled"] = updates["ai_memory_enabled"]
    for key in ("defaultDifficulty", "personality", "voiceEnabled", "interviewVoiceProfile"):
        if key in updates:
            ai_updates[key] = updates[key]
    payload_updates: dict[str, Any] = {"ai": ai_updates}
    if interview_updates:
        payload_updates["interview"] = interview_updates
    settings = persist_settings(current_user, payload_updates, commit=False)
    await repository_service.commit_async()
    return {"message": "Updated", "ai": settings["ai"]}


@router.put("/appearance")
async def update_appearance(payload: AppearanceUpdate, current_user: dict = Depends(get_current_user)):
    settings = persist_settings(current_user, {"appearance": {"theme": payload.theme}}, commit=False)
    await repository_service.commit_async()
    return {"message": "Updated", "theme": settings["appearance"]["theme"]}


@router.post("/change-password")
async def change_password(payload: PasswordChange, current_user: dict = Depends(get_current_user)):
    if not verify_password(payload.old_password, current_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    repository_service.update_user(
        current_user,
        {"hashed_password": hash_password(payload.new_password), "updatedAt": iso_now()},
        commit=False,
    )
    await repository_service.commit_async()
    return {"message": "Password changed"}


@router.get("/sessions")
async def sessions(current_user: dict = Depends(get_current_user)):
    return [
        {
            "id": session["id"],
            "device": "Browser",
            "location": "Unknown",
            "lastActive": session["created_at"],
            "expiresAt": session["expires_at"],
        }
        for session in store.sessions.values()
        if session["user_id"] == current_user["id"]
    ]


@router.delete("/sessions/all")
async def revoke_all_sessions(current_user: dict = Depends(get_current_user)):
    await asyncio.to_thread(repository_service.revoke_user_sessions, current_user["id"])
    return {"message": "All other sessions revoked"}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, current_user: dict = Depends(get_current_user)):
    for token, session in list(store.sessions.items()):
        if session["id"] == session_id and session["user_id"] == current_user["id"]:
            await asyncio.to_thread(repository_service.revoke_session_token, token)
            return {"message": "Session revoked"}
    raise HTTPException(status_code=404, detail="Session not found")
