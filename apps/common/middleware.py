from __future__ import annotations

import re

from django.conf import settings
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    """Redirect unauthenticated users to login except for exempt paths."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_urls = [
            re.compile(url) for url in getattr(settings, "LOGIN_EXEMPT_URLS", [])
        ]

    def __call__(self, request):
        if not request.user.is_authenticated:
            path = request.path_info
            if not any(pattern.match(path) for pattern in self.exempt_urls):
                from django.conf import settings as s

                return redirect(f"{s.LOGIN_URL}?next={path}")
        return self.get_response(request)
