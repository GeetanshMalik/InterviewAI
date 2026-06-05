import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agents.bot_agent import ai_memory_enabled_for_user, build_bot_prompt_context, build_bot_response_details
from agents.tools.autonomous import AutonomousToolExecution, execute_autonomous_tool_selection
from agents.tools.decision import tool_decision
from auth.dependencies import get_current_user
from models.bot import BotMessageRequest
from services.llm import llm_service
from services.repository_service import repository_service
from services.security_gateway import security_gateway
from services.store import iso_now, new_id, store


router = APIRouter()


def _process_step(label: str, detail: str | None = None) -> dict:
    return {"id": new_id(), "label": label, "detail": detail, "timestamp": iso_now()}


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _should_remember_bot_exchange(user_text: str, assistant_text: str) -> bool:
    text = f"{user_text} {assistant_text}".lower()
    durable_terms = {
        "weakness",
        "roadmap",
        "resume",
        "interview",
        "score",
        "practice",
        "goal",
        "plan",
        "mistake",
        "feedback",
        "dsa",
        "technical",
        "hr",
    }
    return len(user_text.strip()) >= 12 and bool(durable_terms & set(text.replace(",", " ").split()))


async def remember_bot_exchange(user: dict, user_text: str, assistant_text: str, message_id: str) -> AutonomousToolExecution:
    if not ai_memory_enabled_for_user(user):
        return AutonomousToolExecution(provider_metadata={"stopReason": "ai_memory_disabled"})

    user_id = user["id"]
    sanitized_user = security_gateway.sanitize_text(user_text, source="bot.memory.user_message", limit=3000)
    sanitized_assistant = security_gateway.sanitize_text(assistant_text, source="bot.memory.assistant_message", limit=3000)
    fallback_decisions = []
    if _should_remember_bot_exchange(sanitized_user.clean_text, sanitized_assistant.clean_text):
        fallback_decisions.append(
            tool_decision(
                "AI Consultant Bot Agent",
                "write_memory",
                "Policy fallback: persist bot exchange only when it contains durable interview context.",
                {
                    "user_id": user_id,
                    "memory_type": "bot",
                    "source_id": message_id,
                    "text": f"User asked: {sanitized_user.clean_text}\nAssistant answered: {sanitized_assistant.clean_text}",
                    "metadata": {
                        "type": "bot",
                        "message_id": message_id,
                        "privacy_scope": "user",
                        "importance": "medium",
                        "security": {
                            "user": sanitized_user.private_metadata(),
                            "assistant": sanitized_assistant.private_metadata(),
                        },
                    },
                },
                required=False,
            )
        )

    return await execute_autonomous_tool_selection(
        agent="bot",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Bot Memory Agent. Call write_memory only if this exchange contains "
                    "durable candidate goals, interview weaknesses, roadmap commitments, resume facts, or practice signals. "
                    "For greetings or generic chat, choose no tool."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User id: {user_id}\nSource id: {message_id}\n"
                    f"Required memory_type if writing: bot\n"
                    f"User message: {sanitized_user.clean_text}\nAssistant answer: {sanitized_assistant.clean_text[:1600]}"
                ),
            },
        ],
        available_tools=["write_memory"],
        fallback_decisions=fallback_decisions,
        provider_order=("groq", "gemini"),
    )


@router.get("/history")
async def history(current_user: dict = Depends(get_current_user)):
    return store.bot_messages.get(current_user["id"], [])[-50:]


@router.post("/message")
async def message(payload: BotMessageRequest, current_user: dict = Depends(get_current_user)):
    user_message = {
        "id": new_id(),
        "role": "user",
        "content": payload.message,
        "timestamp": iso_now(),
        "context": payload.context,
    }
    repository_service.add_bot_message(current_user["id"], user_message, commit=False)
    history = store.bot_messages.get(current_user["id"], [])[:-1]
    resumes = [resume for resume in store.resumes.values() if resume["userId"] == current_user["id"]]
    response = await build_bot_response_details(
        current_user,
        payload.message,
        store.user_reports(current_user["id"]),
        store.user_roadmaps(current_user["id"]),
        resumes,
        history,
    )
    response_text = response.content
    assistant_message = {
        "id": new_id(),
        "role": "assistant",
        "content": response_text,
        "timestamp": iso_now(),
        "context": payload.context,
    }
    repository_service.add_bot_message(current_user["id"], assistant_message, commit=False)
    memory_result = await remember_bot_exchange(current_user, payload.message, response_text, assistant_message["id"])
    await repository_service.commit_async()
    return {
        "response": response_text,
        "message_id": assistant_message["id"],
        "message": assistant_message,
        "process": [
            _process_step("Saved your message"),
            _process_step("Loaded reports, roadmaps, resumes, and recent chat memory"),
            _process_step("Generated the answer with the AI consultant"),
            _process_step(
                "Saved the assistant reply",
                "Bot memory written through autonomous tool selection."
                if any(record.get("ok") for record in memory_result.tool_results)
                else "Bot memory write skipped.",
            ),
        ],
        "tool_decisions": [*response.tool_decisions, *memory_result.tool_decisions],
        "tool_results": [*response.tool_results, *memory_result.tool_results],
    }


@router.post("/message/stream")
async def message_stream(payload: BotMessageRequest, current_user: dict = Depends(get_current_user)):
    async def event_stream():
        steps: list[dict] = []

        def remember(label: str, detail: str | None = None) -> dict:
            step = _process_step(label, detail)
            steps.append(step)
            return step

        try:
            user_message = {
                "id": new_id(),
                "role": "user",
                "content": payload.message,
                "timestamp": iso_now(),
                "context": payload.context,
            }
            repository_service.add_bot_message(current_user["id"], user_message, commit=False)
            yield _sse("step", remember("Saved your message"))

            history = store.bot_messages.get(current_user["id"], [])[:-1]
            reports = store.user_reports(current_user["id"])
            roadmaps = store.user_roadmaps(current_user["id"])
            resumes = [resume for resume in store.resumes.values() if resume["userId"] == current_user["id"]]
            yield _sse(
                "step",
                remember(
                    "Loaded your interview context",
                    f"{len(reports)} reports, {len(roadmaps)} roadmaps, {len(resumes)} resumes, {len(history[-12:])} memory items",
                ),
            )

            yield _sse("step", remember("Sending context to the AI consultant"))
            prompt = await build_bot_prompt_context(
                current_user,
                payload.message,
                reports,
                roadmaps,
                resumes,
                history,
            )
            chunks: list[str] = []
            provider = "unknown"
            model = "unknown"
            async for chunk in llm_service.stream_live(
                prompt.messages,
                agent="bot",
                provider_order=("groq", "gemini"),
            ):
                provider = chunk.provider
                model = chunk.model
                if chunk.event == "start":
                    yield _sse("step", remember("Streaming model response", f"{chunk.provider} / {chunk.model}"))
                elif chunk.event == "token":
                    chunks.append(chunk.content)
                    yield _sse("token", {"content": chunk.content, "provider": chunk.provider, "model": chunk.model})
            response_content = "".join(chunks)
            yield _sse("step", remember("Received model response", f"{provider} / {model}"))

            assistant_message = {
                "id": new_id(),
                "role": "assistant",
                "content": response_content,
                "timestamp": iso_now(),
                "context": payload.context,
            }
            repository_service.add_bot_message(current_user["id"], assistant_message, commit=False)
            memory_result = await remember_bot_exchange(
                current_user,
                payload.message,
                response_content,
                assistant_message["id"],
            )
            await repository_service.commit_async()
            yield _sse(
                "step",
                remember(
                    "Saved the assistant reply",
                    "Bot memory written through autonomous tool selection."
                    if any(record.get("ok") for record in memory_result.tool_results)
                    else "Bot memory write skipped.",
                ),
            )
            yield _sse(
                "message",
                {
                    "response": response_content,
                    "message_id": assistant_message["id"],
                    "message": assistant_message,
                    "process": steps,
                    "tool_decisions": [*prompt.tool_decisions, *memory_result.tool_decisions],
                    "tool_results": [*prompt.tool_results, *memory_result.tool_results],
                },
            )
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse(
                "error",
                {
                    "message": f"Something went wrong while generating the bot response. {exc} Please try again.",
                    "process": steps,
                },
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/history")
async def clear_history(current_user: dict = Depends(get_current_user)):
    repository_service.clear_bot_messages(current_user["id"], commit=False)
    await repository_service.commit_async()
    return {"message": "History cleared"}
