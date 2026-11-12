"""ArcGIS Pro adapter for constructing raw candidate-level measurements."""

import csv
import json
import math
import re
import sys

import arcpy


def _unique_id(value, seen, label):
    if value is None or not str(value).strip() or str(value) in seen:
        raise ValueError(f"{label}: missing or duplicate ID {value!r}")
    seen.add(str(value))
    return str(value)


def _project(geometry, reference):
    if not geometry or geometry.firstPoint is None:
        raise ValueError("missing or empty geometry")
    if geometry.spatialReference.name == "Unknown":
        raise ValueError("unknown spatial reference")
    if geometry.spatialReference.exportToString() != reference.exportToString():
        if geometry.spatialReference.GCS.name != reference.GCS.name:
            raise ValueError("different geographic datums: transform inputs explicitly before analysis")
        geometry = geometry.projectAs(reference)
    return geometry


def _load_regions(path, id_field, reference):
    if arcpy.Describe(path).shapeType != "Polygon":
        raise ValueError("regions must be polygons")
    seen, result = set(), []
    with arcpy.da.SearchCursor(path, [id_field, "SHAPE@"]) as rows:
        for value, geometry in rows:
            result.append((_unique_id(value, seen, "regions"), _project(geometry, reference)))
    return result


def _load_facilities(spec, reference):
    desc = arcpy.Describe(spec["data"])
    allowed = {"Point", "Multipoint"} if spec["method"] == "count_within" else {"Point", "Multipoint", "Polygon"}
    if desc.shapeType not in allowed:
        raise ValueError(f"{spec['name']}: incompatible facility geometry")
    id_field = spec.get("deduplicate_by")
    fields = ([id_field] if id_field else []) + ["SHAPE@"]
    seen, geometries = {}, []
    with arcpy.da.SearchCursor(spec["data"], fields) as rows:
        for row in rows:
            geom = _project(row[-1], reference)
            if id_field:
                if row[0] is None or not str(row[0]).strip():
                    raise ValueError(f"{spec['name']}: blank facility ID")
                key = str(row[0])
                if key in seen:
                    if not geom.equals(seen[key]):
                        raise ValueError(f"{spec['name']}: duplicate facility ID with different geometry")
                    continue
                seen[key] = geom
            geometries.append(geom)
    return geometries


def _table(spec, id_field):
    seen, values = set(), {}
    with arcpy.da.SearchCursor(spec["data"], [spec.get("id_field", id_field), spec["value_field"]]) as rows:
        for candidate, value in rows:
            key = _unique_id(candidate, seen, spec["name"])
            if value is not None:
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError(f"{spec['name']}: non-finite value")
            values[key] = value
    return values


def build_arcpy_indicators(candidates, regions, specs, output_csv, id_field="candidate_id", region_field="region_id"):
    """Write a UTF-8 CSV without dropping planned candidates; distances are metres."""
    desc = arcpy.Describe(candidates)
    reference = desc.spatialReference
    if desc.shapeType != "Point" or reference.type != "Projected" or not math.isclose(reference.metersPerUnit, 1.0):
        raise ValueError("candidates must be point features in a projected metre-based CRS")
    region_geometries = _load_regions(regions, region_field, reference)
    seen, point_rows = set(), []
    with arcpy.da.SearchCursor(candidates, [id_field, "SHAPE@"]) as rows:
        for value, geometry in rows:
            candidate_id = _unique_id(value, seen, "candidates")
            geometry = _project(geometry, reference)
            matches = [region_id for region_id, polygon in region_geometries if not geometry.disjoint(polygon)]
            if len(matches) != 1:
                raise ValueError(f"candidate {candidate_id}: expected exactly one region; found {len(matches)}")
            point_rows.append(({id_field: candidate_id, region_field: matches[0]}, geometry))
    names = {id_field, region_field}
    for spec in specs:
        name, method = spec.get("name", ""), spec.get("method")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name in names or name + "__status" in names:
            raise ValueError(f"invalid or duplicated indicator name {name!r}")
        names.update((name, name + "__status"))
        if method not in {"count_within", "nearest", "table"}:
            raise ValueError(f"{name}: unsupported method")
        if method == "table":
            values = _table(spec, id_field)
        elif spec.get("coverage_known") is True:
            values = _load_facilities(spec, reference)
        else:
            values = None
        if method == "count_within" and values is not None:
            radius = spec.get("radius_m")
            if not isinstance(radius, (float, int)) or not math.isfinite(radius) or radius < 0:
                raise ValueError(f"{name}: radius_m must be finite and nonnegative")
        for record, point in point_rows:
            if method == "table":
                value = values.get(record[id_field])
                status = "missing_measurement" if value is None else "ok"
            elif values is None:
                value, status = None, "coverage_unknown"
            elif method == "count_within":
                value, status = sum(point.distanceTo(place) <= radius for place in values), "ok"
            elif not values:
                value, status = None, "no_facilities"
            else:
                value, status = min(point.distanceTo(place) for place in values), "ok"
            record[name], record[name + "__status"] = value, status
    fields = [id_field, region_field] + [item for spec in specs for item in (spec["name"], spec["name"] + "__status")]
    with open(output_csv, "x", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(record for record, _ in point_rows)
    return len(point_rows)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8-sig") as file:
        settings = json.load(file)
    print(build_arcpy_indicators(**settings))
