"""Worker-only UP analysis consumer with independent lease renewal."""
import os
import threading
import time
import uuid

from logger import get_logger
from storage.repositories.analysis_jobs import get_analysis_repository, LostAnalysisLease

logger = get_logger(__name__)
HEARTBEAT_SECONDS = 20
POLL_SECONDS = 2
_guard = threading.Lock()
_thread = None


def _safe_error(code):
    messages = {
        "collector_login_required": "采集登录已失效，请管理员更新采集登录后重新提交",
        "collection_failed": "采集失败，请检查 Worker 日志后重试",
        "core_save_failed": "观测保存失败，本次新批次已回滚",
        "database_permission_denied": "Worker 数据库权限异常，请检查部署配置",
        "calendar_enqueue_failed": "观测已保存，日历任务提交失败",
    }
    return {"code": code, "message": messages[code]}


def run_analysis_once(worker_id: str) -> bool:
    repo = get_analysis_repository()
    if repo is None:
        raise RuntimeError("PostgreSQL analysis repository is not configured")
    job = repo.claim(worker_id, int(time.time()))
    if not job:
        return False
    job_id, token = job["id"], job["fencing_token"]
    stop, lost = threading.Event(), threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                if not repo.renew(job_id, worker_id, token, int(time.time())):
                    lost.set()
                    return
            except Exception:
                logger.exception("analysis lease renewal failed")
                lost.set()
                return

    renewer = threading.Thread(target=heartbeat, name="up-analysis-lease", daemon=True)
    renewer.start()
    phase = "collection_failed"
    try:
        if job["status"] == "running":
            from collectors.bilibili_user import analyze_tracked_ups_with_progress
            started = time.time()

            def progress_cb(index, up_name):
                if lost.is_set():
                    raise LostAnalysisLease("analysis lease lost")
                current = index + 1
                elapsed = max(0.001, time.time() - started)
                total = len(job["roster"])
                repo.update_progress(job_id, worker_id, token, int(time.time()), {
                    "total": total, "current": current, "current_up": up_name,
                    "eta_seconds": int(max(0, total - current) * elapsed / max(1, current)),
                })

            result = analyze_tracked_ups_with_progress(job["roster"], progress_cb)
            if lost.is_set():
                raise LostAnalysisLease("analysis lease lost")
            if result.get("error"):
                code = "collector_login_required" if result["error"] in ("not_logged_in", "cookie_expired") else "collection_failed"
                repo.finish(job_id, worker_id, token, int(time.time()), "failed", {}, _safe_error(code))
                return True
            phase = "core_save_failed"
            job = repo.commit_core(job_id, worker_id, token, int(time.time()), result)
        if lost.is_set():
            raise LostAnalysisLease("analysis lease lost")
        phase = "calendar_enqueue_failed"
        from jobs.calendar_jobs import enqueue_calendar_job
        followup, _ = enqueue_calendar_job(
            mode="recent", days=7, mids=[u["mid"] for u in job["roster"]],
            requested_by="system:analysis", reason="UP 主动态分析完成",
            dedupe_key=f"analysis:{job_id}", dedupe_forever=True,
        )
        repo.finish(job_id, worker_id, token, int(time.time()), "succeeded",
                    {**job["result_summary"], "calendar_job_id": followup["id"]})
    except LostAnalysisLease:
        logger.warning("analysis ownership lost; stale worker stopped writing")
    except Exception as exc:
        logger.exception("analysis phase failed: %s", phase)
        code = "database_permission_denied" if getattr(getattr(exc, "orig", None), "sqlstate", None) == "42501" else phase
        try:
            if lost.is_set():
                raise LostAnalysisLease("analysis lease lost")
            partial = job["status"] == "finalizing"
            error = _safe_error(code)
            summary = {**job["result_summary"], "warnings": [error]} if partial else {}
            repo.finish(job_id, worker_id, token, int(time.time()), "partial" if partial else "failed", summary, error)
        except LostAnalysisLease:
            logger.warning("analysis failure belongs to an expired claim; not overwritten")
        except Exception:
            logger.exception("analysis terminal update failed; lease recovery will retry")
    finally:
        stop.set()
        renewer.join(timeout=5)
    return True


def ensure_analysis_worker() -> None:
    global _thread
    with _guard:
        if _thread is not None and _thread.is_alive():
            return
        worker_id = f"{os.environ.get('KICHU_WORKER_ID', 'worker')}-{uuid.uuid4().hex}"
        def consume():
            while True:
                try:
                    run_analysis_once(worker_id)
                except Exception:
                    logger.exception("analysis queue polling failed")
                time.sleep(POLL_SECONDS)
        _thread = threading.Thread(target=consume, name="up-analysis-consumer", daemon=True)
        _thread.start()
