#!/usr/bin/env python3
"""Audit the released grid, geographic scope, and independently sampled source means."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path)
    p.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'docs/data')
    args = p.parse_args()
    climate = json.loads((args.data / 'climate.json').read_text())
    manifest = json.loads((args.data / 'climate_manifest.json').read_text())
    states = json.loads((args.data / 'states.geojson').read_text())
    grid = climate['grid']
    n = grid['width'] * grid['height']
    assert len(grid['lat']) == grid['height']
    assert len(grid['lon']) == grid['width']
    assert all(a > b for a, b in zip(grid['lat'], grid['lat'][1:]))
    assert all(a < b for a, b in zip(grid['lon'], grid['lon'][1:]))
    assert len(manifest['inputs']) == 20
    assert [i['year'] for i in manifest['inputs']] == list(range(2006, 2026))
    assert all(i['month'] == 11 for i in manifest['inputs'])
    assert hashlib.sha256((args.data / 'climate.json').read_bytes()).hexdigest() == manifest['output']['sha256']
    expected = set('AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())
    assert len(states['features']) == 49
    assert {f['properties']['STUSPS'] for f in states['features']} == expected
    values = grid['values']
    for key, numbers in values.items():
        assert len(numbers) == n
        assert len(grid['validYears'][key]) == n
        for i, v in enumerate(numbers):
            assert v is None or (isinstance(v, (int, float)) and math.isfinite(v))
            assert grid['validYears'][key][i] == (0 if v is None else 20)
            if key == 'precip_mm' and v is not None:
                assert v >= 0
    usable = [i for i, v in enumerate(values['mean_temp_c']) if v is not None]
    for i in usable:
        assert values['min_temp_c'][i] <= values['mean_temp_c'][i] + .02
        assert values['mean_temp_c'][i] <= values['max_temp_c'][i] + .02
        assert 1 <= grid['sourceCellCount'][i] <= 4
    for numbers in grid.get('interannualStdDev', {}).values():
        assert len(numbers) == n
        assert all(v is None or (math.isfinite(v) and v >= 0) for v in numbers)

    samples = []
    if args.cache:
        import rasterio
        from rasterio.windows import Window
        rng = random.Random(20062025)
        indices = rng.sample(usable, 12)
        # Include a partial block to test coastal nodata handling as well.
        partial = [i for i in usable if grid['sourceCellCount'][i] < 4]
        if partial:
            indices.append(partial[len(partial) // 2])
        accumulator = {(i, k): [] for i in indices for k in values}
        for record in manifest['inputs']:
            path = args.cache / f"{record['year']}11.tif"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
            with rasterio.open(path) as source:
                for index in indices:
                    row, col = divmod(index, grid['width'])
                    for layer in climate['layers']:
                        band = source.descriptions.index(layer['band']) + 1
                        block = source.read(band, window=Window(col*2, row*2, 2, 2), masked=True)
                        numerator, denominator = 0.0, 0.0
                        for y in range(block.shape[0]):
                            north = source.transform.f + (row*2+y)*source.transform.e
                            south = north + source.transform.e
                            weight = math.sin(math.radians(north)) - math.sin(math.radians(south))
                            for x in range(block.shape[1]):
                                if bool(block.mask[y, x]) if hasattr(block.mask, 'shape') and block.mask.shape else bool(block.mask):
                                    continue
                                v = float(block[y, x])*source.scales[band-1]+source.offsets[band-1]
                                numerator += v*weight
                                denominator += weight
                        assert denominator > 0
                        accumulator[(index, layer['id'])].append(numerator/denominator)
        for index in indices:
            entry = {'index': index, 'lat': grid['lat'][index//grid['width']], 'lon': grid['lon'][index%grid['width']], 'checks': {}}
            for key in values:
                series = accumulator[(index, key)]
                expected_mean = sum(series)/20
                actual = values[key][index]
                assert abs(expected_mean-actual) <= .00501, (index, key, expected_mean, actual)
                entry['checks'][key] = {'recalculated': round(expected_mean, 6), 'published': actual}
                if key in grid.get('interannualStdDev', {}):
                    sd = math.sqrt(sum((v-expected_mean)**2 for v in series)/19)
                    assert abs(sd-grid['interannualStdDev'][key][index]) <= .00501
            samples.append(entry)
    report = {
        'checkedAt': datetime.now(timezone.utc).isoformat(),
        'status': 'passed',
        'datasetSHA256': manifest['output']['sha256'],
        'checks': ['49 correct geographic units', '20 distinct Novembers 2006–2025', 'Source manifest hash matches dataset', 'Grid shape and coordinate ordering', 'Finite numbers or null only', 'Complete-year counts match valid data', 'Temperature ordering', 'Nonnegative precipitation and interannual standard deviations'],
        'validOverviewCells': len(usable),
        'independentSourceSampleCount': len(samples),
        'sourceVerification': '20 source files independently re-read; sampled area-weighted means and standard deviations agree to published rounding' if samples else 'not performed; provide --cache',
        'samples': samples,
    }
    (args.data/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['samples','checks']}, indent=2))


if __name__ == '__main__':
    main()
