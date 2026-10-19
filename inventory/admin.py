from django.contrib import admin

from .models import Building, Cable, Component, PathSegment, Pathway, Room, Site


admin.site.register(Site)


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'site')
    list_filter = ('site',)
    search_fields = ('code', 'name')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('qualified_id', 'name', 'floor')
    list_filter = ('building',)
    list_select_related = ('building',)
    search_fields = ('code', 'name')
    ordering = ('building__code', 'code')


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ('qualified_id', 'kind', 'name')
    list_filter = ('kind',)
    # For the qualified id.
    list_select_related = ('parent_room__building', 'parent_distributor__parent_room__building')
    search_fields = ('code', 'name')
    autocomplete_fields = ('parent_room', 'parent_distributor')
    # Without an ordering, the autocomplete for `parent_distributor` paginates
    # an unordered queryset and Django warns about it.
    ordering = ('pk',)


@admin.register(Pathway)
class PathwayAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'from_room', 'to_room')
    list_filter = ('kind',)
    list_select_related = ('from_room__building', 'to_room__building')
    search_fields = ('name',)
    autocomplete_fields = ('from_room', 'to_room')
    ordering = ('name',)


class PathSegmentInline(admin.TabularInline):
    model = PathSegment
    autocomplete_fields = ('pathway',)
    extra = 0


@admin.register(Cable)
class CableAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'kind')
    list_filter = ('kind',)
    # For the qualified ids of both ends.
    list_select_related = (
        'source__parent_room__building',
        'source__parent_distributor__parent_room__building',
        'target__parent_room__building',
        'target__parent_distributor__parent_room__building',
    )
    search_fields = ('name', 'source__code', 'target__code')
    autocomplete_fields = ('source', 'target')
    inlines = (PathSegmentInline,)
