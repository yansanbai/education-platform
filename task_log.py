import json
import time
from contextlib import contextmanager


def save_event(db, job, attempt, stage, event, message, details, entry_id=None):
    payload = json.dumps(details, ensure_ascii=False, default=str)
    if entry_id is not None:
        db.execute("""UPDATE task_logs SET message=?, details=?
            WHERE id=? AND job=? AND attempt=?""", (message, payload, entry_id, job, attempt))
        return entry_id
    return db.execute("""INSERT INTO task_logs(job, attempt, stage, event, message, details, created_at)
        VALUES(?,?,?,?,?,?,?)""", (job, attempt, stage, event, message, payload, time.time())).lastrowid


def model_response(details, response):
    details["http_status"] = response.status_code
    request_id = response.headers.get("x-request-id") or response.headers.get("x-tt-logid")
    if request_id:
        details["provider_request_id"] = request_id
    if not response.is_success:
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict) and error.get("code"):
                details["provider_error_code"] = str(error["code"])[:150]
        except (ValueError, AttributeError):
            pass


@contextmanager
def trace_call(log, provider, model, operation, **context):
    details = {"provider":provider, "model":model, "operation":operation, **context}
    if log is None:
        yield details
        return
    started = time.monotonic()
    label = f"{provider} · {operation}"
    entry_id = log("api", label, **details, status="running")
    try:
        yield details
    except Exception as exc:
        details["status"] = "failed"
        details["error_type"] = type(exc).__name__
        if details.get("http_status") is None:
            details["failure"] = "连接或发送失败，未收到 HTTP 响应"
        raise
    else:
        details["status"] = "done"
    finally:
        details["duration_ms"] = round((time.monotonic()-started)*1000)
        log("api",label,entry_id=entry_id,**details)
