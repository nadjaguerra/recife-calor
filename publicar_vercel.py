"""Publish a prepared, public-data bundle using Vercel's authenticated REST API."""
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests


def api(method, path, **kwargs):
    response = requests.request(method, 'https://api.vercel.com' + path,
                                params={'teamId': os.environ['VERCEL_ORG_ID']},
                                headers={'Authorization': 'Bearer ' + os.environ['VERCEL_TOKEN'],
                                         **kwargs.pop('headers', {})}, timeout=90, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}


def files_to_publish(root):
    paths = [root / name for name in ['app.py', 'config.json', 'requirements.txt', 'vercel.json',
                                     'outputs/manifest.json', 'outputs/metrics.json']]
    for folder in ['web', 'public/static', 'data/processed', 'outputs/maps']:
        paths.extend(path for path in (root / folder).rglob('*') if path.is_file())
    paths.extend(root / 'src' / name for name in ['__init__.py', 'common.py', 'weather.py'])
    paths.extend((root / 'outputs').glob('bairros_*.csv'))
    paths.extend((root / 'outputs').glob('research*.json'))
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path.relative_to(root))
    return sorted(set(paths))


def upload(path, root):
    content = path.read_bytes()
    digest = hashlib.sha1(content).hexdigest()
    api('POST', '/v2/files', data=content,
        headers={'Content-Type': 'application/octet-stream', 'x-vercel-digest': digest,
                 'x-vercel-size': str(len(content))})
    return {'file': path.relative_to(root).as_posix(), 'sha': digest, 'size': len(content)}


def promote(project, deployment):
    api('POST', f'/v10/projects/{project}/promote/{deployment}', json={})


def verify_public(expected):
    base = 'https://recife-calor.vercel.app'
    for attempt in range(8):
        try:
            for route in ['/', '/static/research.js', '/maps/2019_temperature.png',
                          '/api/pixel?year=2019&lat=-8.05&lon=-34.94']:
                response = requests.get(base + route, timeout=45)
                response.raise_for_status()
            response = requests.get(base + '/api/manifest', timeout=45)
            response.raise_for_status()
            if response.json() != expected:
                raise ValueError('O manifesto público diverge do processado.')
            for route in ['/api/research-grid'] + [f"/api/research/{r['year']}" for r in expected['years']]:
                response = requests.get(base + route, timeout=45)
                response.raise_for_status()
                if response.json()['generated_at'] != expected['generated_at']:
                    raise ValueError('As análises públicas divergem da versão processada.')
            return
        except (requests.RequestException, ValueError, KeyError):
            if attempt == 7:
                raise
            time.sleep(5)


def publish(root):
    for name in ['VERCEL_TOKEN', 'VERCEL_ORG_ID', 'VERCEL_PROJECT_ID']:
        if not os.environ.get(name):
            raise ValueError(f'Configure {name} no GitHub Actions.')
    project = os.environ['VERCEL_PROJECT_ID']
    previous = api('GET', '/v4/aliases/recife-calor.vercel.app')['deploymentId']
    expected = json.loads((root / 'outputs/manifest.json').read_text(encoding='utf-8'))
    paths = files_to_publish(root)
    print(f'Enviando {len(paths)} arquivos públicos verificados.', flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(lambda path: upload(path, root), paths))
    deployment = api('POST', '/v13/deployments', json={
        'name': 'recife-calor', 'project': project, 'target': 'production',
        'autoAssignCustomDomains': False, 'files': files,
        'projectSettings': {'framework': 'flask'}})
    deployment_id = deployment['id']
    print(f'Build iniciado: {deployment_id}', flush=True)
    for _ in range(120):
        state = api('GET', f'/v13/deployments/{deployment_id}')['readyState']
        if state == 'READY':
            break
        if state in {'ERROR', 'CANCELED'}:
            raise RuntimeError(f'O build terminou em {state}.')
        time.sleep(5)
    else:
        raise TimeoutError('O build não concluiu em dez minutos.')
    promote(project, deployment_id)
    try:
        verify_public(expected)
    except Exception:
        promote(project, previous)
        raise
    print('Publicação e análises verificadas em https://recife-calor.vercel.app/', flush=True)


if __name__ == '__main__':
    publish(Path(sys.argv[1]).resolve())
