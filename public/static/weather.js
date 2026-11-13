'use strict';
(() => {
  const get = id => document.getElementById(id);
  const number = (value, decimals = 0) => Number.isFinite(value)
    ? value.toLocaleString('pt-BR', {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) : '—';
  const localTime = iso => new Date(iso).toLocaleString('pt-BR', {
    timeZone: 'America/Recife', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
  });
  let latest = null, loading = false, lastClick = 0;

  function render(data) {
    const card = get('weatherCard');
    const icon = card.querySelector(".weather-symbol");
    icon.textContent = "—";
    card.classList.toggle('is-unavailable', !data.available);
    if (!data.available) {
      get('weatherTemp').textContent = '—';
      get('weatherWind').textContent = '—';
      get('weatherBadge').lastChild.textContent = ' Indisponível';
      get('weatherCondition').textContent = 'Sem acesso à observação atual.';
      get('weatherTime').textContent = data.error || 'Nova tentativa automática em até 5 minutos.';
      card.classList.remove('is-stale');
      return;
    }
    const age = Math.max(0, (Date.now() - Date.parse(data.observed_at)) / 1000);
    const stale = data.stale || data.connection_error || age > 90 * 60;
    card.classList.toggle('is-stale', Boolean(stale));
    get('weatherTemp').textContent = number(data.temperature_c);
    get('weatherWind').textContent = data.wind_kmh == null ? '—' : `${number(data.wind_kmh)} km/h`;
    get('weatherCondition').textContent = data.condition;
    const hour = Number(new Date(data.observed_at).toLocaleTimeString('en-GB', {
      timeZone: 'America/Recife', hour: '2-digit', hourCycle: 'h23'
    }));
    icon.textContent = /nuv|encoberto/i.test(data.condition) ? '☁' : hour >= 18 || hour < 6 ? '☾' : '☀';
    get('weatherBadge').lastChild.textContent = data.connection_error ? ' Sem atualização' : stale ? ' Dado atrasado' : ' Observado';
    get('weatherTime').textContent = `Observação: ${localTime(data.observed_at)} · Fonte consultada: ${localTime(data.fetched_at)} (Recife).${stale ? ' Exibindo a última informação disponível.' : ''}`;
  }

  async function refresh(manual = false) {
    if (loading) return;
    if (manual && Date.now()-lastClick < 30000) return;
    if (manual) lastClick = Date.now();
    loading = true;
    get('refreshWeather').disabled = true;
    get('weatherCard').setAttribute('aria-busy', 'true');
    try {
      const response = await fetch('/api/weather', {signal: AbortSignal.timeout(23000)});
      const data = await response.json();
      if (!response.ok && data.available !== false) throw new Error('Resposta meteorológica inválida.');
      latest = data;
      render(data);
    } catch (error) {
      if (latest?.available) {
        latest = {...latest, connection_error:true};
        render(latest);
      } else {
        render({available:false,error:'Confira a conexão. Nova consulta automática em até 5 minutos.'});
      }
    } finally {
      loading = false;
      get('refreshWeather').disabled = false;
      get('weatherCard').setAttribute('aria-busy', 'false');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    get('refreshWeather').addEventListener('click', () => refresh(true));
    refresh();
    setInterval(refresh, 300000);
    setInterval(() => { if (latest) render(latest); }, 60000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && latest?.fetched_at && Date.now()-Date.parse(latest.fetched_at)>300000) refresh();
    });
  });
})();
