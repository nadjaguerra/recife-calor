import json
import numpy as np
import pandas as pd
from src.common import OUTPUT, PROCESSED
from src.research import describe, normalized_name


def test_quantiles_ignore_missing_values_and_preserve_empty_groups():
    result = describe([10, np.nan, 20, 30])
    assert result['n'] == 3
    assert result['median'] == 20
    assert result['q25'] == 15
    assert describe([np.nan])['mean'] is None
    assert normalized_name('Poço') == normalized_name('Poço da Panela')


def test_exported_errors_are_signed_out_of_training_predictions():
    grid = json.loads((OUTPUT / 'research-grid.json').read_text(encoding='utf-8'))
    predictions = pd.read_csv(OUTPUT / 'validation_predictions.csv')
    for year in predictions.year.unique():
        data = json.loads((OUTPUT / f'research-{year}.json').read_text(encoding='utf-8'))
        lookup = {(int(r.row), int(r.col)): r.predicted_oof - r.temperature
                  for r in predictions[predictions.year == year].itertuples()}
        for cell, error in zip(grid['cells'], data['error']):
            expected = lookup.get((cell[0], cell[1]))
            if expected is None:
                assert error is None
            else:
                assert abs(error - expected) < .0011


def test_recurrence_counts_and_sensitivity_use_observed_cells():
    manifest = json.loads((OUTPUT / 'manifest.json').read_text(encoding='utf-8'))
    grid = json.loads((OUTPUT / 'research-grid.json').read_text(encoding='utf-8'))
    rows, cols = np.array(grid['cells'])[:, :2].astype(int).T
    hot, valid = np.zeros(len(rows), int), np.zeros(len(rows), int)
    for entry in manifest['years']:
        year = entry['year']
        with np.load(PROCESSED / f'{year}.npz') as arrays:
            valid += np.isfinite(arrays['temperature'][rows, cols])
            hot += np.isfinite(arrays['anomaly'][rows, cols]) & (arrays['anomaly'][rows, cols] >= 2)
            assert not (np.isfinite(arrays['temperature_strict']) & ~np.isfinite(arrays['temperature'])).any()
        data = json.loads((OUTPUT / f'research-{year}.json').read_text(encoding='utf-8'))
        assert len(data['neighborhoods']) == 94
        assert sum(x['population'] for x in data['neighborhoods']) == 1488920
        assert data['sensitivity']['strict']['n'] <= data['sensitivity']['standard']['n']
    assert grid['valid_years'] == valid.tolist()
    assert grid['hot_years'] == hot.tolist()
    for total, warm, percent in zip(valid, hot, grid['frequency']):
        assert percent is None if total < 3 else abs(percent - warm / total * 100) < .0011
