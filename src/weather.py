"""Latest measured air temperature at Recife airport; never a satellite value."""
import math
import threading
import time
from datetime import datetime, timezone
import requests

URL = 'https://aviationweather.gov/api/data/metar'
SOURCE = 'https://aviationweather.gov/data/metar/?id=SBRF'
CACHE_SECONDS = 300
STALE_SECONDS = 90 * 60
LOCK = threading.Lock()
CACHE = {'checked':0.0, 'data':None, 'error':False}


def parse_observation(records, now=None):
    now = now or datetime.now(timezone.utc)
    valid = []
    for record in records if isinstance(records,list) else []:
        if not isinstance(record,dict):
            continue
        try:
            if record.get('icaoId')!='SBRF' or isinstance(record.get('temp'),bool):
                continue
            temperature = float(record['temp'])
            observed = datetime.fromtimestamp(float(record['obsTime']),timezone.utc)
            age = (now-observed).total_seconds()
            if not math.isfinite(temperature) or not -20 <= temperature <= 60 or age < -300:
                continue
            valid.append((observed,temperature,record))
        except (KeyError,TypeError,ValueError,OverflowError,OSError):
            continue
    if not valid:
        raise ValueError('A fonte não retornou uma observação válida para SBRF.')
    observed,temperature,record = max(valid,key=lambda item:item[0])
    age = max(0,int((now-observed).total_seconds()))
    wind = record.get('wspd')
    wind = round(float(wind)*1.852,1) if isinstance(wind,(float,int)) and math.isfinite(wind) and wind>=0 else None
    descriptions = {'CAVOK':'Boa visibilidade', 'CLR':'Céu limpo','SKC':'Céu limpo',
                    'FEW':'Poucas nuvens','SCT':'Nuvens dispersas','BKN':'Muito nublado',
                    'OVC':'Céu encoberto','VV':'Visibilidade reduzida'}
    return {'temperature_c':temperature,'wind_kmh':wind,
            'condition':descriptions.get(record.get('cover'),'Observação meteorológica'),
            'observed_at':observed.isoformat(),'age_seconds':age,'stale':age>STALE_SECONDS,
            'station':'SBRF','station_name':'Aeroporto do Recife / Guararapes',
            'latitude':-8.126,'longitude':-34.923,
            'source':'METAR · Aviation Weather Center / NOAA','source_url':SOURCE,
            'kind':'observed_air_temperature','raw_report':record.get('rawOb',''),
            'refresh_seconds':CACHE_SECONDS}


def current_weather():
    """Cache a maximum of five minutes. Keep last known values explicitly stale on failure."""
    with LOCK:
        if time.monotonic()-CACHE['checked'] >= CACHE_SECONDS or CACHE['checked']==0:
            try:
                response = requests.get(URL,params={'ids':'SBRF','format':'json','hours':6},
                                        headers={'User-Agent':'RecifeCalor/1.0 local academic project'},
                                        timeout=(5,12))
                response.raise_for_status()
                data = parse_observation(response.json())
                data['fetched_at'] = datetime.now(timezone.utc).isoformat()
                CACHE.update(data=data,error=False,checked=time.monotonic())
            except (requests.RequestException,ValueError,TypeError):
                CACHE.update(error=True,checked=time.monotonic())
        if not CACHE['data']:
            return {'available':False,'error':'A observação atual está indisponível. Nova consulta automática em até 5 minutos.',
                    'source_url':SOURCE,'refresh_seconds':CACHE_SECONDS}
        result = {**CACHE['data'],'available':True,'connection_error':CACHE['error']}
        observed = datetime.fromisoformat(result['observed_at'])
        result['age_seconds'] = max(0,int((datetime.now(timezone.utc)-observed).total_seconds()))
        result['stale'] = result['age_seconds']>STALE_SECONDS or CACHE['error']
        return result
