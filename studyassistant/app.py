"""HTTP API and the single-page web app, served from one lab PC.

Run with ``scripts/start.sh``
(or ``uvicorn studyassistant.app:create_app --factory --host 0.0.0.0``).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .assistant import GenerationFailed, StudyAssistant, UnitNotFound
from .config import ROOT, Settings, get_settings
from .db import Database
from .index import SearchIndex
from .llm import ModelUnavailable, OllamaModel
from .translate import Translator

STATIC_DIR = ROOT / "static"


class AskRequest(BaseModel):
    unit_id: str
    question: str = Field(min_length=2, max_length=500)
    language: str = "en"


class QuizRequest(BaseModel):
    unit_id: str
    language: str = "en"


class QuizSubmission(BaseModel):
    answers: list[int | None]


class VisibilityRequest(BaseModel):
    unit_id: str
    hidden: bool


def load_assistant(settings: Settings) -> StudyAssistant:
    """The assistant with the real local model, index and database."""
    if not SearchIndex.exists(settings.index_dir):
        raise SystemExit("No search index yet. Run: scripts/setup.sh (or python -m studyassistant.build)")
    return StudyAssistant(
        SearchIndex.load(settings.index_dir),
        OllamaModel(settings.ollama_url, settings.chat_model, settings.embed_model, num_gpu=settings.num_gpu),
        Database(settings.db_path),
        cache_dir=settings.data_dir / "summaries",
        top_k=settings.top_k,
        min_score=settings.min_score,
        translator=Translator(settings.translation_model_dir),
        translate_quizzes=settings.translate_quizzes,
        context_chars=settings.context_chars,
    )


def create_app(assistant: StudyAssistant | None = None, status=None) -> FastAPI:
    """Build the app. Tests pass a ready ``assistant`` with a fake model."""
    app = FastAPI(title="Offline AI Study Assistant", docs_url="/api/docs")
    settings = get_settings()
    teacher_pin = os.getenv("TEACHER_PIN", "")

    if assistant is None:
        assistant = load_assistant(settings)
        model = assistant.model
        status = status or model.status
        threading.Thread(target=model.warm_up, daemon=True).start()
    app.state.assistant = assistant

    def get_assistant() -> StudyAssistant:
        return app.state.assistant

    def require_teacher(x_teacher_pin: str = Header(default="")) -> None:
        if teacher_pin and x_teacher_pin != teacher_pin:
            raise HTTPException(status_code=401, detail="Teacher PIN required")

    # -------------------------------------------------------------- library

    @app.get("/api/health")
    def health(a: StudyAssistant = Depends(get_assistant)) -> dict:
        return {
            "units": len(a.index.units),
            "passages": len(a.index.chunks),
            "model": status() if status else None,
            "teacher_pin": bool(teacher_pin),
            "amharic_translation": a.translator is not None,
        }

    @app.get("/api/library")
    def library(include_hidden: bool = False, a: StudyAssistant = Depends(get_assistant)) -> dict:
        hidden = a.db.hidden_units()
        grades: dict[int, list[dict]] = {}
        for unit in sorted(a.index.units.values(), key=lambda u: (u.grade, u.book_id, u.number)):
            if unit.id in hidden and not include_hidden:
                continue
            grades.setdefault(unit.grade, []).append(
                {
                    "id": unit.id,
                    "number": unit.number,
                    "title": unit.title,
                    "book": unit.book_title,
                    "hidden": unit.id in hidden,
                    "sections": [
                        {"id": s.id, "number": s.number, "title": s.title, "pages": s.pages_label}
                        for s in unit.sections
                    ],
                }
            )
        return {"grades": [{"grade": g, "units": units} for g, units in sorted(grades.items())]}

    @app.get("/api/sections/{section_id}")
    def section(section_id: str, a: StudyAssistant = Depends(get_assistant)) -> dict:
        unit_id = section_id.rsplit(":s", 1)[0]
        try:
            unit = a.unit(unit_id)
        except UnitNotFound:
            raise HTTPException(404, "Unit not found") from None
        sec = next((s for s in unit.sections if s.id == section_id), None)
        if sec is None:
            raise HTTPException(404, "Section not found")
        return {
            "id": sec.id,
            "unit": f"Unit {unit.number}: {unit.title}",
            "number": sec.number,
            "title": sec.title,
            "pages": [{"page": p, "text": t} for p, t in sec.text_by_page],
        }

    # ------------------------------------------------------------ AI features

    @app.post("/api/ask")
    def ask(req: AskRequest, a: StudyAssistant = Depends(get_assistant)) -> StreamingResponse:
        try:
            a.unit(req.unit_id)
        except UnitNotFound:
            raise HTTPException(404, "Unit not found") from None

        def events() -> Iterator[bytes]:
            try:
                for event in a.ask(req.unit_id, req.question, req.language):
                    yield (json.dumps(event, ensure_ascii=False) + "\n").encode()
            except ModelUnavailable as exc:
                yield (json.dumps({"type": "error", "message": str(exc)}) + "\n").encode()

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/units/{unit_id}/summary")
    def summary(unit_id: str, language: str = "en", refresh: bool = False, a: StudyAssistant = Depends(get_assistant)) -> dict:
        return _call(lambda: a.summary(unit_id, language, refresh=refresh))

    @app.post("/api/quizzes")
    def new_quiz(req: QuizRequest, a: StudyAssistant = Depends(get_assistant)) -> dict:
        return _call(lambda: a.create_quiz(req.unit_id, req.language))

    @app.post("/api/quizzes/{quiz_id}/submit")
    def submit_quiz(quiz_id: str, req: QuizSubmission, a: StudyAssistant = Depends(get_assistant)) -> dict:
        return _call(lambda: a.submit_quiz(quiz_id, req.answers))

    # ---------------------------------------------------------------- teacher

    @app.get("/api/teacher/overview", dependencies=[Depends(require_teacher)])
    def teacher_overview(a: StudyAssistant = Depends(get_assistant)) -> dict:
        stats = a.db.unit_stats()
        hidden = a.db.hidden_units()
        units = []
        for unit in sorted(a.index.units.values(), key=lambda u: (u.grade, u.book_id, u.number)):
            s = stats.get(unit.id, {})
            units.append(
                {
                    "id": unit.id,
                    "grade": unit.grade,
                    "title": f"Unit {unit.number}: {unit.title}",
                    "hidden": unit.id in hidden,
                    "questions": s.get("questions", 0),
                    "unanswered": s.get("unanswered", 0),
                    "quiz_attempts": s.get("quiz_attempts", 0),
                    "quiz_average": s.get("quiz_average"),
                    "top_questions": a.db.top_questions(unit.id),
                }
            )
        return {"units": units}

    @app.post("/api/teacher/visibility", dependencies=[Depends(require_teacher)])
    def set_visibility(req: VisibilityRequest, a: StudyAssistant = Depends(get_assistant)) -> dict:
        if req.unit_id not in a.index.units:
            raise HTTPException(404, "Unit not found")
        a.db.set_unit_hidden(req.unit_id, req.hidden)
        return {"unit_id": req.unit_id, "hidden": req.hidden}

    # ----------------------------------------------------------------- static

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


def _call(fn):
    try:
        return fn()
    except UnitNotFound:
        raise HTTPException(404, "Not found") from None
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except GenerationFailed as exc:
        raise HTTPException(502, str(exc)) from None
