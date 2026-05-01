from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.app.settings import get_settings
from src.learn.diary_memory import load_memory_context
from src.review.service import ReviewService
from src.runtime.halt_guard import resume_agent
from src.storage.db import session_scope
from src.storage.repositories import AccountHealthRepository, DecisionRepository, LearningRepository

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def create_review_app():
    app = FastAPI(title="PromptHunt Review Dashboard")
    reviews = ReviewService()

    @app.get("/", include_in_schema=False)
    def dashboard_root():
        return RedirectResponse(url="/reviews", status_code=307)

    @app.get("/reviews", response_class=HTMLResponse)
    def list_reviews(request: Request):
        with session_scope() as session:
            repo = DecisionRepository(session)
            items = repo.list_pending_reviews()
        return templates.TemplateResponse(
            request,
            "reviews.html",
            {"reviews": items, "title": "Pending Reviews"},
        )

    @app.get("/reviews/{review_id}", response_class=HTMLResponse)
    def review_detail(review_id: int, request: Request):
        with session_scope() as session:
            repo = DecisionRepository(session)
            review = repo.get_review(review_id)
            if review is None:
                raise HTTPException(status_code=404, detail="Review not found")
            draft = repo.get_draft(review.draft_id)
        return templates.TemplateResponse(
            request,
            "review_detail.html",
            {"review": review, "draft": draft, "title": f"Review {review_id}"},
        )

    @app.post("/reviews/{review_id}/approve")
    def approve_review(review_id: int, note: str = Form(default="")):
        reviews.approve(review_id, note=note or None)
        return RedirectResponse(url=f"/reviews/{review_id}", status_code=303)

    @app.post("/reviews/{review_id}/reject")
    def reject_review(review_id: int, note: str = Form(default="")):
        reviews.reject(review_id, note=note or None)
        return RedirectResponse(url=f"/reviews/{review_id}", status_code=303)

    @app.post("/reviews/{review_id}/edit-and-approve")
    def edit_and_approve(review_id: int, body: str = Form(...), note: str = Form(default="")):
        reviews.approve(review_id, note=note or None, edited_body=body)
        return RedirectResponse(url=f"/reviews/{review_id}", status_code=303)

    @app.get("/attempts", response_class=HTMLResponse)
    def list_attempts(request: Request):
        with session_scope() as session:
            repo = DecisionRepository(session)
            attempts = repo.get_attempts()
        return templates.TemplateResponse(
            request,
            "attempts.html",
            {"attempts": attempts, "title": "Post Attempts"},
        )

    @app.get("/threads/{reddit_thread_id}", response_class=HTMLResponse)
    def thread_detail(reddit_thread_id: str, request: Request):
        with session_scope() as session:
            repo = DecisionRepository(session)
            thread = repo.get_thread_details(reddit_thread_id)
            if thread is None:
                raise HTTPException(status_code=404, detail="Thread not found")
        return templates.TemplateResponse(
            request,
            "thread_detail.html",
            {"thread": thread, "title": f"Thread {reddit_thread_id}"},
        )

    @app.get("/learning", response_class=HTMLResponse)
    def learning_dashboard(request: Request):
        settings = get_settings()
        memory_error = None
        memory_context = None
        diary_path = Path(settings.memory_diary_path)
        try:
            memory_context = load_memory_context(diary_path, settings.memory_recent_days, settings.memory_monthly_recap_months)
        except Exception as exc:
            memory_error = f"{type(exc).__name__}: {exc}"
        with session_scope() as session:
            repo = LearningRepository(session)
            weights = repo.latest_strategy_weights()
            threshold_event = repo.latest_threshold_event()
        return templates.TemplateResponse(
            request,
            "learning.html",
            {
                "weights": weights,
                "threshold_event": threshold_event,
                "title": "Learning",
                "diary_path": diary_path,
                "memory_context": memory_context,
                "latest_daily_entry": memory_context.daily_entries[0] if memory_context and memory_context.daily_entries else None,
                "latest_monthly_recap": memory_context.monthly_recaps[0] if memory_context and memory_context.monthly_recaps else None,
                "memory_error": memory_error,
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_dashboard(request: Request):
        settings = get_settings()
        username = settings.reddit_username
        with session_scope() as session:
            account_health = AccountHealthRepository(session)
            latest_snapshot = account_health.latest_snapshot(username) if username else None
            active_halt = account_health.latest_active_halt()
            health_events = account_health.recent_health_events()
        thresholds = {
            "min_total_karma": settings.account_health_min_total_karma,
            "min_comment_karma": settings.account_health_min_comment_karma,
            "min_link_karma": settings.account_health_min_link_karma,
            "max_daily_total_karma_drop": settings.account_health_max_daily_total_karma_drop,
            "min_daily_tracked_score_delta": settings.account_health_min_daily_tracked_score_delta,
        }
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": settings.model_dump(),
                "title": "Settings",
                "latest_snapshot": latest_snapshot,
                "active_halt": active_halt,
                "health_events": health_events,
                "account_health_thresholds": thresholds,
            },
        )

    @app.post("/settings/agent-halt/resume")
    def resume_halted_agent(note: str = Form(default="")):
        resume_agent(resolved_by="dashboard", note=note or None)
        return RedirectResponse(url="/settings", status_code=303)

    return app
