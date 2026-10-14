from django.core.exceptions import ValidationError
from django.test import TestCase

from inventory.models import (
    Building,
    Component,
    DeviceKind,
    DistributorKind,
    OutletKind,
    Room,
    Site,
)


class Test_Component(TestCase):
    """
    Tests the location rules of the `Component` model.
    """

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Example')
        building = Building.objects.create(site=site, slug='HouseA')
        cls.room = Room.objects.create(building=building, slug='Basement')
        cls.board = Component.objects.create(parent_room=cls.room, kind=DistributorKind.SUB_BOARD, slug='SubBoard')
        cls.actuator = Component.objects.create(
            parent_distributor=cls.board, kind=DeviceKind.KNX_ACTUATOR, slug='Actuator1'
        )

    def assertInvalid(self, component, field):
        with self.assertRaises(ValidationError) as cm:
            component.full_clean()
        self.assertIn(field, cm.exception.message_dict)

    def test_kinds_unique(self):
        """The kind values are unique across all groups, as `is_distributor` relies on it."""
        values = DistributorKind.values + OutletKind.values + DeviceKind.values
        self.assertEqual(len(values), len(set(values)))

    def test_slug_unique_per_room(self):
        """Slugs are unique within a room across all kinds."""
        self.assertInvalid(Component(parent_room=self.room, kind=DeviceKind.LIGHT, slug='SubBoard'), '__all__')

    def test_slug_unique_per_distributor(self):
        """Slugs are unique within a distributor, independent of those in its room."""
        duplicate = Component(parent_distributor=self.board, kind=DeviceKind.LIGHT, slug='Actuator1')
        self.assertInvalid(duplicate, '__all__')
        Component(parent_distributor=self.board, kind=DeviceKind.LIGHT, slug='SubBoard').full_clean()

    def test_slug_without_dots(self):
        """Dots in slugs would make qualified ids ambiguous."""
        self.assertInvalid(Component(parent_room=self.room, kind=OutletKind.POWER, slug='Outlet.1'), 'slug')

    def test_container(self):
        """A component is either in a room or in a distributor."""
        self.assertInvalid(Component(kind=DeviceKind.LIGHT, slug='Light1'), '__all__')
        both = Component(parent_room=self.room, parent_distributor=self.board, kind=DeviceKind.LIGHT, slug='Light1')
        self.assertInvalid(both, '__all__')

    def test_distributor_contents(self):
        """Distributors contain components, but no distributors; other components contain nothing."""
        box = Component(parent_distributor=self.board, kind=DistributorKind.JUNCTION_BOX, slug='Box1')
        self.assertInvalid(box, 'parent_distributor')
        light = Component(parent_distributor=self.actuator, kind=DeviceKind.LIGHT, slug='Light1')
        self.assertInvalid(light, 'parent_distributor')
        self.board.kind = DeviceKind.ROUTER
        self.assertInvalid(self.board, 'kind')

    def test_qualified_id(self):
        self.assertEqual(self.actuator.qualified_id, 'HouseA.Basement.SubBoard.Actuator1')
