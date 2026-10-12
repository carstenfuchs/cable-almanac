from django.contrib import admin

from .models import Building, Component, Room, Site


admin.site.register(Site)


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'site')
    list_filter = ('site',)
    search_fields = ('slug', 'name')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('qualified_id', 'name', 'floor')
    list_filter = ('building',)
    list_select_related = ('building',)
    search_fields = ('slug', 'name')
    ordering = ('building__slug', 'slug')


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ('qualified_id', 'kind', 'name')
    list_filter = ('kind',)
    # For the qualified id.
    list_select_related = ('parent_room__building', 'parent_distributor__parent_room__building')
    search_fields = ('slug', 'name')
    autocomplete_fields = ('parent_room', 'parent_distributor')
    # Without an ordering, the autocomplete for `parent_distributor` paginates
    # an unordered queryset and Django warns about it.
    ordering = ('pk',)
