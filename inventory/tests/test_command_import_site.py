import datetime
import tempfile
import textwrap
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from inventory.models import (
    Building,
    Cable,
    CableKind,
    Component,
    DeviceKind,
    Pathway,
    PathwayKind,
    Room,
    Site,
)


SITE = {
    'buildings.yaml': """
        - id: H1
          name: Wohnhaus
        """,
    'rooms.yaml': """
        - id: Keller
          building: H1
          floor: KG
        - id: Flur
          building: H1
          floor: EG
        """,
    'distributors.yaml': """
        - id: HV
          room: H1.Keller
          kind: HV
        """,
    'outlets.yaml': """
        - id: Dose1
          location: H1.Flur
          kind: Netzwerk
        """,
    'devices.yaml': """
        - id: Switch
          location: H1.Keller.HV
          kind: IP_Switch
          manufacturer: Netgear
        """,
    'conduits.yaml': """
        - id: LR-01
          kind: Leerrohr
          from_room: H1.Keller
          to_room: H1.Flur
          diameter_mm: 25
        """,
    'cables.yaml': """
        - id: N-01
          type: Cat6
          source: { kind: device, ref_id: H1.Keller.HV.Switch, terminal: Port-1 }
          target: { kind: outlet, ref_id: H1.Flur.Dose1 }
          path: [LR-01]
          length_m: 12.5
          installed: 2024-09-15
          annotation: Measured on site.
        """,
}


class Test_import_site(TestCase):
    """
    Tests the import of the YAML files of a site.
    """

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.directory = Path(temp_dir.name) / 'example'
        self.directory.mkdir()

        for filename, content in SITE.items():
            self.write(filename, content)

    def write(self, filename, content):
        content = textwrap.dedent(content).lstrip('\n')
        (self.directory / filename).write_text(content, encoding='utf-8')

    def import_site(self):
        out = StringIO()
        call_command('import_site', self.directory, stdout=out)
        return out.getvalue()

    def assertImportError(self, message):
        with self.assertRaises(CommandError) as cm:
            self.import_site()
        self.assertIn(message, str(cm.exception))
        self.assertFalse(Site.objects.exists())

    def test_import(self):
        self.assertIn("Imported the site 'example'", self.import_site())

        switch = Component.objects.get(code='Switch')
        self.assertEqual(switch.qualified_id, 'H1.Keller.HV.Switch')
        self.assertEqual(switch.kind, DeviceKind.NETWORK_SWITCH)
        self.assertEqual(switch.manufacturer, 'Netgear')

        pathway = Pathway.objects.get()
        self.assertEqual(pathway.kind, PathwayKind.CONDUIT)
        self.assertEqual(pathway.diameter, 25)

        cable = Cable.objects.get()
        self.assertEqual(cable.kind, CableKind.CAT6)
        self.assertEqual(cable.name, 'N-01')
        self.assertEqual((cable.source, cable.source_terminal), (switch, 'Port-1'))
        self.assertEqual(cable.target.qualified_id, 'H1.Flur.Dose1')
        self.assertEqual(cable.target_terminal, '')
        self.assertEqual(cable.length, 12.5)
        self.assertEqual(cable.installed, datetime.date(2024, 9, 15))
        self.assertEqual(cable.annotation, 'Measured on site.')
        self.assertEqual(list(cable.pathways.all()), [pathway])

    def test_site(self):
        """The name in `site.yaml` takes precedence over that of the directory."""
        self.write(
            'site.yaml',
            """
            name: Beispiel
            note: Family home
            annotation: |
              ## Sources

              Wiring diagram of 2019.
            """,
        )

        self.assertIn("Imported the site 'Beispiel'", self.import_site())

        site = Site.objects.get()
        self.assertEqual(site.note, 'Family home')
        self.assertEqual(site.annotation, '## Sources\n\nWiring diagram of 2019.\n')

    def test_compare_unchanged(self):
        self.import_site()
        self.assertIn("The site 'example' matches the YAML files.", self.import_site())

    def test_compare_changed(self):
        """
        A second import only reports the differences. It finds the existing site
        regardless of the case of its name.
        """
        self.import_site()

        self.write('site.yaml', "name: Example\nnote: Family home")

        self.write(
            'buildings.yaml',
            """
            - id: H1
              name: Wohnhaus
              note: Built in 1965
            """,
        )

        self.write(
            'rooms.yaml',
            """
            - id: Keller
              building: H1
              floor: KG
            - id: Flur
              building: H1
              floor: EG
            - id: Dachboden
              building: H1
              floor: DG
            """,
        )

        self.write('cables.yaml', "[]")

        lines = self.import_site().splitlines()
        self.assertEqual(
            lines[1:-1],
            [
                "~ site: name: 'example' → 'Example'",
                "~ site: note: '' → 'Family home'",
                "~ building H1: note: '' → 'Built in 1965'",
                "+ room H1.Dachboden",
                "- cat6 cable H1.Keller.HV.Switch [Port-1] → H1.Flur.Dose1",
            ],
        )

        self.assertEqual(Site.objects.get().name, 'example')
        self.assertEqual(Building.objects.get().note, '')
        self.assertFalse(Room.objects.filter(code='Dachboden').exists())
        self.assertTrue(Cable.objects.exists())

    def test_unknown_reference(self):
        self.write(
            'rooms.yaml',
            """
            - id: Keller
              building: H2
              floor: KG
            """,
        )

        self.assertImportError("rooms.yaml:1 (id=Keller): building: unknown 'H2'")

    def test_unknown_key(self):
        self.write(
            'buildings.yaml',
            """
            - id: H1
              colour: red
            """,
        )

        self.assertImportError("buildings.yaml:1 (id=H1): unknown keys: colour")

    def test_unknown_file(self):
        self.write('sites.yaml', "name: Example")
        self.assertImportError("Unknown files: sites.yaml")

    def test_site_error(self):
        self.write('site.yaml', "id: example")
        self.assertImportError("site.yaml: unknown keys: id")

    def test_type(self):
        """YAML turns an unquoted `no` into a boolean, which must not pass as a string."""
        self.write(
            'buildings.yaml',
            """
            - id: H1
              name: no
            """,
        )

        self.assertImportError("buildings.yaml:1 (id=H1): name: expected a string, found False")

    def test_duplicate(self):
        self.write(
            'rooms.yaml',
            """
            - id: Keller
              building: H1
              floor: KG
            - id: Keller
              building: H1
              floor: EG
            """,
        )

        self.assertImportError(
            "rooms.yaml:4 (id=Keller): duplicate of the entry in rooms.yaml:1"
        )

    def test_invalid_code(self):
        """The errors of the model validation name the YAML keys."""
        self.write('buildings.yaml', "- id: H.1")
        self.assertImportError("buildings.yaml:1 (id=H.1): id: Enter a valid code")

    def test_location(self):
        self.write(
            'devices.yaml',
            """
            - id: Switch
              location: H1.Flur.Dose1
              kind: IP_Switch
            """,
        )

        self.assertImportError("location: 'H1.Flur.Dose1' is neither a room nor a distributor")

    def test_endpoint_kind(self):
        self.write(
            'cables.yaml',
            """
            - type: Cat6
              source: { kind: outlet, ref_id: H1.Keller.HV.Switch }
              target: { kind: outlet, ref_id: H1.Flur.Dose1 }
            """,
        )

        self.assertImportError("source: 'H1.Keller.HV.Switch' is not of kind 'outlet'")
