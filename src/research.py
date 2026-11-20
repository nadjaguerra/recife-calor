"""Export spatial analyses from real, aligned cells and documented public context."""
import json
import gzip
import unicodedata
from datetime import datetime, timezone
import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from scipy.ndimage import distance_transform_edt
from shapely.geometry import shape, mapping
from .common import ROOT, OUTPUT, PROCESSED, write_json


def normalized_name(value):
    value = ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                    if unicodedata.category(c) != 'Mn')
    aliases = {'poco': 'poco da panela', 'cohab - ibura de cima': 'cohab',
               'sitio dos pintos - sao bras': 'sitio dos pintos', 'zumbi': 'zumbi'}
    return aliases.get(value, value)


def describe(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    if not len(values):
        return {'n': 0, 'min': None, 'p10': None, 'q25': None, 'median': None,
                'q75': None, 'p90': None, 'max': None, 'mean': None}
    result = dict(zip(['min', 'p10', 'q25', 'median', 'q75', 'p90', 'max'],
                      np.percentile(values, [0, 10, 25, 50, 75, 90, 100])))
    return {'n': len(values), **{k: round(float(v), 3) for k, v in result.items()},
            'mean': round(float(np.mean(values)), 3)}


def distance_grid(features, grid):
    geometries = []
    for feature in features:
        geom = shape(feature['geometry'])
        if not geom.is_valid:
            geom = geom.buffer(0)
        if not geom.is_empty:
            geometries.append((transform_geom('EPSG:4326', grid['crs'], mapping(geom)), 1))
    if not geometries:
        raise ValueError('A fonte de contexto não contém geometrias válidas.')
    mask = rasterize(geometries, out_shape=(grid['height'], grid['width']),
                     transform=Affine(*grid['transform']), all_touched=True, fill=0)
    if not mask.any():
        raise ValueError('A camada de contexto não intersecta a grade de Recife.')
    return distance_transform_edt(mask == 0) * abs(grid['transform'][0])


def finite_list(array):
    return [round(float(x), 3) if np.isfinite(x) else None for x in array]


def build_research():
    manifest = json.loads((OUTPUT / 'manifest.json').read_text(encoding='utf-8'))
    grid = json.loads((PROCESSED / 'grid.json').read_text(encoding='utf-8'))
    neighborhoods = json.loads((PROCESSED / 'bairros.geojson').read_text(encoding='utf-8'))
    context = ROOT / 'data/contexto'
    sources = json.loads((context / 'fontes.json').read_text(encoding='utf-8'))
    population = {normalized_name(x['name']): x['population']
                  for x in json.loads((context / 'populacao.json').read_text(encoding='utf-8'))}
    arrays = {}
    for entry in manifest['years']:
        with np.load(PROCESSED / f"{entry['year']}.npz") as stored:
            arrays[entry['year']] = {k: stored[k] for k in stored.files}
    temperature = np.stack([a['temperature'] for a in arrays.values()])
    valid = np.isfinite(temperature)
    n_years = valid.sum(axis=0)
    hot = np.stack([np.isfinite(a['anomaly']) & (a['anomaly'] >= 2)
                    for a in arrays.values()]).sum(axis=0)
    frequency = np.divide(hot * 100., n_years, out=np.full(n_years.shape, np.nan), where=n_years >= 3)
    transform = Affine(*grid['transform'])
    projected = [(transform_geom('EPSG:4326', grid['crs'], f['geometry']), f['properties']['id'])
                 for f in neighborhoods['features']]
    zones = rasterize(projected, out_shape=n_years.shape, transform=transform, fill=0)
    rows, cols = np.where((zones > 0) & (n_years > 0))
    to_geo = Transformer.from_crs(grid['crs'], 'EPSG:4326', always_xy=True)
    x, y = transform * (cols + .5, rows + .5)
    lon, lat = to_geo.transform(x, y)
    polygons = []
    for row, col in zip(rows, cols):
        corners = [transform * (col + dx, row + dy) for dx, dy in [(0, 0), (1, 0), (1, 1), (0, 1)]]
        polygons.append([[round(lon, 6), round(lat, 6)]
                         for lon, lat in [to_geo.transform(*p) for p in corners]])
    water = json.loads(gzip.decompress((context / 'agua.geojson.gz').read_bytes()).decode('utf-8-sig'))['features']
    parks = json.loads(gzip.decompress((context / 'parques.geojson.gz').read_bytes()).decode('utf-8-sig'))['features']
    conservation = json.loads(gzip.decompress((context / 'conservacao.geojson.gz').read_bytes()).decode('utf-8-sig'))['features']
    mangrove = [f for f in conservation if f['properties'].get('CDZONA_NOME') == 'UCN PARQUE DOS MANGUEZAIS']
    rivers = [f for f in water if 'RIO ' in str(f['properties'].get('NMRECHIDRIC', '')).upper()]
    contexts = {'parques': parks, 'rios': rivers, 'manguezal': mangrove}
    distances = {name: distance_grid(features, grid) for name, features in contexts.items()}
    write_json(OUTPUT / 'research-grid.json', {
        'generated_at': manifest['generated_at'], 'sources': sources,
        'cells': [[int(r), int(c), round(float(a), 6), round(float(b), 6), int(zones[r, c])]
                  for r, c, a, b in zip(rows, cols, lat, lon)],
        'polygons': polygons, 'valid_years': n_years[rows, cols].tolist(),
        'hot_years': hot[rows, cols].tolist(), 'frequency': finite_list(frequency[rows, cols]),
        'context': {key: {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': mapping(shape(f['geometry']).simplify(.00004)),
             'properties': {'name': f['properties'].get('NMNOMEOFIC') or f['properties'].get('NMNOME')
                            or f['properties'].get('NMRECHIDRIC') or f['properties'].get('CDZONA_NOME') or 'Área cadastrada'}}
             for f in features]} for key, features in contexts.items()}})
    for year, data in arrays.items():
        observed = data['temperature']
        mask = np.isfinite(observed)
        groups = []
        for feature in neighborhoods['features']:
            props = feature['properties']
            zone = zones == props['id']
            selected = zone & mask
            pop = population.get(normalized_name(props['name']))
            if pop is None:
                raise ValueError(f"Bairro sem correspondência censitária: {props['name']}")
            groups.append({'id': props['id'], 'name': props['name'], 'population': pop,
                           'coverage': round(float(selected.sum() / max(1, zone.sum())), 4),
                           'hot_share': round(float((selected & (data['anomaly'] >= 2)).sum()
                                                   / selected.sum()), 4) if selected.any() else None,
                           **describe(observed[selected])})
        bins = []
        for low, high in [(-1, 0), (0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]:
            selection = mask & (data['ndvi'] >= low) & (data['ndvi'] < high)
            bins.append({'label': f'{low:g} a {min(1, high):g}', **describe(observed[selection])})
        proximity = {}
        for name, distance in distances.items():
            proximity[name] = [{'label': label, **describe(observed[mask & (distance >= low) & (distance < high)])}
                               for label, low, high in [('Até 240 m', 0, 240.01),
                                                       ('240 a 600 m', 240.01, 600.01),
                                                       ('Acima de 600 m', 600.01, float('inf'))]]
        strict = data.get('temperature_strict')
        strict_mask = np.isfinite(strict) if strict is not None else np.zeros(mask.shape, bool)
        joint = mask & strict_mask
        sensitivity = {'strict_available': strict is not None, 'standard': describe(observed[mask]),
                       'strict': describe(strict[strict_mask]) if strict is not None else describe([]),
                       'paired_difference': describe((strict - observed)[joint]) if strict is not None else describe([]),
                       'single': describe(data.get('temperature_first', np.array([]))),
                       'strict_limit_k': min(4, manifest['config']['max_temperature_uncertainty_k'])}
        write_json(OUTPUT / f'research-{year}.json', {
            'year': year, 'generated_at': manifest['generated_at'],
            'temperature': finite_list(observed[rows, cols]),
            'ndvi': finite_list(data['ndvi'][rows, cols]),
            'count': data['count'][rows, cols].astype(int).tolist(),
            'error': finite_list(data.get('validation_error', np.full(mask.shape, np.nan))[rows, cols]),
            'neighborhoods': groups, 'ndvi_bins': bins, 'proximity': proximity,
            'sensitivity': sensitivity,
            'created_at': datetime.now(timezone.utc).isoformat()})
