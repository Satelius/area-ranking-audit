"""Deterministic point-to-area MCDA audit, independent of GIS software."""

import math
import random
from collections import Counter, defaultdict


def number(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    return result if math.isfinite(result) else None


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Reference sample has no valid observations")
    position = (len(ordered) - 1) * fraction
    left = math.floor(position)
    right = math.ceil(position)
    return ordered[left] + (position - left) * (ordered[right] - ordered[left])


def validate_criteria(criteria):
    if not criteria:
        raise ValueError("At least one criterion is required")
    names = [c['name'] for c in criteria]
    if any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names):
        raise ValueError("Criterion names must be nonempty and unique")
    weights = []
    for criterion in criteria:
        if criterion.get('direction') not in ('benefit', 'cost'):
            raise ValueError(f"Unknown direction for {criterion['name']}")
        weight = number(criterion.get('weight'))
        if weight is None or weight < 0:
            raise ValueError(f"Weight must be finite and non-negative: {criterion['name']}")
        lower, upper = number(criterion.get('min')), number(criterion.get('max'))
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"Constraint bounds are reversed: {criterion['name']}")
        weights.append(weight)
    if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise ValueError("Weights must sum to 1")


def fit_reference(reference_rows, criteria):
    validate_criteria(criteria)
    reference_rows = list(reference_rows)
    if not reference_rows:
        raise ValueError("Reference sample is empty")
    names = {c['name'] for c in criteria}
    if any(not names.issubset(row) for row in reference_rows):
        raise ValueError("Reference row lacks a criterion field")
    fitted = {}
    for criterion in criteria:
        name = criterion['name']
        values = [x for row in reference_rows if (x := number(row.get(name))) is not None]
        lo, hi = percentile(values, .05), percentile(values, .95)
        if lo >= hi:
            raise ValueError(f"P5 and P95 must differ for {name}")
        fitted[name] = {'p5': lo, 'p95': hi, 'valid_n': len(values)}
    return fitted


def audit(rows, criteria, reference, coverage=0.9, feasible=0.5, low_n=3, top_k=5, tiebreak=None):
    validate_criteria(criteria)
    rows = list(rows)
    if not rows:
        raise ValueError("No planned points provided")
    names = {c['name'] for c in criteria}
    if any(not names.issubset(row) for row in rows):
        raise ValueError("Planned point lacks a criterion field")
    if not (0 <= coverage <= 1 and 0 <= feasible <= 1 and low_n >= 1 and top_k >= 1):
        raise ValueError("Invalid area thresholds or top_k")
    for criterion in criteria:
        name = criterion['name']
        limits = reference.get(name, {})
        lo, hi = number(limits.get('p5')), number(limits.get('p95'))
        if lo is None or hi is None or lo >= hi:
            raise ValueError(f"Invalid frozen reference for {name}")
    tiebreak = tiebreak or []
    if any(name not in {c['name'] for c in criteria} for name in tiebreak):
        raise ValueError("Tie-breakers must name criteria")
    points, areas, groups, seen = [], [], defaultdict(list), set()
    for row in rows:
        point_id, area_id = row.get('point_id'), row.get('area_id')
        if point_id is None or not str(point_id).strip() or area_id is None or not str(area_id).strip():
            raise ValueError("Every planned point needs point_id and area_id")
        point_id, area_id = str(point_id), str(area_id)
        if point_id in seen:
            raise ValueError(f"Duplicate point_id: {point_id}")
        seen.add(point_id)
        values = {c['name']: number(row.get(c['name'])) for c in criteria}
        missing = [name for name, value in values.items() if value is None]
        complete = not missing
        violations = []
        normalized, contributions = {}, {}
        if complete:
            for c in criteria:
                name, value = c['name'], values[c['name']]
                low, high = number(c.get('min')), number(c.get('max'))
                if (low is not None and value < low) or (high is not None and value > high):
                    violations.append(name)
                lo, hi = number(reference[name]['p5']), number(reference[name]['p95'])
                z = (min(max(value, lo), hi) - lo) / (hi - lo)
                normalized[name] = 1 - z if c['direction'] == 'cost' else z
                contributions[name] = normalized[name] * float(c['weight'])
        point = {'point_id': point_id, 'area_id': area_id, 'values': values,
                 'complete': complete, 'feasible': complete and not violations,
                 'missing': missing, 'violations': violations, 'normalized': normalized,
                 'contributions': contributions, 'score': sum(contributions.values()) if complete else None}
        groups[area_id].append(point)
        points.append(point)
    for area_id, group in groups.items():
        planned = len(group)
        valid = [p for p in group if p['complete']]
        accepted = [p for p in group if p['feasible']]
        eligible = len(valid) / planned >= coverage and len(accepted) / planned >= feasible and bool(accepted)
        score = sum(p['score'] for p in accepted) / len(accepted) if accepted else None
        means = {c['name']: sum(p['contributions'][c['name']] for p in accepted) / len(accepted)
                 for c in criteria} if accepted else {}
        raw_means = {name: sum(p['values'][name] for p in accepted) / len(accepted)
                     for name in tiebreak} if accepted else {}
        areas.append({'area_id': area_id, 'planned': planned, 'complete': len(valid),
                      'feasible': len(accepted), 'coverage': len(valid) / planned,
                      'feasible_fraction': len(accepted) / planned, 'eligible': eligible,
                      'low_sample': len(accepted) < low_n, 'score': score, 'contributions': means,
                      'tiebreak_means': raw_means, 'rank': None, 'top': False})
    directions = {c['name']: c['direction'] for c in criteria}
    def sort_key(area):
        ties = [area['tiebreak_means'][name] * (1 if directions[name] == 'cost' else -1)
                for name in tiebreak]
        return (-area['score'], *ties, area['area_id'])
    ranked = sorted((a for a in areas if a['eligible']), key=sort_key)
    for rank, area in enumerate(ranked, 1):
        area['rank'], area['top'] = rank, rank <= top_k
    areas.sort(key=lambda a: a['area_id'])
    return {'points': points, 'areas': areas, 'reference': reference,
            'settings': {'coverage': coverage, 'feasible': feasible, 'low_n': low_n, 'top_k': top_k,
                         'tiebreak': tiebreak}}


def weight_sensitivity(rows, criteria, reference, draws=1000, seed=42, concentration=50,
                       oat_values=None, **options):
    validate_criteria(criteria)
    rows = list(rows)
    if draws < 1 or concentration <= 0:
        raise ValueError("draws and concentration must be positive")
    weights = [float(c['weight']) for c in criteria]
    if len(criteria) < 2:
        raise ValueError("Sensitivity requires at least two criteria")
    if any(w <= 0 for w in weights):
        raise ValueError("Sensitivity requires strictly positive baseline weights")
    oat_values = list(oat_values if oat_values is not None else [i / 20 for i in range(1, 13)])
    if any(number(v) is None or not 0 <= float(v) <= 1 for v in oat_values):
        raise ValueError("OAT weights must lie in [0, 1]")
    def run(vector):
        adjusted = [dict(c, weight=w) for c, w in zip(criteria, vector)]
        result = audit(rows, adjusted, reference, **options)
        ranked = sorted((a for a in result['areas'] if a['eligible']), key=lambda a: a['rank'])
        return ([a['area_id'] for a in ranked if a['top']],
                [{'area_id': a['area_id'], 'rank': a['rank'], 'score': a['score']} for a in ranked])
    baseline, baseline_ranks = run(weights)
    oat = []
    for i, criterion in enumerate(criteria):
        for value in oat_values:
            vector = [float(value) if j == i else w * (1 - float(value)) / (1 - weights[i])
                      for j, w in enumerate(weights)]
            top, ranks = run(vector)
            oat.append({'criterion': criterion['name'], 'weight': float(value),
                        'weights': vector, 'top_areas': top, 'ranks': ranks})
    rng = random.Random(seed)
    counts, simulations = Counter(), []
    for _ in range(draws):
        raw = [rng.gammavariate(concentration * w, 1.0) for w in weights]
        total = sum(raw)
        if total <= 0:
            raise ArithmeticError("Dirichlet draw underflowed; increase concentration")
        vector = [x / total for x in raw]
        top, ranks = run(vector)
        counts.update(top)
        simulations.append({'weights': vector, 'top_areas': top, 'ranks': ranks})
    return {'baseline_top': baseline, 'baseline_ranks': baseline_ranks, 'oat': oat, 'monte_carlo': simulations,
            'top_frequency': {k: counts[k] / draws for k in sorted(counts)},
            'seed': seed, 'draws': draws, 'concentration': concentration}


def compare_rankings(first, second, same_units=False):
    first_top = {a['area_id'] for a in first['areas'] if a['top']}
    second_top = {a['area_id'] for a in second['areas'] if a['top']}
    if same_units:
        first_set, second_set = first_top, second_top
        common_n = None
        basis = 'area_id'
    else:
        first_map = {p['point_id']: p['area_id'] for p in first['points']}
        second_map = {p['point_id']: p['area_id'] for p in second['points']}
        shared = first_map.keys() & second_map.keys()
        common_n = len(shared)
        if not shared:
            return {'status': 'unavailable_no_common_point_ids', 'basis': 'common_point_ids',
                    'common_point_count': 0, 'jaccard': None}
        first_set = {key for key in shared if first_map[key] in first_top}
        second_set = {key for key in shared if second_map[key] in second_top}
        basis = 'common_point_ids'
    union = first_set | second_set
    if not union:
        return {'status': 'unavailable_empty_union', 'basis': basis,
                'common_point_count': common_n, 'jaccard': None}
    return {'status': 'ok', 'basis': basis, 'common_point_count': common_n,
            'first_count': len(first_set), 'second_count': len(second_set),
            'intersection_count': len(first_set & second_set), 'union_count': len(union),
            'jaccard': len(first_set & second_set) / len(union)}
