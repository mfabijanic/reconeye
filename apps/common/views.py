from __future__ import annotations

from django.http import JsonResponse
from django.views import View


class HealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"})


class ReadinessView(View):
    def get(self, request):
        from django.db import connection

        try:
            connection.ensure_connection()
            db_ok = True
        except Exception:
            db_ok = False
        status = "ok" if db_ok else "degraded"
        return JsonResponse({"status": status, "db": db_ok}, status=200 if db_ok else 503)
