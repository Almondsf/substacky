from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'username', 'tenant', 'role', 'is_staff')
    list_filter = ('role', 'tenant', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (('Tenant', {'fields': ('tenant', 'role')}),)
