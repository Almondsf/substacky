from django.contrib import admin
from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('event_id',)
    readonly_fields = ('event_id', 'event_type', 'payload', 'created_at')
