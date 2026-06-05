import asyncio

from fastapi import APIRouter, Depends, HTTPException

from agents.aptitude_agent import repair_saved_result
from agents.lifecycle_graph import run_interview_lifecycle
from auth.dependencies import get_current_user
from models.report import ReportGenerateRequest
from services.repository_service import repository_service
from services.store import iso_now, store


router = APIRouter()


@router.get("")
@router.get("/")
async def list_reports(current_user: dict = Depends(get_current_user)):
    return store.user_reports(current_user["id"])


@router.get("/{report_id}")
async def get_report(report_id: str, current_user: dict = Depends(get_current_user)):
    report = store.reports.get(report_id)
    if not report or report["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/generate")
async def generate_report(payload: ReportGenerateRequest, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(payload.interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")

    existing_report = next(
        (
            report
            for report in store.user_reports(current_user["id"])
            if report.get("interviewId") == payload.interview_id
        ),
        None,
    )
    existing_roadmap = (
        next(
            (
                roadmap
                for roadmap in store.user_roadmaps(current_user["id"])
                if roadmap.get("sourceReportId") == existing_report.get("id")
            ),
            None,
        )
        if existing_report
        else None
    )
    if existing_report and existing_roadmap:
        return {"report": existing_report, "roadmap": existing_roadmap}

    aptitude_result = repair_saved_result(
        store.aptitude_questions.get(payload.interview_id, []),
        store.aptitude_results.get(payload.interview_id),
    )
    if aptitude_result and aptitude_result != store.aptitude_results.get(payload.interview_id):
        repository_service.set_aptitude_result(payload.interview_id, aptitude_result, commit=False)

    lifecycle = await run_interview_lifecycle(
        current_user["id"],
        interview,
        store.dsa_submissions.get(payload.interview_id, []),
        aptitude_result,
        store.technical_answers.get(payload.interview_id, []),
        store.hr_answers.get(payload.interview_id, []),
    )
    report = lifecycle["report"]
    roadmap = lifecycle["roadmap"]
    interview["currentStep"] = "completed"
    interview["status"] = "completed"
    interview["completedAt"] = interview.get("completedAt") or iso_now()
    repository_service.upsert_interview(interview, commit=False)
    repository_service.upsert_report(report, commit=False)
    repository_service.create_log(
        payload.interview_id,
        "success",
        "Report Agent",
        "Interview report generated.",
        "completed",
        commit=False,
    )

    repository_service.deactivate_user_roadmaps(current_user["id"], commit=False)
    repository_service.upsert_roadmap(roadmap, commit=False)
    repository_service.create_log(
        payload.interview_id,
        "success",
        "Roadmap Agent",
        "Personalized roadmap generated.",
        "completed",
        commit=False,
    )
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()

    return {"report": report, "roadmap": roadmap}


@router.delete("/{report_id}")
async def delete_report(report_id: str, current_user: dict = Depends(get_current_user)):
    report = store.reports.get(report_id)
    if not report or report["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Report not found")
    await asyncio.to_thread(repository_service.delete_report, report_id)
    return {"message": "Report deleted"}
