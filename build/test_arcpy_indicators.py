import csv
import os
import tempfile
import unittest

import arcpy
from arcpy_indicators import build_arcpy_indicators


class ArcPyMeasurements(unittest.TestCase):
    def test_metrics_and_boundary_guard(self):
        with tempfile.TemporaryDirectory(prefix="area_audit_", ignore_cleanup_errors=True) as root:
            gdb = str(arcpy.management.CreateFileGDB(root, "data.gdb")[0])
            sr = arcpy.SpatialReference(3414)
            def create(name, geometry, field):
                path = str(arcpy.management.CreateFeatureclass(gdb, name, geometry, spatial_reference=sr)[0])
                arcpy.management.AddField(path, field, "TEXT")
                return path
            candidates = create("candidates", "POINT", "candidate_id")
            regions = create("regions", "POLYGON", "region_id")
            shops = create("shops", "POINT", "site_id")
            park = create("park", "POLYGON", "park_id")
            polygon = lambda x1, x2: arcpy.Polygon(arcpy.Array([arcpy.Point(x1,-10), arcpy.Point(x1,10), arcpy.Point(x2,10), arcpy.Point(x2,-10), arcpy.Point(x1,-10)]), sr)
            with arcpy.da.InsertCursor(candidates, ["candidate_id", "SHAPE@XY"]) as rows:
                rows.insertRow(("a", (0, 0)))
                rows.insertRow(("b", (5, 0)))
            with arcpy.da.InsertCursor(regions, ["region_id", "SHAPE@"]) as rows:
                rows.insertRow(("R", polygon(-10, 10)))
            with arcpy.da.InsertCursor(shops, ["site_id", "SHAPE@XY"]) as rows:
                rows.insertRow(("1", (0, 0)))
                rows.insertRow(("1", (0, 0)))
                rows.insertRow(("2", (3, 0)))
            with arcpy.da.InsertCursor(park, ["park_id", "SHAPE@"]) as rows:
                rows.insertRow(("P", polygon(-1, 1)))
            table = str(arcpy.management.CreateTable(gdb, "measurement")[0])
            arcpy.management.AddField(table, "candidate_id", "TEXT")
            arcpy.management.AddField(table, "distance", "DOUBLE")
            with arcpy.da.InsertCursor(table, ["candidate_id", "distance"]) as rows:
                rows.insertRow(("a", 42))
            output = os.path.join(root, "output.csv")
            specs = [
                {"name": "shops", "method": "count_within", "data": shops, "radius_m": 3, "coverage_known": True, "deduplicate_by": "site_id"},
                {"name": "park", "method": "nearest", "data": park, "coverage_known": True},
                {"name": "road", "method": "table", "data": table, "value_field": "distance"},
                {"name": "unknown", "method": "nearest", "coverage_known": False},
            ]
            self.assertEqual(build_arcpy_indicators(candidates, regions, specs, output), 2)
            with open(output, encoding="utf-8-sig", newline="") as f:
                records = list(csv.DictReader(f))
            self.assertEqual([int(r["shops"]) for r in records], [2, 1])
            self.assertEqual([float(r["park"]) for r in records], [0.0, 4.0])
            self.assertEqual(records[1]["road__status"], "missing_measurement")
            self.assertEqual(records[0]["unknown__status"], "coverage_unknown")
            overlap = create("overlap", "POLYGON", "region_id")
            with arcpy.da.InsertCursor(overlap, ["region_id", "SHAPE@"]) as rows:
                rows.insertRow(("R", polygon(-10, 0)))
                rows.insertRow(("S", polygon(0, 10)))
            with self.assertRaisesRegex(ValueError, "exactly one region"):
                build_arcpy_indicators(candidates, overlap, [], os.path.join(root, "overlap.csv"))


if __name__ == "__main__":
    unittest.main()
