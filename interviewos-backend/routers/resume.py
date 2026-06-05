from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from agents.resume_agent import analyze_resume_text_with_agent
from agents.tools.decision import execute_tool_decision, tool_decision
from auth.dependencies import get_current_user
from services.file_service import save_upload
from services.repository_service import repository_service
from services.security_gateway import security_gateway
from services.store import iso_now, new_id, store


router = APIRouter()


@router.post("/analyze")
async def analyze_resume(
    file: UploadFile = File(...),
    target_role: str | None = Form(None),
    job_description: str | None = Form(None),
    current_user: dict = Depends(get_current_user),
):
    saved = await save_upload(file)
    text = saved.get("text", "") or saved["content"].decode("utf-8", errors="ignore")
    resume_security = security_gateway.sanitize_text(text, source="resume.upload_text", limit=20000)
    text = resume_security.clean_text
    security_results = [resume_security]
    if job_description:
        jd_security = security_gateway.sanitize_text(job_description, source="resume.job_description", limit=8000)
        security_results.append(jd_security)
        text = f"{text}\n\nJob description:\n{jd_security.clean_text}"
    security_metadata = security_gateway.metadata_for(security_results, source="resume.analyze")
    try:
        analysis = await analyze_resume_text_with_agent(saved["file_name"], text, target_role)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Resume analysis failed: {type(exc).__name__}: {exc}. Please check the API key/network and try again.",
        ) from exc
    resume = {
        "id": new_id(),
        "userId": current_user["id"],
        "fileName": saved["file_name"],
        "filePath": saved["file_path"],
        "uploadedAt": iso_now(),
        **analysis,
    }
    repository_service.upsert_resume(resume, commit=False)
    memory_decision = tool_decision(
        "Resume Agent",
        "write_memory",
        "Persist resume memory through the shared tool registry.",
        {
            "user_id": current_user["id"],
            "memory_type": "resume",
            "source_id": resume["id"],
            "text": text,
            "metadata": {
                "type": "resume",
                "source_agent": "Resume Agent",
                "source_route": "/api/resume/analyze",
            "privacy_scope": "user",
            "importance": "high",
            "security": security_metadata,
        },
    },
        required=False,
    )
    await execute_tool_decision(memory_decision)
    await repository_service.commit_async()
    return resume


@router.get("/history")
async def resume_history(current_user: dict = Depends(get_current_user)):
    resumes = [resume for resume in store.resumes.values() if resume["userId"] == current_user["id"]]
    return sorted(resumes, key=lambda item: item["uploadedAt"], reverse=True)


@router.get("/{resume_id}")
async def get_resume(resume_id: str, current_user: dict = Depends(get_current_user)):
    resume = store.resumes.get(resume_id)
    if not resume or resume["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume
