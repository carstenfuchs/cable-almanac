from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


# Code fields must reject dots, as we use dots to separate the levels of qualified ids.
validate_code = validators.RegexValidator(
    validators.slug_unicode_re,
    "Enter a valid code consisting of letters, numbers, underscores or hyphens.",
)


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
    code = models.CharField(max_length=40, validators=[validate_code])
    name = models.CharField(blank=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'code'], name='unique_building_code_per_site'
            ),
        ]

    def __str__(self):
        return self.qualified_id

    @property
    def qualified_id(self):
        return self.code


class Room(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE)
    code = models.CharField(max_length=40, validators=[validate_code])
    name = models.CharField(blank=True)
    note = models.TextField(blank=True)
    floor = models.CharField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['building', 'code'], name='unique_room_code_per_building'
            ),
        ]

    def __str__(self):
        return self.qualified_id

    @property
    def qualified_id(self):
        return f'{self.building.qualified_id}.{self.code}'


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
    a cable end is a single foreign key to a component, and the codes within a
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
    code = models.CharField(max_length=40, validators=[validate_code])
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
                fields=['parent_room', 'code'], name='unique_component_code_per_room'
            ),
            models.UniqueConstraint(
                fields=['parent_distributor', 'code'],
                name='unique_component_code_per_distributor',
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
        return f'{(self.parent_room or self.parent_distributor).qualified_id}.{self.code}'

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


class PathwayKind(models.TextChoices):
    CONDUIT = 'conduit', "Conduit"
    CABLE_TRAY = 'cable_tray', "Cable tray"
    CABLE_ROUTE = 'cable_route', "Cable route"
    PENETRATION = 'penetration', "Wall penetration"
    SHAFT = 'shaft', "Shaft"


class Pathway(models.Model):
    """
    A conduit, cable tray, wall penetration etc. between two rooms.

    Pathways exist independently of the cables in them, as an empty conduit is
    worth documenting as well: it is where new cables can be pulled through.
    """

    from_room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='pathways_from')
    to_room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='pathways_to')

    kind = models.CharField(choices=PathwayKind)
    name = models.CharField()
    note = models.TextField(blank=True)

    diameter = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="In millimeters."
    )

    def __str__(self):
        return self.name


class CableKind(models.TextChoices):
    POWER = 'power', "Power"
    EXTRA_LOW_VOLTAGE = 'extra_low_voltage', "Extra-low voltage"
    TELEPHONE = 'telephone', "Telephone"
    DSL = 'dsl', "DSL"
    FIBER = 'fiber', "Fiber optic"
    CAT5E = 'cat5e', "Cat 5e"
    CAT6 = 'cat6', "Cat 6"
    CAT7 = 'cat7', "Cat 7"
    WIFI = 'wifi', "Wi-Fi"
    DECT = 'dect', "DECT"
    KNX = 'knx', "KNX"
    SIGNAL = 'signal', "Signal"


class Cable(models.Model):
    """
    A connection between two components, usually one physical cable.

    Radio links (Wi-Fi, DECT) are recorded as cables as well. The direction
    from `source` to `target` carries no physical meaning. A `name` is only
    needed if the cable is labeled, e.g. with a cable marker.

    If several cables share one physical sheath, e.g. KNX and telephone lines
    in one telephone cable, each of them names the sheath in `bundle` and the
    conductors it uses in `conductors`. `conductor_use` describes how these
    conductors are wired.

    Nothing keeps a cable from linking the components of two different sites,
    nor a pathway from linking the rooms of two sites. The import never
    creates such links, but the admin doesn't prevent them.
    """

    source = models.ForeignKey(Component, on_delete=models.CASCADE, related_name='cables_from')
    source_terminal = models.CharField(blank=True)
    target = models.ForeignKey(Component, on_delete=models.CASCADE, related_name='cables_to')
    target_terminal = models.CharField(blank=True)

    kind = models.CharField(choices=CableKind)
    name = models.CharField(blank=True)
    note = models.TextField(blank=True)

    pathways = models.ManyToManyField(Pathway, through='PathSegment', related_name='cables')
    cross_section = models.CharField(blank=True)
    length = models.FloatField(null=True, blank=True, help_text="In meters.")
    bundle = models.CharField(blank=True)
    conductors = models.CharField(blank=True)
    conductor_use = models.TextField(blank=True)
    installed = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name or f"{self.source} → {self.target}"


class PathSegment(models.Model):
    """
    The section of a cable that runs through a pathway.

    The order of the path segments mostly follows from the rooms that the
    pathways connect. If an explicit ordering is needed after all, this through
    model is the right place for a `position` field.
    """

    cable = models.ForeignKey(Cable, on_delete=models.CASCADE)
    pathway = models.ForeignKey(Pathway, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            # Like the table that Django creates for an implicit through model.
            models.UniqueConstraint(fields=['cable', 'pathway'], name='unique_path_segment'),
        ]

    def __str__(self):
        return f"{self.cable} via {self.pathway}"
