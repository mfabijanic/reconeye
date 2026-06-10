from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager
from uuid import uuid4

from celery import current_app
from django.conf import settings
from django.core.cache import cache

from apps.common.cache import make_key

ACTIVITY_TTL_SECONDS = 60 * 60
_ACTIVITY_CACHE_KEY = make_key("celery_tasks", "activity")
_LAST_SEEN_CACHE_KEY = make_key("celery_tasks", "last_seen")


def _load_activity_map() -> dict[str, dict[str, float | str]]:
    data = cache.get(_ACTIVITY_CACHE_KEY, {})
    if isinstance(data, dict):
        return data
    return {}


def _save_activity_map(
    activity_map: dict[str, dict[str, float | str]],
    *,
    ttl_seconds: int,
) -> None:
    if not activity_map:
        cache.delete(_ACTIVITY_CACHE_KEY)
        return
    cache.set(_ACTIVITY_CACHE_KEY, activity_map, timeout=max(ttl_seconds + 300, 600))


def _purge_expired(
    activity_map: dict[str, dict[str, float | str]],
) -> tuple[dict[str, dict[str, float | str]], bool]:
    now = time.time()
    filtered: dict[str, dict[str, float | str]] = {}
    changed = False

    for marker_id, payload in activity_map.items():
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)) and expires_at > now:
            filtered[marker_id] = payload
        else:
            changed = True

    return filtered, changed


def register_task_start(task_name: str, task_id: str = "", *, ttl_seconds: int = ACTIVITY_TTL_SECONDS) -> str:
    marker_id = task_id or f"{task_name}:{uuid4().hex}"
    now = time.time()
    activity_map = _load_activity_map()
    activity_map[marker_id] = {
        "task_name": task_name,
        "started_at": now,
        "expires_at": now + max(30, ttl_seconds),
    }
    _save_activity_map(activity_map, ttl_seconds=ttl_seconds)
    cache.set(_LAST_SEEN_CACHE_KEY, now, timeout=max(ttl_seconds + 300, 600))
    return marker_id


def register_task_finish(marker_id: str) -> None:
    if not marker_id:
        return
    activity_map = _load_activity_map()
    if marker_id in activity_map:
        activity_map.pop(marker_id, None)
        _save_activity_map(activity_map, ttl_seconds=ACTIVITY_TTL_SECONDS)


def _to_label(task_name: str) -> str:
    if task_name.startswith("reconeye."):
        return task_name.split(".")[-1]
    return task_name


def _is_shared_cache_backend() -> bool:
    backend = (
        settings.CACHES.get("default", {}).get("BACKEND", "")
        if hasattr(settings, "CACHES")
        else ""
    )
    return "locmem" not in backend.lower()


def _inspect_runtime_tasks(*, limit: int = 3) -> dict[str, int | list[dict[str, int | str]]]:
    """Best-effort runtime task summary using Celery inspect.

    Used as fallback when cache backend is process-local (LocMem), where
    worker-updated markers are not visible from the web process.
    """
    try:
        inspector = current_app.control.inspect(timeout=0.8)
        if inspector is None:
            return {"active_count": 0, "top_tasks": [], "extra_task_types": 0}

        counts = Counter()

        for group in (
            inspector.active() or {},
            inspector.reserved() or {},
            inspector.scheduled() or {},
        ):
            for tasks in group.values():
                if not isinstance(tasks, list):
                    continue
                for task in tasks:
                    name = str(task.get("name") or "")
                    if not name.startswith("reconeye."):
                        continue
                    counts[name] += 1

        top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: max(1, limit)]
        top_tasks = [
            {"name": name, "label": _to_label(name), "count": count}
            for name, count in top
        ]
        total = sum(counts.values())
        return {
            "active_count": total,
            "top_tasks": top_tasks,
            "extra_task_types": max(0, len(counts) - len(top_tasks)),
        }
    except Exception:
        return {"active_count": 0, "top_tasks": [], "extra_task_types": 0}


def get_active_task_summary(*, limit: int = 3) -> dict[str, int | float | list[dict[str, int | str]]]:
    activity_map, changed = _purge_expired(_load_activity_map())
    if changed:
        _save_activity_map(activity_map, ttl_seconds=ACTIVITY_TTL_SECONDS)

    counts = Counter(
        str(payload.get("task_name", "unknown")) for payload in activity_map.values()
    )
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: max(1, limit)]

    top_tasks = [{"name": name, "label": _to_label(name), "count": count} for name, count in top]
    active_count = len(activity_map)
    last_seen_at = cache.get(_LAST_SEEN_CACHE_KEY)

    # In local-dev LocMem cache, web and worker do not share marker state.
    # Fallback to Celery inspect so navbar still reflects background activity.
    if not _is_shared_cache_backend():
        runtime_summary = _inspect_runtime_tasks(limit=limit)
        runtime_count = int(runtime_summary.get("active_count", 0))
        if runtime_count > 0:
            return {
                "active_count": runtime_count,
                "top_tasks": runtime_summary.get("top_tasks", []),
                "extra_task_types": runtime_summary.get("extra_task_types", 0),
                "last_seen_at": time.time(),
            }

    return {
        "active_count": active_count,
        "top_tasks": top_tasks,
        "extra_task_types": max(0, len(counts) - len(top_tasks)),
        "last_seen_at": float(last_seen_at) if isinstance(last_seen_at, (int, float)) else None,
    }


@contextmanager
def track_task_activity(task_name: str, task_id: str = "", *, ttl_seconds: int = ACTIVITY_TTL_SECONDS):
    marker_id = register_task_start(task_name, task_id, ttl_seconds=ttl_seconds)
    try:
        yield
    finally:
        register_task_finish(marker_id)
