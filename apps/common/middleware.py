from __future__ import annotations

import re

from django.conf import settings
from django.shortcuts import redirect
from django.utils import translation


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


class UserLanguageMiddleware:
    """Apply persisted user language preference for each authenticated request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = None
        if request.user.is_authenticated:
            preferred = getattr(request.user, "preferred_language", "")
            supported = {code for code, _ in getattr(settings, "LANGUAGES", [])}
            if preferred in supported:
                language = preferred

        if language:
            translation.activate(language)
            request.LANGUAGE_CODE = language

        response = self.get_response(request)

        if language:
            response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language)
        return response
