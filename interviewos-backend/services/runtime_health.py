from __future__ import annotations

import platform
import sys
from typing import Any

from config import settings


MIN_SUPPORTED_PYTHON = (3, 10)


def runtime_health_snapshot() -> dict[str, Any]:
    version = sys.version_info
    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "minimumSupported": ".".join(str(part) for part in MIN_SUPPORTED_PYTHON),
            "supported": version[:2] >= MIN_SUPPORTED_PYTHON,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
        },
    }


def provider_health_snapshot() -> dict[str, Any]:
    return {
        "llm": {
            "providerOrder": settings.llm_provider_order,
            "geminiConfigured": bool(settings.gemini_api_key),
            "groqConfigured": bool(settings.groq_api_key),
            "agentKeysConfigured": {
                "dsa": bool(settings.dsa_gemini_api_key or settings.dsa_groq_api_key),
                "aptitude": bool(settings.aptitude_gemini_api_key or settings.aptitude_groq_api_key),
                "technical": bool(settings.technical_gemini_api_key or settings.technical_groq_api_key),
                "hr": bool(settings.hr_gemini_api_key or settings.hr_groq_api_key),
                "bot": bool(settings.bot_gemini_api_key or settings.bot_groq_api_key),
                "planning": bool(settings.planning_gemini_api_key or settings.planning_groq_api_key),
                "evaluation": bool(settings.evaluation_gemini_api_key or settings.evaluation_groq_api_key),
            },
        },
        "voice": {
            "livekitConfigured": bool(settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret),
            "deepgramConfigured": bool(settings.deepgram_api_key),
            "deepgramModel": settings.deepgram_model,
        },
        "semanticMemory": {
            "backend": settings.semantic_memory_backend,
            "embeddingProvider": settings.semantic_embedding_provider,
        },
    }
