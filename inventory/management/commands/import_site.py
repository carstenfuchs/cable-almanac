"""
Imports a site from the YAML files of the prototype `smart-home-kabeldoku`.

A site is a directory with up to seven YAML files, one per kind of entity, each
a list of entries. The prototype documents the format in `docs/modell.md`.
Its values are German, so the import maps them to the choices of our models.

If no site of the same name exists, the import creates it. Otherwise, it only
reports how the YAML files differ from the existing site.
"""

import datetime
from pathlib import Path

import yaml
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from inventory.models import (
    Building,
    Cable,
    CableKind,
    Component,
    DeviceKind,
    DistributorKind,
    OutletKind,
    PathSegment,
    Pathway,
    PathwayKind,
    Room,
    Site,
)


DISTRIBUTOR_KINDS = {
    'HV': DistributorKind.MAIN_BOARD,
    'UV': DistributorKind.SUB_BOARD,
    'Netzwerkschrank': DistributorKind.NETWORK_CABINET,
    'Abzweigdose': DistributorKind.JUNCTION_BOX,
}

OUTLET_KINDS = {
    'Strom': OutletKind.POWER,
    'Netzwerk': OutletKind.NETWORK,
    'Telefon': OutletKind.TELEPHONE,
    'TV': OutletKind.TV,
}

DEVICE_KINDS = {
    'IP_Switch': DeviceKind.NETWORK_SWITCH,
    'IP_Router': DeviceKind.ROUTER,
    'Access_Point': DeviceKind.ACCESS_POINT,
    'Lampe': DeviceKind.LIGHT,
    'Telefon': DeviceKind.TELEPHONE,
    'TV': DeviceKind.TV,
    'KNX_Aktor': DeviceKind.KNX_ACTUATOR,
    'KNX_Sensor': DeviceKind.KNX_SENSOR,
    'Geraet': DeviceKind.OTHER,
}

PATHWAY_KINDS = {
    'Leerrohr': PathwayKind.CONDUIT,
    'Pritsche': PathwayKind.CABLE_TRAY,
    'Trasse': PathwayKind.CABLE_ROUTE,
    'Durchbruch': PathwayKind.PENETRATION,
    'Schacht': PathwayKind.SHAFT,
}

CABLE_KINDS = {
    'Strom': CableKind.POWER,
    'Kleinspannung': CableKind.EXTRA_LOW_VOLTAGE,
    'Telefon': CableKind.TELEPHONE,
    'DSL': CableKind.DSL,
    'Glasfaser': CableKind.FIBER,
    'Cat5e': CableKind.CAT5E,
    'Cat6': CableKind.CAT6,
    'Cat7': CableKind.CAT7,
    'WLAN': CableKind.WIFI,
    'DECT': CableKind.DECT,
    'KNX': CableKind.KNX,
    'Signal': CableKind.SIGNAL,
}

# The endpoints of cables state the kind of the component they refer to.
ENDPOINT_KINDS = {
    'distributor': DistributorKind,
    'outlet': OutletKind,
    'device': DeviceKind,
}

# The YAML keys of the fields whose names differ, for error messages.
YAML_KEYS = {'code': 'id', 'diameter': 'diameter_mm', 'length': 'length_m'}

TYPE_NAMES = {
    str: "a string",
    int: "an integer",
    float: "a number",
    datetime.date: "a date",
    dict: "a mapping",
    list: "a list",
}

# The order of the kinds of objects in comparisons.
KINDS_ORDER = ['building', 'room', 'component', 'pathway', 'cable']


class EntryError(Exception):
    """An error in an entry of a YAML file."""


def load_yaml(path):
    """
    Returns the entries of a YAML file as (line, entry) pairs, or an empty list
    if the file doesn't exist.

    The line is the first line of the entry, as editors expect it in
    `file:line`. To get it, the loader is driven by hand, as `yaml.safe_load()`
    discards the positions of the nodes.
    """
    if not path.exists():
        return []

    with path.open(encoding='utf-8') as file:
        loader = yaml.SafeLoader(file)
        try:
            node = loader.get_single_node()
            if node is None:
                return []
            data = loader.construct_document(node)
        except yaml.YAMLError as error:
            raise CommandError(f"{path.name}: {error}") from error
        finally:
            loader.dispose()

    if not isinstance(data, list):
        raise CommandError(f"{path.name}: expected a list of entries")

    return [
        (node.start_mark.line + 1, entry) for node, entry in zip(node.value, data, strict=True)
    ]


def has_type(value, expected):
    # `bool` is a subclass of `int`, and `datetime` one of `date`.
    if isinstance(value, bool | datetime.datetime):
        return False
    if expected is float:
        return isinstance(value, int | float)
    return isinstance(value, expected)


def check_fields(entry, required, optional, prefix=''):
    """
    Checks the keys of an entry and the types of their values. Returns the
    values, with an empty string or `None` for missing optional keys.

    The type check matters because YAML turns unquoted values like `no` or
    `off` into booleans, which Django would silently store as "False".
    """
    if not isinstance(entry, dict):
        raise EntryError(f"{prefix}expected a mapping, found {entry!r}")

    unknown = entry.keys() - required.keys() - optional.keys()
    if unknown:
        raise EntryError(
            f"unknown keys: {', '.join(sorted(prefix + str(key) for key in unknown))}"
        )

    values = {}
    for key, expected in (required | optional).items():
        value = entry.get(key)
        if value is None:
            if key in required:
                raise EntryError(f"{prefix}{key}: missing")
            value = '' if expected is str else None
        elif not has_type(value, expected):
            raise EntryError(f"{prefix}{key}: expected {TYPE_NAMES[expected]}, found {value!r}")

        values[key] = value

    return values


def choice(choices, value, key):
    """Returns the choice for the German `value` of `key`."""
    if value not in choices:
        raise EntryError(
            f"{key}: unknown value {value!r}, expected one of {', '.join(choices)}"
        )

    return choices[value]


def resolve(objects, ref, key):
    """Returns the object that `ref`, the value of `key`, refers to."""
    if ref not in objects:
        raise EntryError(f"{key}: unknown {ref!r}")
    return objects[ref]


def cable_key(cable):
    """
    Identifies a cable by its kind and its ends, as cables have no ids of their
    own. The kind is needed for cables that share a sheath, which may have the
    same ends.
    """
    return (
        'cable',
        cable.kind,
        cable.source.qualified_id,
        cable.source_terminal,
        cable.target.qualified_id,
        cable.target_terminal,
    )


def describe(key):
    """Describes the object with `key` for the comparison."""
    if key[0] != 'cable':
        return f"{key[0]} {key[1]}"

    kind, source, source_terminal, target, target_terminal = key[1:]
    source = f"{source} [{source_terminal}]" if source_terminal else source
    target = f"{target} [{target_terminal}]" if target_terminal else target
    return f"{kind} cable {source} → {target}"


def site_records(site):
    """
    Returns the objects of `site` as {key: {field: value}}, with keys that don't
    depend on database ids, so that two sites can be compared.
    """
    records = {}

    def add(key, obj, **values):
        if key in records:
            raise CommandError(f"The site {site.name!r} contains the {describe(key)} twice.")

        # The values include those in the key, but these are equal anyway.
        records[key] = {
            field.name: getattr(obj, field.name)
            for field in obj._meta.concrete_fields
            if not field.is_relation and not field.primary_key
        } | values

    for building in Building.objects.filter(site=site):
        add(('building', building.qualified_id), building)

    for room in Room.objects.filter(building__site=site).select_related('building'):
        add(('room', room.qualified_id), room)

    in_site = Q(parent_room__building__site=site) | Q(
        parent_distributor__parent_room__building__site=site
    )
    for component in Component.objects.filter(in_site).select_related(
        'parent_room__building', 'parent_distributor__parent_room__building'
    ):
        add(('component', component.qualified_id), component)

    for pathway in Pathway.objects.filter(from_room__building__site=site).select_related(
        'from_room__building', 'to_room__building'
    ):
        add(
            ('pathway', pathway.name),
            pathway,
            from_room=pathway.from_room.qualified_id,
            to_room=pathway.to_room.qualified_id,
        )

    cables = (
        Cable.objects.filter(
            Q(source__parent_room__building__site=site)
            | Q(source__parent_distributor__parent_room__building__site=site)
        )
        .select_related(
            'source__parent_room__building',
            'source__parent_distributor__parent_room__building',
            'target__parent_room__building',
            'target__parent_distributor__parent_room__building',
        )
        .prefetch_related('pathways')
    )
    for cable in cables:
        add(cable_key(cable), cable, pathways=sorted(p.name for p in cable.pathways.all()))

    return records


def compare(old_records, new_records):
    """Returns the differences between the records of two sites as lines of text."""
    keys = sorted(
        old_records.keys() | new_records.keys(),
        key=lambda key: (KINDS_ORDER.index(key[0]), key[1:]),
    )

    lines = []
    for key in keys:
        if key not in old_records:
            lines.append(f"+ {describe(key)}")
        elif key not in new_records:
            lines.append(f"- {describe(key)}")
        else:
            old, new = old_records[key], new_records[key]
            lines += [
                f"~ {describe(key)}: {field}: {old[field]!r} → {new[field]!r}"
                for field in old
                if old[field] != new[field]
            ]

    return lines


class Importer:
    """
    Creates the objects of a site from its YAML files, after checking each entry.
    """

    def __init__(self, directory, site):
        self.directory = directory
        self.site = site

        # The objects by their qualified ids, pathways by their names,
        # to resolve the references of later entries.
        self.buildings = {}
        self.rooms = {}
        self.components = {}
        self.pathways = {}
        self.cable_count = 0

        # Where each object is defined, to report duplicates with both places.
        self.places = {}
        self.place = None

    def claim(self, key):
        """Notes where the object with `key` is defined, refusing duplicates."""
        if key in self.places:
            raise EntryError(f"duplicate of the entry in {self.places[key]}")
        self.places[key] = self.place

    def save(self, obj):
        """Validates and saves `obj`."""
        try:
            obj.full_clean()
        except ValidationError as error:
            raise EntryError(
                "; ".join(
                    message
                    if field == NON_FIELD_ERRORS
                    else f"{YAML_KEYS.get(field, field)}: {message}"
                    for field, messages in error.message_dict.items()
                    for message in messages
                )
            ) from error

        obj.save()
        return obj

    def location(self, qid):
        """Returns the container field for a `location`, a room or a distributor."""
        if qid in self.rooms:
            return {'parent_room': self.rooms[qid]}

        component = resolve(self.components, qid, 'location')
        if not component.is_distributor:
            raise EntryError(f"location: {qid!r} is neither a room nor a distributor")
        return {'parent_distributor': component}

    def endpoint(self, values, key):
        """Returns the component and the terminal of the endpoint `key` of a cable."""
        values = check_fields(
            values, {'kind': str, 'ref_id': str}, {'terminal': str}, f'{key}.'
        )

        kinds = choice(ENDPOINT_KINDS, values['kind'], f'{key}.kind')
        component = resolve(self.components, values['ref_id'], f'{key}.ref_id')
        if component.kind not in kinds.values:
            raise EntryError(f"{key}: {values['ref_id']!r} is not of kind {values['kind']!r}")
        return component, values['terminal']

    def add_component(self, values, kinds, **fields):
        component = Component(
            kind=choice(kinds, values['kind'], 'kind'),
            code=values['id'],
            name=values['name'],
            note=values['note'],
            annotation=values['annotation'],
            **fields,
        )

        self.claim(component.qualified_id)
        self.components[component.qualified_id] = self.save(component)

    def import_building(self, entry):
        values = check_fields(entry, {'id': str}, {'name': str, 'note': str, 'annotation': str})

        building = Building(
            site=self.site,
            code=values['id'],
            name=values['name'],
            note=values['note'],
            annotation=values['annotation'],
        )

        self.claim(building.qualified_id)
        self.buildings[building.qualified_id] = self.save(building)

    def import_room(self, entry):
        values = check_fields(
            entry,
            {'id': str, 'building': str, 'floor': str},
            {'name': str, 'note': str, 'annotation': str},
        )

        room = Room(
            building=resolve(self.buildings, values['building'], 'building'),
            code=values['id'],
            floor=values['floor'],
            name=values['name'],
            note=values['note'],
            annotation=values['annotation'],
        )

        self.claim(room.qualified_id)
        self.rooms[room.qualified_id] = self.save(room)

    def import_distributor(self, entry):
        values = check_fields(
            entry,
            {'id': str, 'room': str, 'kind': str},
            {'name': str, 'note': str, 'annotation': str},
        )

        self.add_component(
            values, DISTRIBUTOR_KINDS, parent_room=resolve(self.rooms, values['room'], 'room')
        )

    def import_outlet(self, entry):
        values = check_fields(
            entry,
            {'id': str, 'location': str, 'kind': str},
            {'name': str, 'note': str, 'annotation': str},
        )

        self.add_component(values, OUTLET_KINDS, **self.location(values['location']))

    def import_device(self, entry):
        values = check_fields(
            entry,
            {'id': str, 'location': str, 'kind': str},
            {'name': str, 'manufacturer': str, 'model': str, 'note': str, 'annotation': str},
        )

        self.add_component(
            values,
            DEVICE_KINDS,
            **self.location(values['location']),
            manufacturer=values['manufacturer'],
            model=values['model'],
        )

    def import_pathway(self, entry):
        values = check_fields(
            entry,
            {'id': str, 'kind': str, 'from_room': str, 'to_room': str},
            {'diameter_mm': int, 'note': str, 'annotation': str},
        )

        pathway = Pathway(
            from_room=resolve(self.rooms, values['from_room'], 'from_room'),
            to_room=resolve(self.rooms, values['to_room'], 'to_room'),
            kind=choice(PATHWAY_KINDS, values['kind'], 'kind'),
            name=values['id'],
            note=values['note'],
            annotation=values['annotation'],
            diameter=values['diameter_mm'],
        )

        self.claim(('pathway', pathway.name))
        self.pathways[pathway.name] = self.save(pathway)

    def import_cable(self, entry):
        values = check_fields(
            entry,
            {'type': str, 'source': dict, 'target': dict},
            {
                'id': str,
                'cross_section': str,
                'length_m': float,
                'path': list,
                'bundle': str,
                'conductors': str,
                'conductor_use': str,
                'installed': datetime.date,
                'note': str,
                'annotation': str,
            },
        )

        source, source_terminal = self.endpoint(values['source'], 'source')
        target, target_terminal = self.endpoint(values['target'], 'target')

        cable = Cable(
            source=source,
            source_terminal=source_terminal,
            target=target,
            target_terminal=target_terminal,
            kind=choice(CABLE_KINDS, values['type'], 'type'),
            name=values['id'],
            note=values['note'],
            annotation=values['annotation'],
            cross_section=values['cross_section'],
            length=values['length_m'],
            bundle=values['bundle'],
            conductors=values['conductors'],
            conductor_use=values['conductor_use'],
            installed=values['installed'],
        )

        path = values['path'] or []
        if not all(isinstance(name, str) for name in path):
            raise EntryError("path: expected a list of pathway ids")
        if len(set(path)) < len(path):
            raise EntryError("path: contains a pathway more than once")
        pathways = [resolve(self.pathways, name, 'path') for name in path]

        self.claim(cable_key(cable))
        self.save(cable)
        for pathway in pathways:
            self.save(PathSegment(cable=cable, pathway=pathway))
        self.cable_count += 1

    def run(self):
        """
        Imports all files. Raises a `CommandError` with all errors of the first
        file that has any, as the entries of later files refer to its entries
        and would mostly repeat its errors.
        """
        for filename, import_entry in [
            ('buildings.yaml', self.import_building),
            ('rooms.yaml', self.import_room),
            ('distributors.yaml', self.import_distributor),
            ('outlets.yaml', self.import_outlet),
            ('devices.yaml', self.import_device),
            ('conduits.yaml', self.import_pathway),
            ('cables.yaml', self.import_cable),
        ]:
            errors = []
            for line, entry in load_yaml(self.directory / filename):
                self.place = f'{filename}:{line}'
                try:
                    import_entry(entry)
                except EntryError as error:
                    ident = entry.get('id') if isinstance(entry, dict) else None
                    ident = f" (id={ident})" if ident else ""
                    errors.append(f"{self.place}{ident}: {error}")

            if errors:
                raise CommandError("\n".join(errors))


class Command(BaseCommand):
    help = "Imports a site from the YAML files of smart-home-kabeldoku."

    def add_arguments(self, parser):
        parser.add_argument(
            'directory', type=Path, help="The directory with the YAML files of the site."
        )

        parser.add_argument(
            '--name', help="The name of the site. Defaults to the name of the directory."
        )

    def handle(self, directory, name, **options):
        if not directory.is_dir():
            raise CommandError(f"Directory not found: {directory}")

        name = name or directory.resolve().name
        existing = list(Site.objects.filter(name__iexact=name))
        if len(existing) > 1:
            raise CommandError(f"There are several sites named {name!r}.")

        with transaction.atomic():
            # If the site exists, the YAML files are imported as a second site
            # of the same name, which is rolled back after the comparison.
            # This way, the comparison sees the data exactly as an import would
            # store it, after all checks.
            site = Site.objects.create(name=name)  # Names are not unique.
            importer = Importer(directory, site)
            importer.run()

            if not existing:
                self.stdout.write(
                    f"Imported the site {name!r}: {len(importer.buildings)} buildings, "
                    f"{len(importer.rooms)} rooms, {len(importer.components)} components, "
                    f"{len(importer.pathways)} pathways, {importer.cable_count} cables."
                )
                return

            old_records = site_records(existing[0])
            new_records = site_records(site)
            transaction.set_rollback(True)

        differences = compare(old_records, new_records)
        if not differences:
            self.stdout.write(f"The site {name!r} matches the YAML files.")
            return

        self.stdout.write(f"The site {name!r} differs from the YAML files:")
        for line in differences:
            self.stdout.write(line)

        added = len(new_records.keys() - old_records.keys())
        removed = len(old_records.keys() - new_records.keys())
        changed = sum(
            old_records[key] != new_records[key]
            for key in old_records.keys() & new_records.keys()
        )
        self.stdout.write(
            f"{added} new, {changed} changed, {removed} not in the YAML files. "
            f"The site was left unchanged."
        )
