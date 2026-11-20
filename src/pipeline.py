"""Real Landsat C2 L2 data -> QA-filtered composites -> spatial model -> maps."""
import calendar
import hashlib
import json
import logging
import math
import warnings
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin, array_bounds
from rasterio.warp import reproject, transform_bounds, transform_geom
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from PIL import Image
from .common import (ROOT, RAW, PROCESSED, OUTPUT, setup, config, write_json,
                     temperature_c, reflectance, normalized_difference, clear_land, block_reduce, pipeline_lock)

LOG = logging.getLogger('recife')
STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1'
BAIRROS = ('https://dados.recife.pe.gov.br/dataset/1702c764-ec7a-4ef0-9861-8acd0e40c819/'
           'resource/5c67ce14-1799-40c4-a37c-9daa04d1761c/download/bairros-do-recife.geojson')
FEATURES = ['ndvi', 'ndbi', 'ndwi', 'red', 'nir', 'swir']
CRS = 'EPSG:32725'
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'RecifeCalor/1.0 academic-local-project'
SESSION.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1,
    status_forcelist=[429,500,502,503,504], allowed_methods=['GET'])))
SIGNED = {}


def get_json(url, **kwargs):
    response = SESSION.get(url, timeout=(20, 120), **kwargs)
    response.raise_for_status()
    return response.json()


def validate_config(cfg):
    if not 2019 <= cfg['start_year'] <= cfg['end_year'] <= date.today().year:
        raise ValueError('Período inválido; use 2019 até o ano corrente.')
    if not cfg['months'] or any(m not in range(1, 13) for m in cfg['months']):
        raise ValueError('Meses devem estar entre 1 e 12.')
    if cfg['resolution_m'] < 120 or cfg['resolution_m'] % 30:
        raise ValueError('A resolução deve ser múltipla de 30 e pelo menos 120 m.')
    if cfg['scenes_per_year'] < 1 or cfg['max_attempts_per_year'] < cfg['scenes_per_year']:
        raise ValueError('Número de cenas/tentativas inválido.')


def geometry_grid(cfg):
    cached = RAW / 'bairros.geojson'
    if cached.exists():
        original = json.loads(cached.read_text(encoding='utf-8'))
    else:
        original = get_json(BAIRROS)
        write_json(cached, original)
    features = []
    for index, feature in enumerate(original['features'], 1):
        properties = feature['properties']
        name = properties.get('EBAIRRNOMEOF') or properties.get('EBAIRRNOME') or f'Bairro {index}'
        geom = shape(feature['geometry'])
        if not geom.is_valid:
            geom = geom.buffer(0)
        features.append({'type': 'Feature', 'geometry': mapping(geom),
                         'properties': {'id': index, 'name': name}})
    result = {'type': 'FeatureCollection', 'features': features}
    write_json(PROCESSED / 'bairros.geojson', result)
    city = unary_union([shape(f['geometry']) for f in features])
    if not (-35.2 < city.bounds[0] < -34.8 and -8.3 < city.bounds[1] < -7.8):
        raise ValueError('A malha não está em longitude/latitude do Recife.')
    projected = transform_geom('EPSG:4326', CRS, mapping(city))
    bounds = shape(projected).bounds
    res = cfg['resolution_m']
    left, bottom = [math.floor(v / res) * res for v in bounds[:2]]
    right, top = [math.ceil(v / res) * res for v in bounds[2:]]
    width, height = round((right-left)/res), round((top-bottom)/res)
    transform = from_origin(left, top, res, res)
    fine = from_origin(left, top, 30, 30)
    zones = rasterize([(transform_geom('EPSG:4326', CRS, f['geometry']), f['properties']['id'])
                       for f in features], out_shape=(height, width), transform=transform, dtype='uint16')
    fine_mask = rasterize([(projected, 1)], out_shape=(height*int(res/30), width*int(res/30)),
                          transform=fine, dtype='uint8').astype(bool)
    return result, {'transform': transform, 'fine_transform': fine, 'width': width, 'height': height,
                    'fine_mask': fine_mask, 'zones': zones, 'bbox': list(city.bounds),
                    'bounds': [[city.bounds[1], city.bounds[0]], [city.bounds[3], city.bounds[2]]]}


def search_year(year, cfg, bbox):
    end_date = min(date(year, 12, 31), date.fromisoformat(cfg['as_of']), date.today())
    if end_date < date(year, 1, 1):
        return []
    params = {'collections': 'landsat-c2-l2', 'bbox': ','.join(map(str, bbox)),
              'datetime': f'{year}-01-01T00:00:00Z/{end_date.isoformat()}T23:59:59Z', 'limit': 100}
    items, url = [], f'{STAC}/search'
    for page in range(30):
        payload = get_json(url, params=params)
        items.extend(payload['features'])
        next_link = next((x for x in payload.get('links', []) if x['rel'] == 'next'), None)
        if not next_link:
            break
        url, params = next_link['href'], None
    else:
        raise RuntimeError('Paginação STAC excedeu o limite; reduza a busca.')
    available = [item for item in items
                 if item['properties'].get('platform') in ('landsat-8', 'landsat-9')
                 and int(item['properties']['datetime'][5:7]) in cfg['months']
                 and item['properties'].get('landsat:correction') == 'L2SP'
                 and item['properties'].get('landsat:collection_category') == 'T1'
                 and 'lwir11' in item['assets']
                 and item['properties'].get('eo:cloud_cover', 100) <= cfg['max_cloud_cover']]
    available.sort(key=lambda item: (item['properties'].get('eo:cloud_cover', 100), item['id']))
    # Prefer scenes covering the entire municipality over edge-path scenes.
    city_box = shape({'type':'Polygon', 'coordinates':[[[bbox[0],bbox[1]], [bbox[2],bbox[1]],
                         [bbox[2],bbox[3]], [bbox[0],bbox[3]], [bbox[0],bbox[1]]]]})
    available.sort(key=lambda item: -round(shape(item['geometry']).intersection(city_box).area/city_box.area,3))
    # Adjacent WRS rows may repeat the same overpass. Count each date/platform once.
    seen, unique = set(), []
    for item in available:
        key = (item['properties']['platform'], item['properties']['datetime'][:10])
        if key not in seen:
            unique.append(item)
            seen.add(key)
    available = unique
    # Retain signed-token-free provenance only.
    write_json(RAW / f'catalog_{year}.json', {'search': params, 'items': available})
    return available


def read_band(item, name, grid):
    href = item['assets'][name]['href']
    from urllib.parse import urlsplit
    location = urlsplit(href)
    container = location.netloc + '/' + location.path.split('/')[1]
    if container not in SIGNED or time.monotonic()-SIGNED[container][0] > 1800:
        signed = get_json('https://planetarycomputer.microsoft.com/api/sas/v1/sign',
                          params={'href':href,'recife_time':datetime.now(timezone.utc).isoformat()})['href']
        SIGNED[container] = (time.monotonic(),urlsplit(signed).query)
    signed = href + '?' + SIGNED[container][1]
    destination = np.full(grid['fine_mask'].shape,-9999,dtype=np.int32)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_MAX_RETRY='3',
                      GDAL_HTTP_RETRY_DELAY='2', GDAL_HTTP_CONNECTTIMEOUT='30', GDAL_HTTP_TIMEOUT='120',
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif', VSI_CACHE=True):
        with rasterio.open(signed) as source:
            reproject(source=rasterio.band(source, 1), destination=destination,
                      src_transform=source.transform, src_crs=source.crs,
                      dst_transform=grid['fine_transform'], dst_crs=CRS,
                      src_nodata=source.nodata if name!='qa_radsat' else 65535,
                      dst_nodata=-9999, resampling=Resampling.nearest,
                      num_threads=2)
    return destination


def process_scene(item, grid, cfg, fingerprint):
    path = RAW / 'scenes' / f'{item["id"]}_{fingerprint}.npz'
    if path.exists():
        with np.load(path) as stored:
            return {key: stored[key] for key in stored.files}
    values = {'qa_pixel':read_band(item,'qa_pixel',grid)}
    names = ['qa_radsat','qa','lwir11','red','nir08','swir16','green']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda name:read_band(item,name,grid),names))
    values.update(zip(names,results))
    valid = clear_land(values['qa_pixel'], values['qa_radsat']) & grid['fine_mask']
    valid &= (values['qa'] >= 0) & (values['qa'] * 0.01 <= cfg['max_temperature_uncertainty_k'])
    valid &= (values['lwir11'] > 0)
    temperature = temperature_c(values['lwir11'])
    valid &= (temperature > -10) & (temperature < 70)
    bands = {}
    for name, asset in [('red','red'), ('nir','nir08'), ('swir','swir16'), ('green','green')]:
        bands[name] = reflectance(values[asset])
        valid &= (values[asset] > 0) & (bands[name] > 0) & (bands[name] <= 1)
    bands.update(temperature=temperature,
                 ndvi=normalized_difference(bands['nir'], bands['red']),
                 ndbi=normalized_difference(bands['swir'], bands['nir']),
                 ndwi=normalized_difference(bands['green'], bands['nir']))
    output = {}
    for name in ['temperature'] + FEATURES:
        array = bands[name].copy()
        array[~valid] = np.nan
        output[name] = block_reduce(array, int(cfg['resolution_m']/30))
        output[name][grid['zones'] == 0] = np.nan
    strict_temperature = temperature.copy()
    strict_temperature[~(valid & (values['qa'] * .01 <= min(4, cfg['max_temperature_uncertainty_k'])))] = np.nan
    output['temperature_strict'] = block_reduce(strict_temperature, int(cfg['resolution_m']/30))
    output['temperature_strict'][grid['zones'] == 0] = np.nan
    np.savez_compressed(path, **output)
    return output


def composite(scenes):
    result = {}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        for name in ['temperature', 'temperature_strict'] + FEATURES:
            result[name] = np.nanmedian(np.stack([s.get(name, np.full_like(s['temperature'], np.nan)) for s in scenes]), axis=0).astype('float32')
    result['temperature_first'] = scenes[0]['temperature'].copy()
    result['count'] = np.sum([np.isfinite(s['temperature']) for s in scenes], axis=0).astype('uint8')
    return result


def metric(y, prediction):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    return {'mae': float(mean_absolute_error(y, prediction)),
            'rmse': float(np.sqrt(mean_squared_error(y, prediction))), 'r2': float(r2_score(y, prediction))}


def train_model(composites, grid, cfg, progress):
    import joblib
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import GroupKFold
    from scipy.ndimage import distance_transform_edt
    tables = []
    for year, arrays in composites.items():
        mask = np.logical_and.reduce([np.isfinite(arrays[k]) for k in ['temperature'] + FEATURES])
        row, col = np.where(mask)
        table = pd.DataFrame({k: arrays[k][mask] for k in FEATURES})
        table['temperature'], table['year'] = arrays['temperature'][mask], year
        table['row'], table['col'] = row, col
        tables.append(table)
    frame = pd.concat(tables, ignore_index=True)
    if len(frame) < 500:
        raise RuntimeError('Menos de 500 células válidas: amplie meses ou cenas antes de treinar.')
    block = max(1, cfg['spatial_block_m'] // cfg['resolution_m'])
    groups = (frame.row // block) * (grid['width']//block + 1) + frame.col // block
    folds = min(5, groups.nunique())
    if folds < 3:
        raise RuntimeError('Poucos blocos espaciais para validação.')
    X, y = frame[FEATURES].values, frame.temperature.values
    oof = np.full(len(frame), np.nan)
    baseline = np.full(len(frame), np.nan)
    scores, importances = [], []
    for fold, (train, test) in enumerate(GroupKFold(folds).split(X, y, groups), 1):
        progress(f'Treinando validação espacial: bloco {fold}/{folds}')
        test_mask = np.zeros((grid['height'], grid['width']), dtype=bool)
        test_mask[frame.iloc[test].row, frame.iloc[test].col] = True
        distance = distance_transform_edt(~test_mask) * cfg['resolution_m']
        keep = distance[frame.iloc[train].row, frame.iloc[train].col] > cfg['validation_buffer_m']
        train = train[keep]
        if len(train) < 100:
            raise RuntimeError('Buffer espacial removeu amostras demais.')
        model = RandomForestRegressor(n_estimators=100, min_samples_leaf=5,
                                      max_features=0.8, n_jobs=-1, random_state=cfg['seed'])
        model.fit(X[train], y[train])
        oof[test] = model.predict(X[test])
        baseline[test] = np.mean(y[train])
        scores.append({'fold':fold, 'train':len(train), 'test':len(test), **metric(y[test], oof[test])})
        importances.append(model.feature_importances_)
    frame['predicted_oof'], frame['baseline_oof'] = oof, baseline
    frame.to_csv(OUTPUT / 'validation_predictions.csv', index=False)
    progress('Treinando modelo final e gerando mapas')
    final = RandomForestRegressor(n_estimators=160, min_samples_leaf=5, max_features=0.8,
                                  n_jobs=-1, random_state=cfg['seed'])
    final.fit(X, y)
    joblib.dump({'model':final, 'features':FEATURES, 'config':cfg}, OUTPUT / 'models' / 'random_forest.joblib')
    metrics = {'model':metric(y, oof), 'baseline':metric(y, baseline), 'folds':scores,
               'samples':len(frame), 'spatial_blocks':int(groups.nunique()),
               'block_m':cfg['spatial_block_m'], 'buffer_m':cfg['validation_buffer_m'],
               'importance':dict(zip(FEATURES, np.mean(importances, axis=0).tolist())),
               'by_year':{str(year):metric(group.temperature, group.predicted_oof)
                          for year, group in frame.groupby('year')},
               'scatter':frame.sample(min(1000,len(frame)), random_state=42)[['temperature','predicted_oof','ndvi']].round(3).values.tolist()}
    write_json(OUTPUT / 'metrics.json', metrics)
    for year, arrays in composites.items():
        mask = np.logical_and.reduce([np.isfinite(arrays[k]) for k in FEATURES])
        predicted = np.full(mask.shape, np.nan, dtype=np.float32)
        predicted[mask] = final.predict(np.column_stack([arrays[k][mask] for k in FEATURES]))
        arrays['predicted'] = predicted
        validation = np.full(mask.shape, np.nan, dtype=np.float32)
        samples = frame[frame.year == year]
        validation[samples.row.to_numpy(), samples.col.to_numpy()] = samples.predicted_oof - samples.temperature
        arrays['validation_error'] = validation
    return metrics


PALETTES = {
    'temperature': (20, 45, ['#243b83','#2a9eb3','#c5e7bb','#fff0a0','#f79950','#d73537','#79153b']),
    'predicted': (20, 45, ['#243b83','#2a9eb3','#c5e7bb','#fff0a0','#f79950','#d73537','#79153b']),
    'ndvi': (0, 1, ['#c9b490','#f2ebbb','#b6d381','#5eaa68','#12634b']),
    'anomaly': (-5, 5, ['#2166ac','#92c5de','#f7f7f7','#f4a582','#b2182b']),
    'count': (0, 8, ['#e1e8ef','#75b5b5','#075e66'])}


def render_png(array, name, path):
    low, high, colors = PALETTES[name]
    rgb = np.array([[int(c[i:i+2],16) for i in (1,3,5)] for c in colors])
    scale = np.clip((np.nan_to_num(array, nan=low)-low)/(high-low),0,1)
    position = scale * (len(rgb)-1)
    index = np.minimum(position.astype(int),len(rgb)-2)
    mix = (position-index)[...,None]
    rgba = np.zeros((*array.shape,4),dtype=np.uint8)
    rgba[...,:3] = (rgb[index]*(1-mix) + rgb[index+1]*mix).astype('uint8')
    rgba[...,3] = np.where(np.isfinite(array),230,0)
    Image.fromarray(rgba).save(path)


def export_year(year, arrays, grid, geometry, metadata):
    arrays['anomaly'] = arrays['temperature'] - np.nanmedian(arrays['temperature'])
    np.savez_compressed(PROCESSED / f'{year}.npz', **arrays)
    height, width = grid['height'], grid['width']
    utm_bounds = array_bounds(height, width, grid['transform'])
    west,south,east,north = transform_bounds(CRS,'EPSG:4326',*utm_bounds)
    geographic = from_origin(west,north,(east-west)/width,(north-south)/height)
    for name in ['temperature','ndvi','anomaly','predicted','count']:
        array = arrays[name].astype('float32')
        if name == 'count':
            array[(grid['zones']==0) | (array==0)] = np.nan
        tif = OUTPUT / 'maps' / f'{year}_{name}.tif'
        with rasterio.open(tif,'w',driver='GTiff',width=width,height=height,count=1,dtype='float32',
                           crs=CRS,transform=grid['transform'],nodata=np.nan,compress='deflate') as output:
            output.write(array,1)
        destination = np.full_like(array,np.nan)
        reproject(array,destination,src_transform=grid['transform'],src_crs=CRS,src_nodata=np.nan,
                  dst_transform=geographic,dst_crs='EPSG:4326',dst_nodata=np.nan,
                  resampling=Resampling.nearest)
        render_png(destination,name,OUTPUT / 'maps' / f'{year}_{name}.png')
    metadata['overlay_bounds'] = [[south,west],[north,east]]
    stats = []
    rows = []
    for feature in geometry['features']:
        zone = grid['zones']==feature['properties']['id']
        valid = zone & np.isfinite(arrays['temperature'])
        total = int(zone.sum())
        entry = {**feature['properties'], 'valid_cells':int(valid.sum()),
                 'coverage':round(float(valid.sum()/max(1,total)),4)}
        for name in ['temperature','ndvi','predicted','anomaly']:
            values = arrays[name][valid]
            entry[name] = round(float(np.mean(values)),3) if len(values) else None
        entry['maximum'] = round(float(np.max(arrays['temperature'][valid])),3) if valid.any() else None
        stats.append(entry)
        rows.append({'year':year,**entry})
    pd.DataFrame(rows).to_csv(OUTPUT / f'bairros_{year}.csv',index=False,encoding='utf-8-sig')
    valid = np.isfinite(arrays['temperature'])
    metadata.update(coverage=float(valid.sum()/max(1,(grid['zones']>0).sum())),
                    mean=float(np.nanmean(arrays['temperature'])),
                    maximum=float(np.nanmax(arrays['temperature'])),
                    mean_ndvi=float(np.nanmean(arrays['ndvi'])),
                    median=float(np.nanmedian(arrays['temperature'])),
                    valid_cells=int(valid.sum()), neighborhoods=stats)
    return metadata


def run_pipeline(progress=lambda text: LOG.info(text), years=None):
    with pipeline_lock():
        def report(text):
            write_json(RAW/'status.json',{'stage':text,'updated_at':datetime.now(timezone.utc).isoformat()})
            progress(text)
        try:
            return _run_pipeline(report,years)
        finally:
            write_json(RAW/'status.json',{'stage':'Processamento encerrado'})


def _run_pipeline(progress, years=None):
    setup()
    cfg = config()
    validate_config(cfg)
    if years and any(y not in range(cfg['start_year'],cfg['end_year']+1) for y in years):
        raise ValueError('Os anos solicitados devem estar dentro do período de config.json.')
    progress('Carregando limites oficiais dos bairros do Recife')
    geometry, grid = geometry_grid(cfg)
    signature = hashlib.sha256(json.dumps({**cfg,'bbox':grid['bbox'],'version':4},sort_keys=True).encode()).hexdigest()[:12]
    composites, records, failures = {}, {}, []
    for year in (years or range(cfg['start_year'],cfg['end_year']+1)):
        progress(f'Consultando imagens de {year}')
        candidates = search_year(year,cfg,grid['bbox'])
        scenes, used, attempted = [], [], []
        for item in candidates[:cfg['max_attempts_per_year']]:
            progress(f'{year}: processando cena {len(scenes)+1}/{cfg["scenes_per_year"]} — {item["id"]}')
            try:
                arrays = process_scene(item,grid,cfg,signature)
                coverage = float(np.isfinite(arrays['temperature']).sum()/max(1,(grid['zones']>0).sum()))
                attempted.append({'id':item['id'],'coverage':coverage})
                if coverage < cfg['min_scene_land_coverage']:
                    LOG.info('  Cena rejeitada: cobertura terrestre válida %.1f%%',coverage*100)
                    continue
                scenes.append(arrays)
                used.append({'id':item['id'], 'date':item['properties']['datetime'],
                             'platform':item['properties']['platform'], 'land_coverage':coverage,
                             'scene_cloud_cover':item['properties'].get('eo:cloud_cover'),
                             'catalog_url':f'{STAC}/collections/landsat-c2-l2/items/{item["id"]}'})
            except Exception as error:
                LOG.warning('Falha na cena %s: %s',item['id'],str(error).split('?')[0][:250])
                failures.append({'year':year,'scene':item['id'],'error':str(error).split('?')[0][:250]})
            if len(scenes)>=cfg['scenes_per_year']:
                break
        if scenes:
            composites[year] = composite(scenes)
            records[year] = {'year':year,'scenes':used,'attempted':attempted,
                             'partial':year==date.today().year, 'months':cfg['months']}
        else:
            failures.append({'year':year,'error':'Nenhuma cena com cobertura válida suficiente no período.'})
    if not composites:
        raise RuntimeError('Nenhum ano processado. Confira a internet e data/pipeline.log. Nenhum resultado foi inventado.')
    metrics = train_model(composites,grid,cfg,progress)
    summary = []
    for year, arrays in composites.items():
        progress(f'Exportando mapas e indicadores de {year}')
        summary.append(export_year(year,arrays,grid,geometry,records[year]))
    # Pixel values support clicks without depending on an external map service.
    write_json(PROCESSED / 'grid.json',{'crs':CRS,'transform':list(grid['transform'])[:6],
                                       'width':grid['width'],'height':grid['height']})
    write_json(OUTPUT / 'manifest.json',{
        'generated_at':datetime.now(timezone.utc).isoformat(),'config':cfg,'signature':signature,
        'bounds':grid['bounds'],'years':summary,'failures':failures,
        'sources':{'landsat':'https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature',
                   'catalog':STAC,'neighborhoods':BAIRROS},
        'metrics':{k:v for k,v in metrics.items() if k!='scatter'},
        'method':{'composite':'Mediana de até 3 cenas selecionadas por cobertura e nuvens nos meses configurados.',
                  'temperature':'Temperatura superficial diurna; não é temperatura do ar ou média anual.',
                  'anomaly':'Diferença em relação à mediana terrestre do município na composição selecionada; não é ilha de calor urbana-rural.',
                  'prediction':'Mapa ajustado pelo modelo final aos anos analisados; as métricas são calculadas apenas em blocos não usados no treino.',
                  'resolution':'Grade de 120 m; Landsat térmico tem resolução nativa aproximada de 100 m, distribuída a 30 m.',
                  'coverage':'Água e pixels sem qualidade suficiente ficam transparentes; cobertura usa toda a malha como denominador.'}})
    progress('Concluído: mapas e modelo disponíveis no site')
    from .research import build_research
    progress('Gerando análises espaciais e contexto demográfico')
    build_research()
    return {'years':list(composites),'failures':failures,'mae':metrics['model']['mae']}
