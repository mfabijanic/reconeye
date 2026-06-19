from django.contrib import admin

from apps.common.models import AuditLog

admin.site.site_header = "ReconEye Administration"
admin.site.site_title = "ReconEye Admin"
admin.site.index_title = "Operations Console"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
	list_display = ("created_at", "action", "target_label", "actor", "route")
	list_filter = ("action", "created_at")
	search_fields = ("target_label", "route", "actor__username", "object_id")
	readonly_fields = (
		"actor",
		"action",
		"content_type",
		"object_id",
		"target_label",
		"route",
		"ip_address",
		"user_agent",
		"before_state",
		"after_state",
		"metadata",
		"created_at",
	)

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False
