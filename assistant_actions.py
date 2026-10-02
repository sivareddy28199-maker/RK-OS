"""Strict assistant action tool layer for RK OS.

This module turns the assistant into a controlled orchestration layer over the
existing RK OS business logic. It never accepts a function name, SQL statement,
shell command, filesystem path, or URL from the caller. Callers submit an action
envelope whose ``action`` must be one of a fixed allow-list, and whose ``args``
are validated against the per-action JSON Schema in
``schemas/assistant-actions.schema.json``.

Flow::

    action envelope -> schema validation -> permission lookup -> confirmation
    check -> allow-listed handler -> existing RK OS logic -> result envelope
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

import main

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "assistant-actions.schema.json"

# Permission levels, ordered from least to most powerful.
READ = "read"
SAFE_WRITE = "safe_write"
WRITE = "write"
DESTRUCTIVE = "destructive"

_PERMISSION_ORDER = [READ, SAFE_WRITE, WRITE, DESTRUCTIVE]


# =============================================================================
# PERMISSION MODEL
# =============================================================================

READ_ACTIONS = {
    "routines.summary", "routines.list", "routines.get", "routines.history",
    "study.overview", "study.subjects", "study.topics", "study.topic",
    "study.sessions", "study.today", "study.weak_areas", "study.recent_topics",
    "study.revision_queue",
    "timer.status",
    "progress.overview", "progress.today", "progress.week", "progress.month",
    "progress.subject", "progress.topic", "progress.streak", "progress.study_time",
    "progress.accuracy", "progress.practice", "progress.quiz", "progress.weak_areas",
    "practice.result", "practice.history", "practice.weak_topics",
    "quiz.result", "quiz.history", "quiz.performance",
    "assistant.get_context", "assistant.daily_plan", "assistant.recommend_next",
    "assistant.explain_progress",
}

SAFE_WRITE_ACTIONS = {
    "timer.start", "timer.pause", "timer.resume", "timer.reset",
    "study.start_session", "study.mark_topic_studied", "study.mark_reviewed",
    "routines.habit.complete", "routines.habit.uncomplete",
    "routines.task.complete", "routines.task.uncomplete",
    "routines.goal.progress",
    "practice.start", "practice.next", "practice.submit",
    "quiz.start", "quiz.next", "quiz.submit", "quiz.finish",
    "assistant.start_focus", "assistant.start_practice", "assistant.start_quiz",
}

WRITE_ACTIONS = {
    "routines.habit.create", "routines.habit.update",
    "routines.task.create", "routines.task.update",
    "routines.goal.create", "routines.goal.update",
    "study.end_session", "timer.set_duration",
}

DESTRUCTIVE_ACTIONS = {
    "routines.habit.delete", "routines.task.delete", "routines.goal.delete",
}

PERMISSIONS: dict[str, str] = {}
for _name in READ_ACTIONS:
    PERMISSIONS[_name] = READ
for _name in SAFE_WRITE_ACTIONS:
    PERMISSIONS[_name] = SAFE_WRITE
for _name in WRITE_ACTIONS:
    PERMISSIONS[_name] = WRITE
for _name in DESTRUCTIVE_ACTIONS:
    PERMISSIONS[_name] = DESTRUCTIVE


# =============================================================================
# SCHEMA + MINIMAL DRAFT 2020-12 VALIDATOR
# =============================================================================

class ActionSchemaError(Exception):
    """Raised when the bundled action schema cannot be loaded."""


def _load_schema() -> dict:
    try:
        with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:  # pragma: no cover - packaging guard
        raise ActionSchemaError(f"Unable to load assistant action schema: {exc}") from exc


_SCHEMA = _load_schema()
ALLOWED_ACTIONS: tuple[str, ...] = tuple(_SCHEMA["properties"]["action"]["enum"])
ALLOWED_ACTION_SET = set(ALLOWED_ACTIONS)


def _resolve_ref(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ActionSchemaError(f"Unsupported $ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate(instance: Any, schema: dict, root: dict, path: str) -> list[str]:
    """Validate ``instance`` against a subset of JSON Schema Draft 2020-12.

    Supports the keywords used by the bundled schema: $ref, type, enum, const,
    required, properties, additionalProperties, minimum, maximum, minLength,
    maxLength, pattern, allOf, anyOf, if/then/else.
    """
    errors: list[str] = []

    if "$ref" in schema:
        return _validate(instance, _resolve_ref(schema["$ref"], root), root, path)

    if "allOf" in schema:
        for subschema in schema["allOf"]:
            errors.extend(_validate(instance, subschema, root, path))

    if "anyOf" in schema:
        if not any(not _validate(instance, subschema, root, path) for subschema in schema["anyOf"]):
            errors.append(f"{path}: does not match any allowed variant")

    if "if" in schema:
        if not _validate(instance, schema["if"], root, path):
            if "then" in schema:
                errors.extend(_validate(instance, schema["then"], root, path))
        elif "else" in schema:
            errors.extend(_validate(instance, schema["else"], root, path))

    if "type" in schema:
        expected = schema["type"]
        if isinstance(expected, list):
            if not any(_type_matches(instance, item) for item in expected):
                errors.append(f"{path}: expected one of {expected}")
        elif not _type_matches(instance, expected):
            errors.append(f"{path}: expected {expected}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value is not one of the allowed options")

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: value must be {schema['const']!r}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property '{key}'")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(_validate(value, properties[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{key}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(_validate(value, schema["additionalProperties"], root, f"{path}.{key}"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: must be at least {schema['minLength']} characters")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: must be at most {schema['maxLength']} characters")

    return errors


def validate_envelope(envelope: Any) -> list[str]:
    """Return a list of human-readable validation errors (empty if valid)."""
    return _validate(envelope, _SCHEMA, _SCHEMA, "$")


# =============================================================================
# RESULT FORMAT
# =============================================================================

def ok(action: str, data: Any, message: str, permission: str, request_id: str | None = None) -> dict:
    result = {
        "success": True,
        "action": action,
        "permission": permission,
        "data": data,
        "message": message,
    }
    if request_id:
        result["request_id"] = request_id
    return result


def fail(action: str | None, code: str, message: str, request_id: str | None = None,
         confirmation_required: bool = False) -> dict:
    result = {
        "success": False,
        "action": action,
        "error": {"code": code, "message": message},
    }
    if confirmation_required:
        result["confirmation_required"] = True
    if request_id:
        result["request_id"] = request_id
    return result


_HTTP_ERROR_CODES = {
    400: "bad_request",
    404: "not_found",
    409: "conflict",
    422: "invalid_args",
}


# =============================================================================
# DISPATCHER
# =============================================================================

class ActionDispatcher:
    """Validates and executes allow-listed assistant actions."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict, dict], tuple[Any, str]]] = {}
        self._register_handlers()
        self._active_practice: dict | None = None

    # -- registration -------------------------------------------------------

    def _register_handlers(self) -> None:
        handlers = {
            "routines.summary": self._routines_summary,
            "routines.list": self._routines_list,
            "routines.get": self._routines_get,
            "routines.history": self._routines_history,
            "routines.habit.create": self._habit_create,
            "routines.habit.update": self._habit_update,
            "routines.habit.complete": self._habit_complete,
            "routines.habit.uncomplete": self._habit_uncomplete,
            "routines.habit.delete": self._habit_delete,
            "routines.task.create": self._task_create,
            "routines.task.update": self._task_update,
            "routines.task.complete": self._task_complete,
            "routines.task.uncomplete": self._task_uncomplete,
            "routines.task.delete": self._task_delete,
            "routines.goal.create": self._goal_create,
            "routines.goal.update": self._goal_update,
            "routines.goal.progress": self._goal_progress,
            "routines.goal.delete": self._goal_delete,
            "study.overview": self._study_overview,
            "study.subjects": self._study_subjects,
            "study.topics": self._study_topics,
            "study.topic": self._study_topic,
            "study.sessions": self._study_sessions,
            "study.today": self._study_today,
            "study.weak_areas": self._study_weak_areas,
            "study.recent_topics": self._study_recent_topics,
            "study.revision_queue": self._study_revision_queue,
            "study.start_session": self._study_start_session,
            "study.end_session": self._study_end_session,
            "study.mark_topic_studied": self._study_mark_topic_studied,
            "study.mark_reviewed": self._study_mark_reviewed,
            "timer.start": self._timer_start,
            "timer.pause": self._timer_pause,
            "timer.resume": self._timer_resume,
            "timer.reset": self._timer_reset,
            "timer.status": self._timer_status,
            "timer.set_duration": self._timer_set_duration,
            "progress.overview": self._progress_overview,
            "progress.today": self._progress_today,
            "progress.week": self._progress_week,
            "progress.month": self._progress_month,
            "progress.subject": self._progress_subject,
            "progress.topic": self._progress_topic,
            "progress.streak": self._progress_streak,
            "progress.study_time": self._progress_study_time,
            "progress.accuracy": self._progress_accuracy,
            "progress.practice": self._progress_practice,
            "progress.quiz": self._progress_quiz,
            "progress.weak_areas": self._progress_weak_areas,
            "practice.start": self._practice_start,
            "practice.next": self._practice_next,
            "practice.submit": self._practice_submit,
            "practice.result": self._practice_result,
            "practice.history": self._practice_history,
            "practice.weak_topics": self._practice_weak_topics,
            "quiz.start": self._quiz_start,
            "quiz.next": self._quiz_next,
            "quiz.submit": self._quiz_submit,
            "quiz.finish": self._quiz_finish,
            "quiz.result": self._quiz_result,
            "quiz.history": self._quiz_history,
            "quiz.performance": self._quiz_performance,
            "assistant.get_context": self._assistant_get_context,
            "assistant.daily_plan": self._assistant_daily_plan,
            "assistant.recommend_next": self._assistant_recommend_next,
            "assistant.explain_progress": self._assistant_explain_progress,
            "assistant.start_focus": self._assistant_start_focus,
            "assistant.start_practice": self._assistant_start_practice,
            "assistant.start_quiz": self._assistant_start_quiz,
        }
        # Only allow-listed actions may ever be registered.
        self._handlers = {name: handler for name, handler in handlers.items()
                          if name in ALLOWED_ACTION_SET}
        missing = ALLOWED_ACTION_SET - set(self._handlers)
        if missing:  # pragma: no cover - guards against drift
            raise ActionSchemaError(f"Actions without a handler: {sorted(missing)}")

    # -- public entry point -------------------------------------------------

    def dispatch(self, envelope: Any) -> dict:
        if not isinstance(envelope, dict):
            return fail(None, "invalid_envelope", "Action payload must be a JSON object.")

        action = envelope.get("action")
        request_id = envelope.get("request_id") if isinstance(envelope.get("request_id"), str) else None

        if not isinstance(action, str) or action not in ALLOWED_ACTION_SET:
            return fail(action if isinstance(action, str) else None, "unknown_action",
                        "That action is not in the allow-list and cannot be executed.",
                        request_id)

        errors = validate_envelope(envelope)
        if errors:
            return fail(action, "invalid_args", "Action arguments failed validation.",
                        request_id)

        permission = PERMISSIONS[action]

        if permission == DESTRUCTIVE and envelope.get("confirmation_required") is not True:
            return fail(action, "confirmation_required",
                        f"{action} is a destructive action and requires explicit confirmation.",
                        request_id, confirmation_required=True)

        handler = self._handlers[action]
        args = envelope.get("args") or {}

        try:
            data, message = handler(args, envelope)
        except HTTPException as exc:
            code = _HTTP_ERROR_CODES.get(exc.status_code, "action_failed")
            return fail(action, code, str(exc.detail), request_id)
        except sqlite3.Error:
            return fail(action, "storage_error",
                        "The action could not be completed because of a storage error.", request_id)
        except (TypeError, ValueError, KeyError):
            return fail(action, "invalid_args",
                        "The action arguments could not be processed.", request_id)
        except Exception:  # noqa: BLE001 - never leak internal errors to callers
            return fail(action, "internal_error",
                        "The action failed unexpectedly.", request_id)

        return ok(action, data, message, permission, request_id)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _active_quiz_session_id() -> int | None:
        conn = main.get_db()
        row = conn.execute(
            "SELECT id FROM quiz_sessions WHERE completed_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else None

    def _timer_context(self) -> dict:
        return {"status": "idle", "active": False, "minutes": 25}

    # -- ROUTINES -----------------------------------------------------------

    def _routines_summary(self, args: dict, envelope: dict):
        summary = main.rk_get_routines_summary()
        message = (
            f"{summary['habits']['completed_today']}/{summary['habits']['total']} habits, "
            f"{summary['tasks']['completed']}/{summary['tasks']['total']} tasks, "
            f"{summary['goals']['total']} goals."
        )
        return summary, message

    def _routines_list(self, args: dict, envelope: dict):
        kind = args.get("type")
        data: dict[str, Any] = {}
        if kind in (None, "tasks"):
            data["tasks"] = main.get_tasks()
        if kind in (None, "habits"):
            data["habits"] = main.rk_get_habits()
        if kind in (None, "goals"):
            data["goals"] = main.rk_get_goals()
        return data, f"Listed {kind or 'all routine items'}."

    def _routines_get(self, args: dict, envelope: dict):
        kind, item_id = args["type"], args["id"]
        source = {"tasks": main.get_tasks, "habits": main.rk_get_habits, "goals": main.rk_get_goals}[kind]
        item = next((entry for entry in source() if entry["id"] == item_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail=f"{kind[:-1].capitalize()} not found")
        return item, f"Found {kind[:-1]} #{item_id}."

    def _routines_history(self, args: dict, envelope: dict):
        limit = args.get("limit", 30)
        return main.rk_get_activity_history(limit=limit), "Loaded routine history."

    def _habit_create(self, args: dict, envelope: dict):
        created = main.rk_create_habit({"name": args["name"]})
        return created, f"Created habit: {created['name']}."

    def _habit_update(self, args: dict, envelope: dict):
        payload = {key: args[key] for key in ("name",) if key in args}
        if not payload:
            raise HTTPException(status_code=422, detail="Provide a name to update")
        updated = main.rk_update_habit(args["id"], payload)
        return updated, f"Updated habit #{args['id']}."

    def _habit_complete(self, args: dict, envelope: dict):
        updated = main.rk_update_habit(args["id"], {"completed": True})
        return updated, f"Marked habit #{args['id']} complete."

    def _habit_uncomplete(self, args: dict, envelope: dict):
        updated = main.rk_update_habit(args["id"], {"completed": False})
        return updated, f"Marked habit #{args['id']} not complete."

    def _habit_delete(self, args: dict, envelope: dict):
        deleted = main.rk_delete_habit(args["id"])
        return deleted, f"Deleted habit #{args['id']}."

    def _task_create(self, args: dict, envelope: dict):
        created = main.create_task({"title": args["title"]})
        return created, f"Added task: {created['title']}."

    def _task_update(self, args: dict, envelope: dict):
        payload = {key: args[key] for key in ("title", "completed") if key in args}
        if not payload:
            raise HTTPException(status_code=422, detail="Provide a title or completed value to update")
        updated = main.update_task(args["id"], payload)
        return updated, f"Updated task #{args['id']}."

    def _task_complete(self, args: dict, envelope: dict):
        updated = main.update_task(args["id"], {"completed": True})
        return updated, f"Completed task #{args['id']}."

    def _task_uncomplete(self, args: dict, envelope: dict):
        updated = main.update_task(args["id"], {"completed": False})
        return updated, f"Marked task #{args['id']} not complete."

    def _task_delete(self, args: dict, envelope: dict):
        deleted = main.delete_task(args["id"])
        return deleted, f"Deleted task #{args['id']}."

    def _goal_create(self, args: dict, envelope: dict):
        created = main.rk_create_goal({key: args[key] for key in ("title", "target_date", "progress") if key in args})
        return created, f"Created goal: {created['title']}."

    def _goal_update(self, args: dict, envelope: dict):
        payload = {key: args[key] for key in ("title", "target_date", "progress") if key in args}
        if not payload:
            raise HTTPException(status_code=422, detail="Provide a field to update")
        updated = main.rk_update_goal(args["id"], payload)
        return updated, f"Updated goal #{args['id']}."

    def _goal_progress(self, args: dict, envelope: dict):
        updated = main.rk_update_goal(args["id"], {"progress": args["progress"]})
        return updated, f"Updated goal #{args['id']} to {updated['progress']}%."

    def _goal_delete(self, args: dict, envelope: dict):
        deleted = main.rk_delete_goal(args["id"])
        return deleted, f"Deleted goal #{args['id']}."

    # -- STUDY --------------------------------------------------------------

    def _study_overview(self, args: dict, envelope: dict):
        return main.rk_get_study_overview(), "Loaded study overview."

    def _study_subjects(self, args: dict, envelope: dict):
        return main.rk_get_study_subjects(), "Loaded study subjects."

    def _study_topics(self, args: dict, envelope: dict):
        return main.rk_get_study_topics(subject_id=args.get("subject_id")), "Loaded study topics."

    def _study_topic(self, args: dict, envelope: dict):
        return main.rk_get_study_topic(args["topic_id"]), f"Loaded study topic #{args['topic_id']}."

    def _study_sessions(self, args: dict, envelope: dict):
        return main.rk_get_study_sessions(limit=args.get("limit", 30)), "Loaded study sessions."

    def _study_today(self, args: dict, envelope: dict):
        overview = main.rk_get_study_overview()
        data = {
            "today_sessions": overview["today_sessions"],
            "today_study_minutes": overview["today_study_minutes"],
            "topics_studied_today": overview["topics_studied_today"],
            "current_streak": overview["current_streak"],
        }
        return data, (f"Today: {data['today_sessions']} sessions, "
                      f"{data['today_study_minutes']} minutes studied.")

    def _study_weak_areas(self, args: dict, envelope: dict):
        data = main.rk_get_practice_weak_topics(subject_id=args.get("subject_id"))
        return data, f"Found {len(data)} weak areas."

    def _study_recent_topics(self, args: dict, envelope: dict):
        data = main.rk_get_revision_topics().get("recently_studied", [])
        return data, f"Found {len(data)} recently studied topics."

    def _study_revision_queue(self, args: dict, envelope: dict):
        return main.rk_get_revision_topics(), "Loaded the revision queue."

    def _study_start_session(self, args: dict, envelope: dict):
        payload = {key: args[key] for key in ("subject_id", "topic_id", "duration_minutes", "session_type") if key in args}
        created = main.rk_create_study_session(payload)
        return created, f"Started a study session for subject #{created['subject_id']}."

    def _study_end_session(self, args: dict, envelope: dict):
        existing = main.rk_get_study_session(args["session_id"])
        payload = {"subject_id": existing["subject_id"]}
        if existing.get("topic_id") is not None:
            payload["topic_id"] = existing["topic_id"]
        if existing.get("session_type"):
            payload["session_type"] = existing["session_type"]
        if existing.get("started_at"):
            payload["started_at"] = existing["started_at"]
        if args.get("duration_minutes") is not None:
            payload["duration_minutes"] = args["duration_minutes"]
        created = main.rk_create_study_session(payload)
        return created, f"Recorded a completed study session of {created['duration_minutes']} minutes."

    def _study_mark_topic_studied(self, args: dict, envelope: dict):
        topic = main.rk_get_study_topic(args["topic_id"])
        payload = {"subject_id": topic["subject_id"], "topic_id": topic["id"]}
        if args.get("duration_minutes") is not None:
            payload["duration_minutes"] = args["duration_minutes"]
        created = main.rk_create_study_session(payload)
        return created, f"Marked {topic['name']} as studied."

    def _study_mark_reviewed(self, args: dict, envelope: dict):
        created = main.rk_mark_revision_reviewed({"topic_id": args["topic_id"]})
        return created, f"Marked topic #{args['topic_id']} as reviewed."

    # -- TIMER --------------------------------------------------------------

    def _timer_start(self, args: dict, envelope: dict):
        minutes = args.get("duration_minutes", 25)
        data = {"status": "running", "minutes": minutes,
                "subject_id": args.get("subject_id"), "topic_id": args.get("topic_id")}
        return data, f"Starting a {minutes}-minute focus session."

    def _timer_pause(self, args: dict, envelope: dict):
        return {"status": "paused"}, "Paused the focus timer."

    def _timer_resume(self, args: dict, envelope: dict):
        return {"status": "running"}, "Resumed the focus timer."

    def _timer_reset(self, args: dict, envelope: dict):
        return {"status": "idle"}, "Reset the focus timer."

    def _timer_status(self, args: dict, envelope: dict):
        data = self._timer_context()
        return data, f"Timer is {data['status']} at {data['minutes']} minutes."

    def _timer_set_duration(self, args: dict, envelope: dict):
        minutes = args["duration_minutes"]
        return {"minutes": minutes}, f"Focus duration set to {minutes} minutes."

    # -- PROGRESS -----------------------------------------------------------

    @staticmethod
    def _aggregate_history(days: int) -> dict:
        rows = main.rk_get_activity_history(limit=days)
        scores = [int(row.get("overall_score") or 0) for row in rows]
        return {
            "days": len(rows),
            "tasks_completed": sum(int(row.get("tasks_completed") or 0) for row in rows),
            "habits_completed": sum(int(row.get("habits_completed") or 0) for row in rows),
            "days_active": sum(1 for score in scores if score > 0),
            "average_score": round(sum(scores) / len(scores)) if scores else 0,
        }

    def _progress_overview(self, args: dict, envelope: dict):
        return main.rk_get_progress(), "Loaded the progress overview."

    def _progress_today(self, args: dict, envelope: dict):
        data = main.rk_get_today_activity()
        return data, f"Today's score is {data['overall_score']}%."

    def _progress_week(self, args: dict, envelope: dict):
        data = {"period": "week", "history": self._aggregate_history(7), "overall": main.rk_get_progress()}
        return data, "Loaded this week's progress."

    def _progress_month(self, args: dict, envelope: dict):
        data = {"period": "month", "history": self._aggregate_history(30), "overall": main.rk_get_progress()}
        return data, "Loaded this month's progress."

    def _progress_subject(self, args: dict, envelope: dict):
        subject_id = args["subject_id"]
        practice = main.rk_get_practice_statistics(subject_id=subject_id)
        weak = main.rk_get_practice_weak_topics(subject_id=subject_id)
        data = {"subject_id": subject_id, "practice": practice, "weak_topics": weak}
        return data, f"Loaded progress for subject #{subject_id}."

    def _progress_topic(self, args: dict, envelope: dict):
        topic = main.rk_get_study_topic(args["topic_id"])
        return topic, f"Loaded progress for {topic['name']}."

    def _progress_streak(self, args: dict, envelope: dict):
        overview = main.rk_get_study_overview()
        routines = main.rk_get_routines_summary()
        data = {"study_streak": overview["current_streak"], "routine_streak": routines["current_streak"]}
        return data, f"Current study streak is {data['study_streak']} day(s)."

    def _progress_study_time(self, args: dict, envelope: dict):
        progress = main.rk_get_progress()["study"]
        overview = main.rk_get_study_overview()
        data = {
            "period": args.get("period", "all"),
            "today_minutes": overview["today_study_minutes"],
            "total_minutes": progress["study_minutes"],
            "total_sessions": progress["sessions"],
        }
        return data, f"{data['today_minutes']} minutes studied today; {data['total_minutes']} minutes total."

    def _progress_accuracy(self, args: dict, envelope: dict):
        progress = main.rk_get_progress()
        data = {"period": args.get("period", "all"),
                "practice_accuracy": progress["practice"]["accuracy"],
                "quiz_accuracy": progress["quiz"]["accuracy"]}
        return data, f"Practice accuracy {data['practice_accuracy']}%, quiz accuracy {data['quiz_accuracy']}%."

    def _progress_practice(self, args: dict, envelope: dict):
        return main.rk_get_practice_statistics(), "Loaded practice progress."

    def _progress_quiz(self, args: dict, envelope: dict):
        return main.rk_get_quiz_statistics(), "Loaded quiz progress."

    def _progress_weak_areas(self, args: dict, envelope: dict):
        data = main.rk_get_practice_weak_topics(subject_id=args.get("subject_id"))
        return data, f"Found {len(data)} weak areas."

    # -- PRACTICE -----------------------------------------------------------

    def _practice_start(self, args: dict, envelope: dict):
        query = {key: args[key] for key in ("subject_id", "topic_id", "difficulty") if key in args}
        query.setdefault("difficulty", "Mixed")
        limit = args.get("limit", 20)
        questions = main.rk_get_practice_questions(limit=limit, **query)
        self._active_practice = {"filters": query, "limit": limit, "question_ids": [q["id"] for q in questions]}
        data = {"session": self._active_practice["question_ids"], "questions": questions}
        return data, f"Started practice with {len(questions)} question(s)."

    def _practice_next(self, args: dict, envelope: dict):
        if self._active_practice is None:
            raise HTTPException(status_code=409, detail="No active practice session. Start one first.")
        conn = main.get_db()
        answered = {row[0] for row in conn.execute("SELECT DISTINCT question_id FROM practice_attempts").fetchall()}
        conn.close()
        remaining = [qid for qid in self._active_practice["question_ids"] if qid not in answered]
        if not remaining:
            raise HTTPException(status_code=409, detail="No more practice questions in this session")
        question_id = remaining[0]
        questions = main.rk_get_practice_questions(limit=100, **self._active_practice["filters"])
        question = next((q for q in questions if q["id"] == question_id), None)
        if question is None:
            raise HTTPException(status_code=404, detail="Practice question not found")
        return question, "Here is your next practice question."

    def _practice_submit(self, args: dict, envelope: dict):
        created = main.rk_create_practice_attempt(
            {"question_id": args["question_id"], "selected_option": args["selected_option"]}
        )
        return created, ("Correct!" if created["is_correct"] else "Not quite — review the explanation.")

    def _practice_result(self, args: dict, envelope: dict):
        data = main.rk_get_practice_statistics()
        if self._active_practice is not None:
            data["active_session"] = self._active_practice["question_ids"]
        return data, f"Practice accuracy is {data['accuracy']}%."

    def _practice_history(self, args: dict, envelope: dict):
        limit = args.get("limit", 20)
        conn = main.get_db()
        rows = conn.execute(
            """
            SELECT pa.id, pa.question_id, pa.selected_option, pa.is_correct, pa.answered_at,
                q.question_text
            FROM practice_attempts AS pa
            JOIN questions AS q ON q.id = pa.question_id
            ORDER BY pa.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        data = [
            {"id": row[0], "question_id": row[1], "selected_option": row[2],
             "is_correct": bool(row[3]), "answered_at": row[4], "question_text": row[5]}
            for row in rows
        ]
        return data, f"Loaded {len(data)} practice attempts."

    def _practice_weak_topics(self, args: dict, envelope: dict):
        data = main.rk_get_practice_weak_topics(subject_id=args.get("subject_id"))
        return data, f"Found {len(data)} weak topics."

    # -- QUIZ ---------------------------------------------------------------

    def _quiz_start(self, args: dict, envelope: dict):
        payload = {key: args[key] for key in ("subject_id", "topic_id", "difficulty", "total_questions") if key in args}
        session = main.rk_start_quiz_session(payload)
        return session, f"Started a quiz with {session['total_questions']} question(s)."

    def _quiz_session_for(self, args: dict) -> int:
        session_id = args.get("session_id") or self._active_quiz_session_id()
        if session_id is None:
            raise HTTPException(status_code=409, detail="No active quiz session. Start one first.")
        return int(session_id)

    def _quiz_next(self, args: dict, envelope: dict):
        session_id = self._quiz_session_for(args)
        conn = main.get_db()
        session = conn.execute(
            "SELECT question_ids FROM quiz_sessions WHERE id = ? AND completed_at IS NULL",
            (session_id,),
        ).fetchone()
        if session is None:
            conn.close()
            raise HTTPException(status_code=404, detail="Quiz session not found")
        answered = {row[0] for row in conn.execute(
            "SELECT question_id FROM quiz_answers WHERE session_id = ?", (session_id,)
        ).fetchall()}
        question_ids = json.loads(session[0] or "[]")
        remaining = [qid for qid in question_ids if qid not in answered]
        if not remaining:
            conn.close()
            raise HTTPException(status_code=409, detail="All quiz questions have been answered")
        question_id = remaining[0]
        row = conn.execute(
            "SELECT id, subject_id, topic_id, question_text, option_a, option_b, option_c, option_d, difficulty, source "
            "FROM questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        conn.close()
        data = {"session_id": session_id, "question": {
            "id": row[0], "subject_id": row[1], "topic_id": row[2], "question_text": row[3],
            "option_a": row[4], "option_b": row[5], "option_c": row[6], "option_d": row[7],
            "difficulty": row[8], "source": row[9],
        }}
        return data, "Here is your next quiz question."

    def _quiz_submit(self, args: dict, envelope: dict):
        created = main.rk_submit_quiz_answer(
            args["session_id"],
            {"question_id": args["question_id"], "selected_option": args["selected_option"]},
        )
        return created, ("Correct!" if created["is_correct"] else "Not quite — review the explanation.")

    def _quiz_finish(self, args: dict, envelope: dict):
        result = main.rk_complete_quiz_session(args["session_id"])
        return result, f"Quiz finished with {result['correct_answers']}/{result['total_questions']} correct."

    def _quiz_result(self, args: dict, envelope: dict):
        session_id = self._quiz_session_for(args)
        conn = main.get_db()
        row = conn.execute(
            "SELECT total_questions, correct_answers, started_at, completed_at FROM quiz_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail="Quiz session not found")
        if row[3] is None:
            answered = main.rk_get_quiz_statistics()["today"]["questions"]
            data = {"session_id": session_id, "completed": False,
                    "total_questions": int(row[0] or 0), "correct_answers": int(row[1] or 0),
                    "answered_today": answered}
            return data, "This quiz is still in progress."
        result = main._rk_quiz_result(session_id, row[0], row[1], row[2], row[3])
        return result, f"Quiz accuracy was {result['accuracy']}%."

    def _quiz_history(self, args: dict, envelope: dict):
        data = main.rk_get_quiz_history(limit=args.get("limit", 20))
        return data, f"Loaded {len(data)} completed quizzes."

    def _quiz_performance(self, args: dict, envelope: dict):
        return main.rk_get_quiz_statistics(), "Loaded quiz performance."

    # -- ASSISTANT ----------------------------------------------------------

    def _assistant_get_context(self, args: dict, envelope: dict):
        data = {
            "profile": main.rk_get_profile(),
            "routines": main.rk_get_routines_summary(),
            "study": main.rk_get_study_overview(),
            "progress": main.rk_get_progress(),
        }
        return data, "Loaded the current RK OS context."

    def _assistant_daily_plan(self, args: dict, envelope: dict):
        routines = main.rk_get_routines_summary()
        study = main.rk_get_study_overview()
        weak = main.rk_get_practice_weak_topics()
        plan = {
            "pending_tasks": routines["pending_tasks"],
            "pending_habits": routines["pending_habits"],
            "active_goals": routines["active_goals"],
            "study_target_minutes": study["today_study_minutes"],
            "suggested_focus": weak[0]["topic_name"] if weak else None,
        }
        return plan, "Here is your daily plan."

    def _assistant_recommend_next(self, args: dict, envelope: dict):
        weak = main.rk_get_practice_weak_topics()
        if weak:
            topic = weak[0]
            data = {"recommended_action": "practice.start", "topic_id": topic["topic_id"],
                    "topic_name": topic["topic_name"], "reason": f"Low accuracy ({topic['accuracy']}%)"}
            return data, f"Practise {topic['topic_name']} — your accuracy there is {topic['accuracy']}%."
        topics = main.rk_get_study_topics()
        if not topics:
            return {"recommended_action": None}, "No study topics are available yet."
        topic = topics[0]
        data = {"recommended_action": "study.start_session", "topic_id": topic["id"],
                "topic_name": topic["name"], "reason": "First available study topic"}
        return data, f"Start a study session on {topic['name']}."

    def _assistant_explain_progress(self, args: dict, envelope: dict):
        period = args.get("period", "all")
        progress = main.rk_get_progress()
        if period == "week":
            history = self._aggregate_history(7)
        elif period == "month":
            history = self._aggregate_history(30)
        elif period == "day":
            history = main.rk_get_today_activity()
        else:
            history = None
        data = {"period": period, "progress": progress, "history": history}
        message = (f"Overall score {progress['overall_score']}%. "
                   f"Practice {progress['practice']['accuracy']}%, quiz {progress['quiz']['accuracy']}%.")
        return data, message

    def _assistant_start_focus(self, args: dict, envelope: dict):
        return self._timer_start(args, envelope)

    def _assistant_start_practice(self, args: dict, envelope: dict):
        return self._practice_start(args, envelope)

    def _assistant_start_quiz(self, args: dict, envelope: dict):
        payload = {key: args[key] for key in ("subject_id", "topic_id", "difficulty", "total_questions") if key in args}
        if "subject_id" not in payload:
            subjects = main.rk_get_study_subjects()
            if not subjects:
                raise HTTPException(status_code=409, detail="No study subjects are available yet")
            payload["subject_id"] = subjects[0]["id"]
        session = main.rk_start_quiz_session(payload)
        return session, f"Started a quiz with {session['total_questions']} question(s)."


# Module-level singleton used by the FastAPI integration.
dispatcher = ActionDispatcher()


def dispatch_action(envelope: Any) -> dict:
    """Validate and execute an action envelope, returning a result envelope."""
    return dispatcher.dispatch(envelope)


def get_action_catalog() -> dict:
    """Return the allow-list grouped by permission level."""
    return {
        "read": sorted(READ_ACTIONS),
        "safe_write": sorted(SAFE_WRITE_ACTIONS),
        "write": sorted(WRITE_ACTIONS),
        "destructive": sorted(DESTRUCTIVE_ACTIONS),
    }
