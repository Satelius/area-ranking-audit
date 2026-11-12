"""ArcGIS Pro toolbox for auditable ranking of candidate regions."""
import csv
import html
import json
import os
import sys
import uuid

import arcpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "build"))
import area_audit
import arcpy_indicators


def parameter(name, label, datatype, direction="Input", required=True):
    return arcpy.Parameter(displayName=label, name=name, datatype=datatype,
                           parameterType="Required" if required else "Optional", direction=direction)


def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


AREA_FIELDS = [
    ("ARA_plan", "LONG", "Planned points"), ("ARA_valid", "LONG", "Complete points"),
    ("ARA_feas", "LONG", "Feasible points"), ("ARA_cover", "DOUBLE", "Complete fraction"),
    ("ARA_fshare", "DOUBLE", "Feasible fraction"), ("ARA_elig", "SHORT", "Eligible"),
    ("ARA_low", "SHORT", "Low sample"), ("ARA_score", "DOUBLE", "Mean feasible-point score"),
    ("ARA_rank", "LONG", "Rank among eligible regions"), ("ARA_top", "SHORT", "In top K"),
    ("ARA_status", "TEXT", "Recommendation status")]


def area_attributes(a):
    if a is None:
        return [0, 0, 0, None, None, 0, None, None, None, 0, "No planned points"]
    if not a["eligible"]:
        status = "Ineligible"
    elif a["top"]:
        status = "Top K - low sample" if a["low_sample"] else "Top K"
    else:
        status = "Other eligible"
    return [a["planned"], a["complete"], a["feasible"], a["coverage"], a["feasible_fraction"],
            int(a["eligible"]), int(a["low_sample"]), a["score"], a["rank"], int(a["top"]), status]


def create_area_table(gdb, areas):
    dataset = arcpy.management.CreateTable(gdb, "region_audit")[0]
    arcpy.management.AddField(dataset, "area_id", "TEXT", field_length=max(64, max(len(a["area_id"]) for a in areas)))
    arcpy.management.AddFields(dataset, AREA_FIELDS)
    with arcpy.da.InsertCursor(dataset, ["area_id"] + [f[0] for f in AREA_FIELDS]) as cursor:
        for a in areas:
            cursor.insertRow([a["area_id"]] + area_attributes(a))
    return dataset


def make_region_layer(source, id_field, areas, gdb, top_k=5):
    if arcpy.Describe(source).shapeType != "Polygon":
        raise ValueError("Region boundaries must be polygon features")
    records = {a["area_id"]: a for a in areas}
    found = set()
    with arcpy.da.SearchCursor(source, [id_field]) as cursor:
        for (value,) in cursor:
            if value is None or not str(value).strip() or str(value) in found:
                raise ValueError("Polygon region IDs must be unique and nonempty")
            found.add(str(value))
    absent = records.keys() - found
    if absent:
        raise ValueError("Scored area IDs absent from polygon layer: " + ", ".join(sorted(absent)))
    fields = [f[0] for f in AREA_FIELDS]
    existing = {f.name.lower() for f in arcpy.ListFields(source)}
    if any(name.lower() in existing for name in fields):
        raise ValueError("Region input already contains audit fields")
    fc = arcpy.management.CopyFeatures(source, os.path.join(gdb, "ranked_regions"))[0]
    arcpy.management.AddFields(fc, AREA_FIELDS + [("ARA_band", "TEXT", "Ranking group")])
    top_end = int(top_k)
    max_rank = max((a["rank"] or 0 for a in areas), default=0)
    def band(a):
        if a is None:
            return "No planned points"
        if not a["eligible"]:
            return "Ineligible"
        if a["top"]:
            return "Top K - low sample" if a["low_sample"] else "Top K"
        rank = a["rank"]
        if rank <= top_end + 45:
            return f"{top_end + 1}-{min(top_end + 45, max_rank)}"
        if rank <= top_end + 95:
            return f"{top_end + 46}-{min(top_end + 95, max_rank)}"
        return f"{top_end + 96}-{max_rank}"
    with arcpy.da.UpdateCursor(fc, [id_field] + fields + ["ARA_band"]) as cursor:
        for row in cursor:
            a = records.get(str(row[0]))
            row[1:] = area_attributes(a) + [band(a)]
            cursor.updateRow(row)
    return save_region_layer(fc, os.path.join(os.path.dirname(gdb), "Ranked regions.lyrx"), id_field, top_k)


def save_region_layer(fc, layer_file, id_field=None, top_k=5):
    layer = arcpy.management.MakeFeatureLayer(fc, "Ranked regions " + uuid.uuid4().hex[:8])[0]
    arcpy.management.SaveToLayerFile(layer, layer_file, "RELATIVE")
    saved = arcpy.mp.LayerFile(layer_file)
    saved_layer = saved.listLayers()[0]
    sym = saved_layer.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = ["ARA_band" if "ARA_band" in {f.name for f in arcpy.ListFields(fc)} else "ARA_status"]
    colors = {"Top K": [0, 118, 101], "Top K - low sample": [252, 178, 65],
              "Other eligible": [166, 205, 218], "Ineligible": [141, 145, 153],
              "No planned points": [234, 234, 234],
              }
    if sym.renderer.fields == ["ARA_band"]:
        for (band_name,) in arcpy.da.SearchCursor(fc, ["ARA_band"]):
            if band_name and band_name not in colors:
                first_rank = int(band_name.split("-", 1)[0])
                colors[band_name] = ([94, 160, 184] if first_rank <= top_k + 1 else
                                     [149, 197, 211] if first_rank <= top_k + 46 else
                                     [202, 224, 231])
    for group in sym.renderer.groups:
        for item in group.items:
            category = item.values[0][0]
            item.symbol.color = {"RGB": colors[category] + [100]}
            item.symbol.outlineWidth = 0.35
            item.symbol.outlineColor = {"RGB": [145, 149, 155, 85]}
    saved_layer.symbology = sym
    if id_field:
        names = {f.name.lower(): f.name for f in arcpy.ListFields(fc)}
        label_field = names.get("area_name", id_field)
        if saved_layer.supports("SHOWLABELS"):
            label_class = saved_layer.listLabelClasses()[0]
            label_class.expression = f'Text($feature.ARA_rank, "0") + "  " + $feature["{label_field}"]'
            label_class.SQLQuery = "ARA_top = 1"
            saved_layer.showLabels = True
    saved.save()
    return layer_file



def save_audited_points(source, id_field, points, output, gdb):
    if arcpy.Describe(source).shapeType != "Point":
        raise ValueError("Candidate points must be point features")
    existing = {f.name.lower() for f in arcpy.ListFields(source)}
    names = ["ARA_valid", "ARA_feas", "ARA_score", "ARA_point"]
    if any(name.lower() in existing for name in names):
        raise ValueError("Candidate point input already contains audit fields")
    records = {p["point_id"]: p for p in points}
    found = set()
    source_sr = arcpy.Describe(source).spatialReference
    fc = arcpy.management.CreateFeatureclass(gdb, "audited_points", "POINT", spatial_reference=source_sr)[0]
    arcpy.management.AddField(fc, "ARA_ID", "TEXT", field_length=max(64, max(len(k) for k in records)))
    arcpy.management.AddFields(fc, [("ARA_valid", "SHORT"), ("ARA_feas", "SHORT"), ("ARA_score", "DOUBLE"),
                                    ("ARA_point", "TEXT")])
    with arcpy.da.SearchCursor(source, [id_field, "SHAPE@"]) as reader, arcpy.da.InsertCursor(
            fc, ["ARA_ID", "SHAPE@", "ARA_valid", "ARA_feas", "ARA_score", "ARA_point"]) as writer:
        for key, geom in reader:
            if key is None or not str(key).strip():
                raise ValueError("Candidate point IDs must not be empty")
            key = str(key)
            if key in found:
                raise ValueError(f"Duplicate candidate point ID: {key}")
            found.add(key)
            if key not in records:
                continue
            p = records[key]
            status = "Incomplete measurements" if not p["complete"] else "Feasible" if p["feasible"] else "Constraint failed"
            writer.insertRow([key, geom, int(p["complete"]), int(p["feasible"]), p["score"], status])
    absent = records.keys() - found
    if absent:
        raise ValueError(f"Candidate point layer is missing {len(absent)} planned point IDs")
    view = arcpy.management.MakeFeatureLayer(fc, "Audited candidate points")[0]
    layerfile = os.path.join(output, "Audited points.lyrx")
    arcpy.management.SaveToLayerFile(view, layerfile, "RELATIVE")
    saved = arcpy.mp.LayerFile(layerfile)
    layer = saved.listLayers()[0]
    sym = layer.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = ["ARA_point"]
    colors = {"Feasible": [34, 55, 88], "Incomplete measurements": [188, 46, 68], "Constraint failed": [229, 159, 0]}
    for group in sym.renderer.groups:
        for item in group.items:
            item.symbol.color = {"RGB": colors[item.values[0][0]] + [100]}
            item.symbol.size = 3.5 if item.values[0][0] == "Feasible" else 5.5
    layer.symbology = sym
    layer.minThreshold = 60000
    saved.save()
    return layerfile

def render_report(areas, sensitivity, settings):
    rows = []
    for a in sorted(areas, key=lambda x: (x['rank'] is None, x['rank'] or 0, x['area_id'])):
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in
                    (a['area_id'], a['rank'] or '—', a['planned'], a['complete'], a['feasible'],
                     f"{a['coverage']:.1%}", 'yes' if a['low_sample'] else 'no',
                     f"{a['score']:.4f}" if a['score'] is not None else '—')) + "</tr>")
    details = []
    for a in sorted((x for x in areas if x['top']), key=lambda x:x['rank']):
        contributions = ', '.join(f'{k}: {v:.4f}' for k, v in a['contributions'].items())
        details.append('<li>' + html.escape(a['area_id']) + ': ' + html.escape(contributions) + '</li>')
    freq = ''
    if sensitivity is not None:
        baseline = set(sensitivity['baseline_top'])
        changed = [o for o in sensitivity['oat'] if set(o['top_areas']) != baseline]
        freq = '<h2>Weight sensitivity</h2><p>Monte Carlo top-K frequencies: ' + html.escape(json.dumps(sensitivity['top_frequency'])) + '</p><p>OAT scenarios with a different top-K set: ' + str(len(changed)) + ' of ' + str(len(sensitivity['oat'])) + '. See sensitivity.json for each weight and list.</p><p>Frequencies are conditional on the selected weight distribution, not probabilities of real-world suitability.</p>'
    return "<!doctype html><html><head><meta charset='utf-8'><title>Area Ranking Audit</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 16px;color:#19314d}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ccd7e2;text-align:left}th{background:#eef4fa}</style></head><body><h1>Area Ranking Audit</h1><p>All planned points are retained in each region’s denominator. Ranks are conditional on the inputs and assumptions.</p><p>Settings: " + html.escape(json.dumps(settings)) + "</p><table><thead><tr><th>Area</th><th>Rank</th><th>Planned</th><th>Complete</th><th>Feasible</th><th>Coverage</th><th>Low sample</th><th>Score</th></tr></thead><tbody>" + ''.join(rows) + "</tbody></table><h2>Mean indicator contributions in top areas</h2><p>Contributions use feasible points and sum to each area's score.</p><ul>" + ''.join(details) + "</ul>" + freq + "</body></html>"


class Toolbox:
    def __init__(self):
        self.label = "Area Ranking Audit (prototype)"
        self.alias = "areaaudit"
        self.tools = [BuildIndicators, AuditAreaRankings]


class BuildIndicators:
    def __init__(self):
        self.label = "1. Build Indicators (prototype)"
        self.description = "Build point-level indicators from candidate and facility data. Projected metre CRS required."

    def getParameterInfo(self):
        return [parameter('candidates', 'Candidate points', 'GPFeatureLayer'),
                parameter('regions', 'Region polygons', 'GPFeatureLayer'),
                parameter('point_id', 'Candidate ID field', 'GPString'),
                parameter('region_id', 'Region ID field', 'GPString'),
                parameter('specs', 'Indicator definitions JSON file', 'DEFile'),
                parameter('output', 'New output CSV', 'DEFile', 'Output')]

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        candidate, region, point_id, region_id, config, output = [p.valueAsText for p in parameters]
        if os.path.exists(output):
            raise ValueError('Output CSV already exists; choose a new path')
        count = arcpy_indicators.build_arcpy_indicators(candidate, region, read_json(config)['indicators'], output,
                                                        id_field=point_id, region_field=region_id)
        arcpy.AddMessage(f'Wrote {count} planned points to {output}.')


class AuditAreaRankings:
    def __init__(self):
        self.label = "2. Audit Area Rankings (prototype)"
        self.description = "Retain planned-point denominators, rank eligible areas, and evaluate weight sensitivity."

    def getParameterInfo(self):
        return [parameter('points', 'Indicator CSV (point_id and area_id)', 'DEFile'),
                parameter('criteria', 'Criteria and settings JSON', 'DEFile'),
                parameter('reference_csv', 'Reference sample CSV (unless frozen JSON supplied)', 'DEFile', required=False),
                parameter('reference_json', 'Frozen reference JSON (optional)', 'DEFile', required=False),
                parameter('output_folder', 'Existing output parent folder', 'DEFolder'),
                parameter('regions', 'Optional region polygons', 'GPFeatureLayer', required=False),
                parameter('region_field', 'Region polygon ID field', 'GPString', required=False),
                parameter('alternative', 'Optional alternative sample CSV', 'DEFile', required=False),
                parameter('same_units', 'Alternative uses same area IDs', 'GPBoolean', required=False),
                parameter('result_folder', 'Created results folder', 'DEFolder', 'Output', required=False)]

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        points_path, config_path, reference_csv, reference_json, parent, regions, region_field = [p.valueAsText for p in parameters[:7]]
        alternative = parameters[7].valueAsText
        same_units = bool(parameters[8].value)
        if bool(reference_csv) == bool(reference_json):
            raise ValueError('Supply exactly one reference CSV or frozen reference JSON')
        if bool(regions) != bool(region_field):
            raise ValueError('Supply both region polygons and region ID field, or neither')
        config = read_json(config_path)
        criteria = config['criteria']
        settings = config.get('settings', {})
        allowed = {'coverage', 'feasible', 'low_n', 'top_k', 'tiebreak'}
        if set(settings) - allowed:
            raise ValueError('Unknown audit settings: ' + ', '.join(set(settings) - allowed))
        fields = config.get('id_fields', {})
        point_field = fields.get('point_id', 'point_id')
        area_field = fields.get('area_id', 'area_id')
        def canonical_rows(path):
            values = read_csv(path)
            for row in values:
                if point_field not in row or area_field not in row:
                    raise ValueError('Point and area ID fields are required in indicator CSV')
                row['point_id'], row['area_id'] = row[point_field], row[area_field]
            return values
        rows = canonical_rows(points_path)
        if not rows:
            raise ValueError('Input CSV contains no planned points')
        reference = read_json(reference_json) if reference_json else area_audit.fit_reference(read_csv(reference_csv), criteria)
        result = area_audit.audit(rows, criteria, reference, **settings)
        options = dict(config.get('sensitivity', {}))
        options.pop('enabled', False)
        sensitivity = area_audit.weight_sensitivity(rows, criteria, reference, **options, **settings) if config.get('sensitivity', {}).get('enabled', False) else None
        alternative_result = area_audit.audit(canonical_rows(alternative), criteria, reference, **settings) if alternative else None
        comparison = area_audit.compare_rankings(result, alternative_result, same_units=same_units) if alternative_result else None
        output = os.path.join(parent, 'area_audit_' + uuid.uuid4().hex[:10])
        os.mkdir(output)
        write_json(os.path.join(output, 'reference.json'), reference)
        write_json(os.path.join(output, 'run_configuration.json'), config)
        write_json(os.path.join(output, 'audit.json'), result)
        if sensitivity is not None:
            write_json(os.path.join(output, 'sensitivity.json'), sensitivity)
        if comparison is not None:
            write_json(os.path.join(output, 'alternative_audit.json'), alternative_result)
            write_json(os.path.join(output, 'comparison.json'), comparison)
        fields = ['area_id', 'planned', 'complete', 'feasible', 'coverage', 'feasible_fraction', 'eligible', 'low_sample', 'score', 'rank', 'top']
        write_csv(os.path.join(output, 'area_scores.csv'), [{k: a[k] for k in fields} for a in result['areas']], fields)
        point_fields = ['point_id', 'area_id', 'complete', 'feasible', 'missing', 'violations', 'score']
        indicator_fields = [prefix + c['name'] for c in criteria for prefix in ('value_', 'normalized_', 'contribution_')]
        point_rows = []
        for p in result['points']:
            row = {k: (';'.join(p[k]) if k in ('missing', 'violations') else p[k]) for k in point_fields}
            for c in criteria:
                name = c['name']
                row.update({'value_' + name:p['values'].get(name), 'normalized_' + name:p['normalized'].get(name),
                            'contribution_' + name:p['contributions'].get(name)})
            point_rows.append(row)
        point_fields += indicator_fields
        write_csv(os.path.join(output, 'point_scores.csv'), point_rows, point_fields)
        gdb = arcpy.management.CreateFileGDB(output, "results.gdb")[0]
        table = create_area_table(gdb, result["areas"])
        arcpy.AddMessage("ArcGIS ranking table: " + table)
        if regions:
            layer_file = make_region_layer(regions, region_field, result["areas"], gdb, result["settings"]["top_k"])
            arcpy.AddMessage("Ranked regions: " + layer_file)
        if config.get("candidate_points"):
            point_layer = save_audited_points(config["candidate_points"], config["candidate_point_id"],
                                              result["points"], output, gdb)
            arcpy.AddMessage("Audited candidate points: " + point_layer)
        with open(os.path.join(output, 'report.html'), 'x', encoding='utf-8') as f:
            report = render_report(result['areas'], sensitivity, result['settings'])
            if comparison is not None:
                report = report.replace('</body>', '<h2>Alternative comparison</h2><p>' + html.escape(json.dumps(comparison)) + '</p></body>')
            f.write(report)
        parameters[9].value = output
        arcpy.AddMessage('Results: ' + output)
