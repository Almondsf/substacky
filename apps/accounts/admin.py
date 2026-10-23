from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Invite


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'username', 'tenant', 'role', 'is_staff')
    list_filter = ('role', 'tenant', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (('Tenant', {'fields': ('tenant', 'role')}),)


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ('email', 'tenant', 'role', 'invited_by', 'expires_at', 'accepted_at')
    list_filter = ('tenant', 'role')
    search_fields = ('email',)
    readonly_fields = ('token',)
