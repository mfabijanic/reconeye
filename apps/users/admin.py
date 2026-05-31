from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserMapSettings


class UserMapSettingsInline(admin.StackedInline):
    model = UserMapSettings
    can_delete = False
    extra = 1
    max_num = 1
    fields = (
        "disable_clustering_at_zoom",
        "marker_limit",
        "status_stale_minutes",
        "popup_close_on_mouseout",
        "updated_at",
    )
    readonly_fields = ("updated_at",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserMapSettingsInline]

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Preferences", {"fields": ("preferred_language",)}),
    )
