"""Local web app. Start with python app.py (binds only to loopback)."""
import argparse
import csv
import json
import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from functools import lru_cache
from math import floor, isfinite
from urllib.parse import urlparse
import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from pyproj import Transformer
from affine import Affine
from src.common import ROOT, OUTPUT, PROCESSED, RAW, setup, config, write_json, pipeline_is_running

app = Flask(__name__, static_folder='web', static_url_path='/static')
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
STATE = {'running':False, 'stage':'Pronto', 'error':None}


def read_json(path, fallback=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else fallback


@app.get('/')
def index():
    return send_from_directory(ROOT/'web','index.html')


@app.get('/api/status')
def status():
    if os.environ.get('VERCEL') == '1' or os.environ.get('RECIFE_PUBLIC') == '1':
        return jsonify(ready=(OUTPUT/'manifest.json').exists(), public=True)
    with LOCK:
        state = dict(STATE)
    if not state['running'] and pipeline_is_running():
        state.update(running=True,stage=read_json(RAW/'status.json',{}).get('stage','Processando dados pela linha de comando'))
    return jsonify({**state,'ready':(OUTPUT/'manifest.json').exists(), 'token':TOKEN, 'config':config()})


@app.get('/api/manifest')
def manifest():
    result = read_json(OUTPUT/'manifest.json')
    return (jsonify(result),200) if result else (jsonify(error='Execute a coleta para gerar os mapas.'),404)


@app.get('/api/neighborhoods')
def neighborhoods():
    result = read_json(PROCESSED/'bairros.geojson')
    return (jsonify(result),200) if result else (jsonify(error='Malha não carregada.'),404)


@app.get('/api/metrics')
def metrics():
    result = read_json(OUTPUT/'metrics.json')
    return (jsonify(result),200) if result else (jsonify(error='Modelo não treinado.'),404)


@lru_cache(maxsize=16)
def validation_points(year, predictions_version, grid_version):
    grid = read_json(PROCESSED/'grid.json')
    transform = Affine(*grid['transform'])
    cells = []
    with (OUTPUT/'validation_predictions.csv').open(encoding='utf-8-sig', newline='') as source:
        for sample in csv.DictReader(source):
            if sample['year'] != str(year):
                continue
            observed = float(sample['temperature'])
            predicted = float(sample['predicted_oof'])
            if isfinite(observed) and isfinite(predicted):
                x, y = transform * (int(sample['col']) + .5, int(sample['row']) + .5)
                cells.append((x, y, observed, predicted))
    if not cells:
        return []
    xs, ys, observed, predicted = zip(*cells)
    to_wgs84 = Transformer.from_crs(grid['crs'], 'EPSG:4326', always_xy=True)
    lons, lats = to_wgs84.transform(xs, ys)
    return [[round(lat, 6), round(lon, 6), round(obs, 2), round(pred, 2),
             round(abs(pred - obs), 2)]
            for lat, lon, obs, pred in zip(lats, lons, observed, predicted)]


@app.get('/api/validation/<int:year>')
def validation(year):
    try:
        points = validation_points(year, (OUTPUT/'validation_predictions.csv').stat().st_mtime_ns,
                                   (PROCESSED/'grid.json').stat().st_mtime_ns)
    except FileNotFoundError:
        return jsonify(error='Dados de validação indisponíveis.'), 404
    if not points:
        return jsonify(error='Este ano não tem células de validação.'), 404
    return jsonify(points=points)


@app.get('/api/weather')
def weather():
    from src.weather import current_weather
    result = current_weather()
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response,200 if result['available'] else 503


@app.get('/maps/<path:filename>')
def maps(filename):
    return send_from_directory(OUTPUT/'maps',filename,max_age=0)


@app.get('/download/<filename>')
def download(filename):
    if filename not in ['metrics.json','manifest.json','validation_predictions.csv'] and not (
            filename.startswith('bairros_') and filename.endswith('.csv')):
        return jsonify(error='Arquivo não permitido.'),404
    return send_from_directory(OUTPUT,filename,as_attachment=True)


@lru_cache(maxsize=16)
def load_arrays(year, modified):
    with np.load(PROCESSED/f'{year}.npz') as source:
        return {key:source[key] for key in source.files}


@app.get('/api/pixel')
def pixel():
    try:
        year = int(request.args['year'])
        lat,lon = float(request.args['lat']),float(request.args['lon'])
        if not (-8.4 <= lat <= -7.7 and -35.4 <= lon <= -34.7):
            return jsonify(error='Selecione um ponto no Recife.'),400
        path = PROCESSED/f'{year}.npz'
        if not path.exists():
            return jsonify(error='Ano indisponível.'),404
        grid = read_json(PROCESSED/'grid.json')
        x,y = Transformer.from_crs('EPSG:4326',grid['crs'],always_xy=True).transform(lon,lat)
        col, row = (~Affine(*grid['transform'])) * (x, y)
        row, col = floor(row), floor(col)
        if row<0 or col<0 or row>=grid['height'] or col>=grid['width']:
            return jsonify(values=None)
        arrays = load_arrays(year,path.stat().st_mtime_ns)
        values = {key:round(float(array[row,col]),3) if np.isfinite(array[row,col]) else None
                  for key,array in arrays.items()}
        return jsonify(values=values,lat=lat,lon=lon)
    except (KeyError,ValueError,OverflowError):
        return jsonify(error='Coordenadas/ano inválidos.'),400


def background_job():
    from src.pipeline import run_pipeline
    def progress(text):
        logging.getLogger('recife').info(text)
        with LOCK:
            STATE['stage'] = text
    try:
        result = run_pipeline(progress)
        load_arrays.cache_clear()
        with LOCK:
            STATE.update(stage='Concluído',error=None,result=result)
    except Exception as error:
        logging.getLogger('recife').exception('Pipeline interrompido')
        with LOCK:
            STATE.update(stage='Processamento interrompido',error=str(error).split('?')[0][:500])
    finally:
        with LOCK:
            STATE['running']=False


@app.post('/api/process')
def process():
    if os.environ.get('VERCEL') == '1' or os.environ.get('RECIFE_PUBLIC') == '1':
        return jsonify(error='Processamento disponível apenas na versão local.'), 403
    # A per-process token prevents other websites from triggering a costly job.
    if request.headers.get('X-Local-Token') != TOKEN:
        return jsonify(error='Atualize a página antes de iniciar.'),403
    with LOCK:
        if STATE['running']:
            return jsonify(error='Já existe um processamento em andamento.'),409
        STATE.update(running=True,stage='Iniciando',error=None)
    threading.Thread(target=background_job,daemon=True).start()
    return jsonify(started=True),202


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--process',action='store_true',help='Coleta e treina antes de iniciar o site')
    args = parser.parse_args()
    setup()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',
                        handlers=[logging.FileHandler(RAW/'pipeline.log',encoding='utf-8'),logging.StreamHandler()])
    if args.process:
        from src.pipeline import run_pipeline
        run_pipeline()
    print(f'\nRecife Calor: http://127.0.0.1:{args.port}\n',flush=True)
    app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False)


if __name__ == '__main__':
    main()
