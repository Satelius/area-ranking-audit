import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
CENTERS = {name: 103.70 + index * 0.02 for index, name in enumerate('ABCDEFG')}
SCORES = {'A': 10, 'B': 9.5, 'C': 9, 'D': 8, 'E': 7, 'F': 6, 'G': 5}
COUNTS = {'A': 1, 'B': 10, 'C': 2, 'D': 2, 'E': 2, 'F': 2, 'G': 2}
ALTERNATIVE = {'A': 'Alpha', 'B': 'Beta', 'C': 'Alpha', 'D': 'Gamma', 'E': 'Delta', 'F': 'Epsilon', 'G': 'Zeta'}


def write_csv(name, rows):
    with (HERE / name).open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def polygon(x):
    return [[x - .004, 1.296], [x + .004, 1.296], [x + .004, 1.304], [x - .004, 1.304], [x - .004, 1.296]]


points = []
for region in CENTERS:
    for index in range(1, COUNTS[region] + 1):
        missing_1 = region == 'B' and index == 1
        missing_2 = region == 'B' and index == 2
        points.append({'point_id': f'{region}{index:02}', 'region': region, 'alternative_region': ALTERNATIVE[region],
                       'longitude': CENTERS[region] + ((index - 1) % 5 - 2) * .0004,
                       'latitude': 1.3 + ((index - 1) // 5) * .0004,
                       'indicator_1': '' if missing_1 else SCORES[region],
                       'indicator_2': '' if missing_2 else SCORES[region],
                       'indicator_1_status': 'missing' if missing_1 else 'valid',
                       'indicator_2_status': 'missing' if missing_2 else 'valid'})
write_csv('candidates.csv', points)
reference = [0, 0] + [5] * 17 + [10, 10]
write_csv('reference_sample.csv', [{'reference_id': f'R{i:02}', 'indicator_1': value, 'indicator_2': value} for i, value in enumerate(reference, 1)])
features = [{'type': 'Feature', 'properties': {'region': region}, 'geometry': {'type': 'Polygon', 'coordinates': [polygon(x)]}} for region, x in CENTERS.items()]
alternatives = []
for group in dict.fromkeys(ALTERNATIVE.values()):
    regions = [region for region in CENTERS if ALTERNATIVE[region] == group]
    alternatives.append({'type': 'Feature', 'properties': {'alternative_region': group}, 'geometry': {'type': 'MultiPolygon', 'coordinates': [[polygon(CENTERS[region])] for region in regions]}})
for name, items in [('regions.geojson', features), ('alternative_regions.geojson', alternatives)]:
    (HERE / name).write_text(json.dumps({'type': 'FeatureCollection', 'features': items}, indent=2), encoding='utf-8')
