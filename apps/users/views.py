from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.shortcuts import render
from django.views import View

from .forms import LoginForm, UserMapSettingsForm
from .models import UserMapSettings

logger = logging.getLogger(__name__)


class UserLoginView(LoginView):
    template_name = "users/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        logger.info("User logged in: %s from %s", user.username, self.request.META.get("REMOTE_ADDR"))
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.warning(
            "Failed login attempt for username=%r from %s",
            self.request.POST.get("username"),
            self.request.META.get("REMOTE_ADDR"),
        )
        return super().form_invalid(form)


class UserLogoutView(View):
    def post(self, request):
        logout(request)
        return redirect("users:login")


class UserSettingsView(LoginRequiredMixin, View):
    template_name = "users/settings.html"

    def get(self, request):
        map_settings, _ = UserMapSettings.objects.get_or_create(user=request.user)
        form = UserMapSettingsForm(instance=map_settings)
        return render(request, self.template_name, {"map_settings_form": form})

    def post(self, request):
        map_settings, _ = UserMapSettings.objects.get_or_create(user=request.user)
        form = UserMapSettingsForm(request.POST, instance=map_settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("users:settings")
        return render(request, self.template_name, {"map_settings_form": form})
