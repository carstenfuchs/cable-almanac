from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Site(models.Model):
    """
    A site represents a property with one or more buildings.
    It is the root of the inventory tree.
    """

    name = models.CharField()

    def __str__(self):
        return self.name


class Building(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    slug = models.SlugField(allow_unicode=True)
    name = models.CharField(blank=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'slug'], name='unique_building_slug_per_site'
            ),
        ]

    def __str__(self):
        return self.qualified_id

    @property
    def qualified_id(self):
        return self.slug


class Room(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE)
    slug = models.SlugField(allow_unicode=True)
    name = models.CharField(blank=True)
    note = models.TextField(blank=True)
    floor = models.CharField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['building', 'slug'], name='unique_room_slug_per_building'
            ),
        ]

    def __str__(self):
        return self.qualified_id

    @property
    def qualified_id(self):
        return f'{self.building.qualified_id}.{self.slug}'


class DistributorKind(models.TextChoices):
    MAIN_BOARD = 'main_board', "Main distribution board"
    SUB_BOARD = 'sub_board', "Sub-distribution board"
    NETWORK_CABINET = 'network_cabinet', "Network cabinet"
    JUNCTION_BOX = 'junction_box', "Junction box"


class OutletKind(models.TextChoices):
    POWER = 'power_outlet', "Power outlet"
    NETWORK = 'network_outlet', "Network outlet"
    TELEPHONE = 'telephone_outlet', "Telephone outlet"
    TV = 'tv_outlet', "TV outlet"


class DeviceKind(models.TextChoices):
    NETWORK_SWITCH = 'network_switch', "Network switch"
    ROUTER = 'router', "Router"
    ACCESS_POINT = 'access_point', "Access point"
    LIGHT = 'light', "Light"
    TELEPHONE = 'telephone', "Telephone"
    TV = 'tv', "TV"
    KNX_ACTUATOR = 'knx_actuator', "KNX actuator"
    KNX_SENSOR = 'knx_sensor', "KNX sensor"
    OTHER = 'other', "Other"


class Component(models.Model):
    """
    A distributor, outlet or device: anything a cable can end at.

    The three share one model because they share their fields and their role:
    a cable end is a single foreign key to a component, and the slugs within a
    room are unique across all of them.

    A component can be either directly in a room or in a distributor, never at
    the same time in both.
    """

    parent_room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    parent_distributor = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to={'kind__in': DistributorKind.values},
    )
    kind = models.CharField(
        choices={"Distributor": DistributorKind, "Outlet": OutletKind, "Device": DeviceKind}
    )

    slug = models.SlugField(allow_unicode=True)
    name = models.CharField(blank=True)
    note = models.TextField(blank=True)

    manufacturer = models.CharField(blank=True)
    model = models.CharField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(parent_room__isnull=False, parent_distributor=None)
                | Q(parent_room=None, parent_distributor__isnull=False),
                name='component_in_room_or_distributor',
                violation_error_message="Place the component either in a room or in a distributor.",
            ),
            # As NULLs never compare equal, each constraint only applies to the
            # components in that kind of container.
            models.UniqueConstraint(
                fields=['parent_room', 'slug'], name='unique_component_slug_per_room'
            ),
            models.UniqueConstraint(
                fields=['parent_distributor', 'slug'],
                name='unique_component_slug_per_distributor',
            ),
        ]

    def __str__(self):
        return self.qualified_id

    @property
    def is_distributor(self):
        return self.kind in DistributorKind.values

    @property
    def qualified_id(self):
        """
        The qualified id, e.g. `HouseA.Basement.SubBoard.Actuator1`.
        Triggers an extra query per level unless the containers are `select_related()`.
        """
        return f'{(self.parent_room or self.parent_distributor).qualified_id}.{self.slug}'

    def clean(self):
        # Together with `limit_choices_to`, the two checks below keep the
        # depth of the tree fixed, so that no query ever needs recursion.

        # Distributors are placed directly in rooms.
        if self.is_distributor and self.parent_distributor:
            raise ValidationError(
                {'parent_distributor': "Distributors can only be placed in rooms."}
            )

        # Only distributors (but not outlets or devices) can contain components.
        # Whenever a component is placed in a distributor, `limit_choices_to`
        # ensures that it is one.
        # This check covers changing the kind of a distributor that already has
        # contents. (`self.pk` must be checked because Django refuses to access
        # `component_set` for unsaved objects, but these have no contents anyway.)
        if not self.is_distributor and self.pk and self.component_set.exists():
            raise ValidationError({'kind': "Only distributors can contain components."})
