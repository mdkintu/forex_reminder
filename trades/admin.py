from django.contrib import admin

from .models import ReminderHistory, ReminderRun, ReminderSchedule, TradingAccount


class ReminderHistoryInline(admin.TabularInline):
    model = ReminderHistory
    extra = 0


@admin.register(TradingAccount)
class TradingAccountAdmin(admin.ModelAdmin):
    list_display = [
        "account_name",
        "account_number",
        "user",
        "broker",
        "last_trade_date",
        "inactivity_days",
        "notify_email",
        "notify_whatsapp",
        "notify_telegram",
    ]
    list_filter = [
        "notify_email",
        "notify_whatsapp",
        "notify_telegram",
        "user",
    ]
    search_fields = ["account_name", "account_number", "broker", "user__email"]
    inlines = [ReminderHistoryInline]


@admin.register(ReminderHistory)
class ReminderHistoryAdmin(admin.ModelAdmin):
    list_display = ["account", "day_number", "channel", "slot_hour", "status", "attempts", "catch_up", "short_error", "sent_at"]
    list_filter = ["channel", "status", "catch_up", "slot_hour"]

    @admin.display(description="Error")
    def short_error(self, obj):
        return (obj.error[:80] + "…") if len(obj.error) > 80 else obj.error
    search_fields = ["account__account_name"]


@admin.register(ReminderSchedule)
class ReminderScheduleAdmin(admin.ModelAdmin):
    list_display = ["id", "days_left", "updated_at"]


@admin.register(ReminderRun)
class ReminderRunAdmin(admin.ModelAdmin):
    """Read-only log of reminder-job runs (written by the job itself)."""

    list_display = ["finished_at", "checked", "sent", "skipped", "failed", "report_sent"]
    list_filter = ["report_sent"]
    date_hierarchy = "finished_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
