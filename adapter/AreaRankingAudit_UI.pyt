"""Interactive ArcGIS Pro front end; preserves the original scoring engine."""
import csv
import json
import os
import sys
import tempfile
import arcpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'build'))
sys.path.insert(0, os.path.join(ROOT, 'core'))
import arcpy_indicators
import area_audit
from importlib.machinery import SourceFileLoader
legacy = SourceFileLoader('area_audit_legacy', os.path.join(os.path.dirname(__file__), 'AreaRankingAudit.pyt')).load_module()


def param(name, label, kind, required=True, direction='Input'):
    return arcpy.Parameter(name=name, displayName=label, datatype=kind,
                           parameterType='Required' if required else 'Optional', direction=direction)


def field(name, label, dependency):
    p = param(name, label, 'Field')
    p.parameterDependencies = [dependency]
    return p


def choice(name, label, values, default):
    p = param(name, label, 'GPString')
    p.filter.type = 'ValueList'
    p.filter.list = values
    p.value = default
    return p


def table(name, label, columns, filters=None, dependency=None, required=True):
    p = param(name, label, 'GPValueTable', required)
    p.columns = columns
    if dependency:
        p.parameterDependencies = [dependency]
    for index, values in (filters or {}).items():
        p.filters[index].type = 'ValueList'
        p.filters[index].list = values
    return p


def rows(p):
    return p.values or []


def text(v):
    s = '' if v is None else str(v).strip()
    return '' if s in ('-', '#') else s


def path(v):
    s = text(v)
    if not s:
        raise ValueError('Data source is required')
    return arcpy.Describe(s).catalogPath


class Arg:
    def __init__(self, value=None):
        self.value = value
        self.valueAsText = None if value is None else str(value)


class Toolbox:
    def __init__(self):
        self.label = 'Area Ranking Audit (interactive prototype)'
        self.alias = 'areaauditui'
        self.tools = [BuildIndicators, AuditAreaRankings]


NUMERIC_TYPES = {"SmallInteger", "Integer", "BigInteger", "Single", "Double"}
CHOOSE_FIELDS = "Choose numeric fields"
ALL_FIELDS = "Import all eligible numeric fields"


def measurement_columns(source, reserved_names):
    import re
    reserved = {n.casefold() for n in reserved_names if n}
    return [f.name for f in arcpy.ListFields(source)
            if f.type in NUMERIC_TYPES and not f.required
            and f.name.casefold() not in reserved
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", f.name)
            and not f.name.casefold().endswith("__status")]


def batch_measurements(p):
    source = p[7].valueAsText
    if not source:
        return []
    source_fields = {f.name for f in arcpy.ListFields(source)}
    join_field = p[8].valueAsText or p[2].valueAsText
    if join_field not in source_fields:
        raise ValueError("Select the candidate ID field in the measurement table.")
    available = measurement_columns(source, [join_field, p[2].valueAsText, p[3].valueAsText])
    selected = available if p[9].valueAsText == ALL_FIELDS else [text(v) for v in rows(p[10])]
    if not selected:
        raise ValueError("Choose measurement fields or select Import all eligible numeric fields.")
    invalid = set(selected) - set(available)
    if invalid:
        raise ValueError("Invalid measurement fields: " + ", ".join(sorted(invalid)))
    return [dict(data=source, name=n, method="table", id_field=join_field, value_field=n,
                 reason="Imported existing measurement") for n in selected]


def add_csv_to_current_map(output):
    try:
        project = arcpy.mp.ArcGISProject("CURRENT")
    except (OSError, RuntimeError, ValueError):
        arcpy.AddWarning("CSV saved. Automatic addition to Contents requires running inside ArcGIS Pro with a map open.")
        return
    current_map = project.activeMap
    if current_map is None:
        arcpy.AddWarning("CSV saved. No active map is available. Add the CSV to a map with Add Data.")
        return
    target = os.path.normcase(os.path.realpath(output))
    try:
        for existing in current_map.listTables():
            if os.path.normcase(os.path.realpath(existing.dataSource)) == target:
                arcpy.AddMessage("CSV is already in Contents: " + existing.name)
                return
        added = current_map.addDataFromPath(os.path.abspath(output))
        arcpy.AddMessage("Added to Contents > Standalone Tables: " + added.name)
    except (OSError, RuntimeError, ValueError) as error:
        arcpy.AddWarning("CSV saved, but it could not be added to Contents: " + str(error))


class BuildIndicators:
    def __init__(self):
        self.label = '1. Build Indicators - interactive'
        self.canRunInBackground = False
        self.description = 'Choose candidate points, region polygons and one or more indicator rows.'

    def getParameterInfo(self):
        candidates = param('candidates', 'Candidate points', 'GPFeatureLayer')
        regions = param('regions', 'Region polygons', 'GPFeatureLayer')
        pid = field('point_id', 'Candidate ID field', 'candidates')
        rid = field('region_id', 'Region ID field', 'regions')
        spatial = table('spatial', 'Spatial indicators: one row per indicator',
                        [[['GPFeatureLayer', 'GPTableView'], 'Source'], ['GPString', 'Indicator name'],
                         ['GPString', 'Method'], ['GPString', 'Radius in m (- if not used)'],
                         ['GPString', 'Deduplication ID field (- if none)'], ['GPString', 'Coverage known?'],
                         ['GPString', 'Reason (- if none)']],
                        {2: ['Count within radius', 'Nearest distance'], 5: ['Yes', 'No']}, required=False)
        existing = table('existing', 'Custom mappings (optional renaming or multiple tables)',
                         [['GPTableView', 'Source table'], ['GPString', 'Indicator name'],
                          ['GPString', 'Candidate ID field'], ['GPString', 'Value field'],
                          ['GPString', 'Reason (- if none)']], required=False)
        output = param('output', 'New output CSV', 'DEFile', direction='Output')
        existing.category = "Custom mappings"
        source = param('measurement_table', 'Measurement table', 'GPTableView', False)
        key = param('measurement_key', 'ID field in measurement table', 'Field', False)
        key.parameterDependencies = [source.name]
        mode = param('import_mode', 'Measurement fields to import', 'GPString', False)
        mode.filter.type = 'ValueList'
        mode.filter.list = [CHOOSE_FIELDS, ALL_FIELDS]
        mode.value = CHOOSE_FIELDS
        columns = arcpy.Parameter(name='measurement_columns', displayName='Numeric measurement fields',
                                  datatype='GPString', parameterType='Optional', direction='Input', multiValue=True)
        columns.filter.type = 'ValueList'
        return [candidates, regions, pid, rid, spatial, existing, output, source, key, mode, columns]

    def updateParameters(self, p):
        source = p[7].valueAsText
        for i in (8, 9, 10):
            p[i].enabled = bool(source)
        if not source or not arcpy.Exists(source):
            p[10].filter.list = []
            return
        candidate_key = p[2].valueAsText
        fields = {f.name for f in arcpy.Describe(source).fields}
        if p[8].valueAsText not in fields and candidate_key in fields:
            p[8].value = candidate_key
        available = measurement_columns(source, [p[8].valueAsText or candidate_key, candidate_key, p[3].valueAsText])
        p[10].filter.list = available
        p[10].enabled = p[9].valueAsText != ALL_FIELDS

    def updateMessages(self, p):
        if p[7].valueAsText and p[9].valueAsText == ALL_FIELDS and p[10].filter.list:
            p[9].setWarningMessage("Fields to import: " + ", ".join(p[10].filter.list))

    def execute(self, parameters, messages):
        p = parameters
        specs = []
        for src, name, method, radius, dedup, coverage, reason in rows(p[4]):
            spec = {'data': path(src), 'name': text(name), 'method': {'Count within radius': 'count_with', 'Nearest distance': 'nearest'}.get(text(method)),
                    'coverage_known': text(coverage) == 'Yes', 'reason': text(reason)}
            if spec['method'] == 'count_with':
                spec['method'] = 'count_within'
                if text(radius) == '':
                    raise ValueError(f'{name}: radius is required for count')
                spec['radius_m'] = float(radius)
            if text(dedup):
                spec['deduplicate_by'] = text(dedup)
            if spec['method'] is None or text(coverage) not in ('Yes', 'No'):
                raise ValueError('Select a method and coverage status for each spatial indicator')
            specs.append(spec)
        for src, name, id_field, value_field, reason in rows(p[5]):
            if not text(id_field) or not text(value_field):
                raise ValueError(f'{name}: source ID and value fields are required')
            specs.append({'data': path(src), 'name': text(name), 'method': 'table',
                          'id_field': text(id_field), 'value_field': text(value_field), 'reason': text(reason)})
        specs.extend(batch_measurements(p))
        names = [spec["name"].casefold() for spec in specs]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate indicator names across inputs. Select each field once or use custom mappings to rename.")
        if not specs:
            raise ValueError('Add at least one indicator row')
        output = p[6].valueAsText
        config_path = os.path.splitext(output)[0] + '_indicators.json'
        if os.path.exists(output) or os.path.exists(config_path):
            raise ValueError('Output CSV or indicator definitions already exist; choose a new path')
        count = arcpy_indicators.build_arcpy_indicators(p[0].valueAsText, p[1].valueAsText, specs, output,
                                                         id_field=p[2].valueAsText, region_field=p[3].valueAsText)
        with open(config_path, 'x', encoding='utf-8') as f:
            json.dump({'candidate_source': path(p[0].valueAsText), 'region_source': path(p[1].valueAsText),
                       'candidate_id_field': p[2].valueAsText, 'region_id_field': p[3].valueAsText,
                       'indicators': specs}, f, ensure_ascii=False, indent=2)
        arcpy.AddMessage(f'Wrote {count} planned points and definitions: {config_path}')
        add_csv_to_current_map(output)


class AuditAreaRankings:
    def __init__(self):
        self.label = '2. Audit Area Rankings - interactive'
        self.description = 'Select input fields and weights; reference parameters are saved with results.'
        self._candidate_suggested = None
        self._candidate_table = None

    def getParameterInfo(self):
        points = param('points', 'Indicator table (CSV)', 'GPTableView')
        pid = field('point_id', 'Candidate ID field', 'points')
        aid = field('area_id', 'Region ID field', 'points')
        criteria = table('criteria', 'Indicators and weights',
                         [['Field', 'Indicator field'], ['GPString', 'Direction'], ['GPDouble', 'Weight'],
                          ['GPString', 'Minimum (optional)'], ['GPString', 'Maximum (optional)']],
                         {1: ['Higher is better', 'Lower is better']}, 'points')
        mode = choice('reference_mode', 'Normalization reference',
                      ['Use complete input sample', 'Use separate reference CSV', 'Use saved reference JSON'],
                      'Use complete input sample')
        reference_csv = param('reference_csv', 'Separate reference CSV', 'DEFile', False)
        reference_json = param('reference_json', 'Saved reference JSON', 'DEFile', False)
        output = param('output_folder', 'Existing output parent folder', 'DEFolder')
        region = param('regions', 'Region polygons (optional)', 'GPFeatureLayer', False)
        region_id = param('region_field', 'Polygon region ID field', 'Field', False)
        region_id.parameterDependencies = ['regions']
        alt = param('alternative', 'Alternative sample CSV (optional)', 'DEFile', False)
        same = param('same_units', 'Alternative has same region IDs', 'GPBoolean', False)
        coverage = param('coverage', 'Minimum complete coverage', 'GPDouble'); coverage.value = .9
        feasible = param('feasible', 'Minimum feasible fraction', 'GPDouble'); feasible.value = .5
        low = param('low_n', 'Low-sample threshold', 'GPLong'); low.value = 3
        top = param('top_k', 'Number of top regions', 'GPLong'); top.value = 5
        sensitivity = param('sensitivity', 'Run weight sensitivity', 'GPBoolean', False); sensitivity.value = False
        draws = param('draws', 'Monte Carlo draws', 'GPLong'); draws.value = 1000
        result = param('result_folder', 'Created results folder', 'DEFolder', False, 'Output')
        audit_table = arcpy.Parameter(name="region_audit", displayName="Region audit table", datatype="DETable", parameterType="Derived", direction="Output")
        ranked_layer = arcpy.Parameter(name="ranked_regions", displayName="Ranked regions", datatype="GPFeatureLayer", parameterType="Derived", direction="Output")
        candidate_points = param('candidate_points', 'Candidate point layer for map (optional)', 'GPFeatureLayer', False)
        candidate_point_id = param('candidate_point_id', 'Candidate point ID field', 'Field', False)
        candidate_point_id.parameterDependencies = ['candidate_points']
        map_points = arcpy.Parameter(name="audited_points", displayName="Audited candidate points",
                                     datatype="GPFeatureLayer", parameterType="Derived", direction="Output")
        return [points, pid, aid, criteria, mode, reference_csv, reference_json, output, region, region_id,
                alt, same, coverage, feasible, low, top, sensitivity, draws, result, audit_table, ranked_layer,
                candidate_points, candidate_point_id, map_points]

    def updateParameters(self, p):
        mode = p[4].valueAsText
        p[5].enabled = mode == 'Use separate reference CSV'
        p[6].enabled = mode == 'Use saved reference JSON'
        p[17].enabled = bool(p[16].value)
        input_table = p[0].valueAsText
        if not input_table:
            return
        try:
            csv_path = path(input_table)
        except (OSError, ValueError, RuntimeError):
            return
        if not csv_path.lower().endswith(".csv"):
            return
        if csv_path == self._candidate_table:
            return
        current_candidate = p[21].valueAsText
        auto_selected = self._candidate_suggested and current_candidate == self._candidate_suggested
        if current_candidate and not auto_selected:
            self._candidate_table = csv_path
            return
        if auto_selected:
            p[21].value = None
            p[22].value = None
        self._candidate_table = csv_path
        self._candidate_suggested = None
        metadata_path = os.path.splitext(csv_path)[0] + "_indicators.json"
        try:
            with open(metadata_path, encoding="utf-8-sig") as file:
                metadata = json.load(file)
            source = metadata.get("candidate_source")
            field_name = metadata.get("candidate_id_field")
            if not source or not field_name or not arcpy.Exists(source):
                return
            desc = arcpy.Describe(source)
            if desc.shapeType != "Point" or field_name not in {f.name for f in desc.fields}:
                return
        except (OSError, ValueError, RuntimeError, AttributeError):
            return
        p[21].value = source
        p[22].value = field_name
        self._candidate_suggested = source

    def execute(self, p, messages):
        point_path = path(p[0].valueAsText)
        if not point_path.lower().endswith('.csv'):
            raise ValueError('Current prototype requires indicator input as a CSV file')
        criteria = []
        for name, direction, weight, minimum, maximum in rows(p[3]):
            d = {'name': text(name), 'direction': {'Higher is better': 'benefit', 'Lower is better': 'cost'}.get(text(direction)),
                 'weight': float(weight)}
            lower = text(minimum)
            upper = text(maximum)
            if lower:
                d['min'] = float(lower)
            if upper:
                d['max'] = float(upper)
            criteria.append(d)
        config = {'criteria': criteria, 'id_fields': {'point_id': p[1].valueAsText, 'area_id': p[2].valueAsText},
                  'settings': {'coverage': float(p[12].value), 'feasible': float(p[13].value),
                               'low_n': int(p[14].value), 'top_k': int(p[15].value)},
                  'sensitivity': {'enabled': bool(p[16].value), 'draws': int(p[17].value or 1000), 'seed': 42}}
        mode = p[4].valueAsText
        ref_csv = point_path if mode == 'Use complete input sample' else p[5].valueAsText if mode == 'Use separate reference CSV' else None
        ref_json = p[6].valueAsText if mode == 'Use saved reference JSON' else None
        if bool(p[21].valueAsText) != bool(p[22].valueAsText):
            raise ValueError("Supply both the candidate point layer and its ID field, or neither")
        if p[21].valueAsText:
            config['candidate_points'] = p[21].valueAsText
            config['candidate_point_id'] = p[22].valueAsText
        config['reference_mode'] = mode
        config['reference_source'] = ref_csv or ref_json
        with tempfile.TemporaryDirectory(prefix='area_audit_ui_') as d:
            config_path = os.path.join(d, 'config.json')
            with open(config_path, 'w', encoding='utf-8') as f: json.dump(config, f)
            args = [Arg(v) for v in [point_path, config_path, ref_csv, ref_json, p[7].valueAsText,
                                     p[8].valueAsText, p[9].valueAsText, p[10].valueAsText, bool(p[11].value), None]]
            legacy.AuditAreaRankings().execute(args, messages)
            output = args[9].value
            p[18].value = output
            p[19].value = os.path.join(output, "results.gdb", "region_audit")
            if p[8].valueAsText:
                layer_file = os.path.join(output, "Ranked regions.lyrx")
                p[20].value = arcpy.mp.LayerFile(layer_file).listLayers()[0]
            if p[21].valueAsText:
                p[23].value = arcpy.mp.LayerFile(os.path.join(output, "Audited points.lyrx")).listLayers()[0]
