from django.contrib import admin

from .models import ReminderHistory, ReminderSchedule, TradingAccount


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
    list_display = ["account", "day_number", "channel", "slot_hour", "status", "sent_at"]
    list_filter = ["channel", "status", "slot_hour"]
    search_fields = ["account__account_name"]


@admin.register(ReminderSchedule)
class ReminderScheduleAdmin(admin.ModelAdmin):
    list_display = ["id", "day_list", "updated_at"]
