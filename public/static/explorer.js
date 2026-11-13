const explorer = (() => {
  const names = new Map();
  const highlights = [];
  let showMapSummary = false;
  const normalize = name => name.normalize('NFD').replace(/\p{Diacritic}/gu, '').trim().toLowerCase();
  const scenes = data => data.scenes.map(scene => new Date(scene.date)
    .toLocaleDateString('pt-BR', {timeZone: 'UTC'})).join(', ');
  const stats = (data, id) => data.neighborhoods.find(row => String(row.id) === id);
  const measure = (value, digits, unit = '') => Number.isFinite(value) ? fmt(value, digits) + unit : '—';

  function renderBairros() {
    if (!manifest || !names.size) return;
    const data = record($('year').value);
    const first = $('bairroFirst').value;
    const second = $('bairroSecond').value;
    if (showMapSummary) {
      const row = stats(data, first);
      const coverage = row?.coverage;
      $('bairroMapName').textContent = names.get(first);
      $('bairroMapPeriod').textContent = `${data.year}${data.partial ? ' · ano parcial' : ''}`;
      $('bairroMapTemperature').textContent = measure(row?.temperature, 1, ' °C');
      $('bairroMapNdvi').textContent = measure(row?.ndvi, 2);
      $('bairroMapCoverage').textContent = measure(Number.isFinite(coverage) ? coverage * 100 : null, 1, '%');
      const quality = !Number.isFinite(row?.temperature) ? 'Sem temperatura válida neste período.'
        : Number.isFinite(coverage) && coverage < .5 ? 'Menos de metade do bairro tem dados válidos neste período.' : '';
      $('bairroMapQuality').textContent = quality;
      $('bairroMapQuality').hidden = !quality;
      $('bairroMapSummary').hidden = false;
    }
    $('bairroPeriod').textContent = `${data.year} · Cenas de ${scenes(data)}${data.partial ? ' · ano parcial' : ''}`;
    const ids = [first, second].filter(Boolean);
    const rows = ids.map(id => stats(data, id));
    const fields = [
      ['Temperatura superficial', 'temperature', 1, ' °C', 1],
      ['Vegetação (NDVI)', 'ndvi', 2, '', 1],
      ['Cobertura válida', 'coverage', 1, '%', 100]
    ];
    const showDifference = ids.length === 2 && first !== second;
    $('bairroComparison').innerHTML = '<table class="bairro-table"><thead><tr><th scope="col">Indicador</th>'
      + ids.map(id => `<th scope="col">${esc(names.get(id))}</th>`).join('')
      + (showDifference ? '<th scope="col">Diferença<br>2º − 1º</th>' : '')
      + '</tr></thead><tbody>' + fields.map(([label, key, digits, unit, scale]) => {
        const values = rows.map(row => row?.[key]);
        const difference = values.every(Number.isFinite) ? (values[1] - values[0]) * scale : null;
        return `<tr><th scope="row">${label}</th>`
          + values.map(value => `<td>${measure(Number.isFinite(value) ? value * scale : null, digits, unit)}</td>`).join('')
          + (showDifference ? `<td>${measure(difference, digits, key === 'coverage' ? ' p.p.' : unit)}</td>` : '') + '</tr>';
      }).join('') + '</tbody></table>'
      + (rows.some(row => !Number.isFinite(row?.temperature)) ? '<p>— indica dado indisponível no período.</p>' : '')
      + (rows.some(row => row?.coverage < .5) ? '<p>Compare com cuidado. Há bairro com menos de 50% de cobertura válida.</p>' : '')
      + (first === second ? '<p>Escolha dois bairros diferentes para calcular a diferença.</p>' : '');
    drawHistory(first);
    for (const [index, map] of maps.entries()) {
      highlights[index]?.remove();
      const features = geo.features.filter(feature => ids.includes(String(feature.properties.id)));
      highlights[index] = L.geoJSON(features, {
        interactive: false,
        style: feature => ({color: String(feature.properties.id) === first ? '#a21e17' : '#f5a623',
          weight: 3, fill: false})
      }).addTo(map);
    }
  }

  function drawHistory(id) {
    const years = manifest.years;
    const values = years.map(data => stats(data, id)?.temperature);
    const valid = values.filter(Number.isFinite);
    if (!valid.length) {
      $('bairroTimeline').textContent = 'Sem temperaturas válidas para este bairro.';
    } else {
      const min = Math.floor(Math.min(...valid)) - 1;
      const max = Math.ceil(Math.max(...valid)) + 1;
      const x = index => 44 + index / Math.max(1, years.length - 1) * 375;
      const y = value => 177 - (value - min) / (max - min) * 137;
      const ticks = [...new Set([min, Math.round((min + max) / 2), max])];
      let markup = ticks.map(tick => `<line x1="42" x2="425" y1="${y(tick)}" y2="${y(tick)}" stroke="#e5d2c6"/><text x="34" y="${y(tick) + 3}" text-anchor="end" font-size="11">${tick}</text>`).join('');
      years.forEach((data, index) => {
        const value = values[index];
        markup += `<text x="${x(index)}" y="204" text-anchor="middle" font-size="12">${data.year}${data.partial ? '*' : ''}</text>`;
        if (!Number.isFinite(value)) return;
        if (Number.isFinite(values[index - 1]) && data.year === years[index - 1].year + 1) {
          markup += `<line x1="${x(index - 1)}" y1="${y(values[index - 1])}" x2="${x(index)}" y2="${y(value)}" stroke="#a93020" stroke-width="2"/>`;
        }
        markup += `<circle cx="${x(index)}" cy="${y(value)}" r="5" fill="#a93020"><title>${data.year} · ${fmt(value)} °C · ${scenes(data)} · ${fmt(stats(data, id).coverage * 100)}% de cobertura</title></circle>`;
      });
      $('bairroTimeline').innerHTML = svgFrame(markup, 'Ano · * parcial', '°C');
      $('bairroTimeline').firstElementChild.setAttribute('role', 'img');
      $('bairroTimeline').firstElementChild.setAttribute('aria-label', `Histórico de temperatura superficial de ${names.get(id)}`);
    }
    historyDetail();
  }

  function historyDetail() {
    const data = record($('bairroHistoryYear').value);
    if (!data) return;
    const row = stats(data, $('bairroFirst').value);
    const coverage = Number.isFinite(row?.coverage) ? measure(row.coverage * 100, 1, '%') : '—';
    $('bairroHistoryDetail').textContent = `${data.year}${data.partial ? ' · ano parcial' : ''} · ${measure(row?.temperature, 1, ' °C')} · Cobertura válida do bairro: ${coverage}. Cenas de ${scenes(data)}.`;
  }

  function locate(ids, scroll = false) {
    const features = geo.features.filter(feature => ids.includes(String(feature.properties.id)));
    if (!features.length) return;
    maps[0].fitBounds(L.geoJSON(features).getBounds(), {padding: [36, 36], maxZoom: 15});
    if (scroll) $('explorar').scrollIntoView({block: 'start'});
  }

  function mapState() {
    const params = new URLSearchParams();
    params.set('ano', $('year').value);
    params.set('camada', currentLayer);
    params.set('visualizacao', $('view').value);
    if ($('bairroFirst').value) params.set('bairro', $('bairroFirst').value);
    if ($('bairroSecond').value) params.set('bairro2', $('bairroSecond').value);
    if ($('compare').checked) params.set('ano2', $('compareYear').value);
    return params;
  }

  async function share() {
    const url = new URL(location.href);
    url.search = mapState().toString();
    url.hash = 'explorar';
    $('sharePanel').hidden = false;
    $('shareUrl').value = url.href;
    try {
      await navigator.clipboard.writeText(url.href);
      toast('Link do mapa copiado.');
    } catch {
      $('shareUrl').focus();
      $('shareUrl').select();
      toast('Copie o endereço selecionado.');
    }
  }

  function load() {
    const first = $('bairroFirst').value;
    const second = $('bairroSecond').value;
    names.clear();
    for (const feature of geo.features) {
      const {id, name} = feature.properties;
      names.set(String(id), bairroDisplayName(name));
    }
    const options = [...names].sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'));
    const selectOptions = options.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('');
    $('bairroOptions').innerHTML = options.map(([, name]) => `<option value="${esc(name)}"></option>`).join('');
    $('bairroFirst').innerHTML = selectOptions;
    $('bairroSecond').innerHTML = '<option value="">Escolha outro bairro</option>' + selectOptions;
    $('bairroHistoryYear').innerHTML = $('year').innerHTML;
    $('bairroSearch').querySelectorAll('input, button').forEach(el => { el.disabled = !options.length; });
    $('bairros').hidden = !options.length;
    $('shareMap').disabled = false;

    const params = new URLSearchParams(location.search);
    const initial = !$('bairroFirst').dataset.loaded;
    const choose = (key, previous) => initial && params.has(key) ? params.get(key) : previous;
    const chosenFirst = choose('bairro', first);
    const chosenSecond = choose('bairro2', second);
    if (names.has(chosenFirst)) $('bairroFirst').value = chosenFirst;
    else if (options.length) $('bairroFirst').value = options.find(([, name]) => name === 'Poço da Panela')?.[0] ?? options[0][0];
    if (names.has(chosenSecond)) $('bairroSecond').value = chosenSecond;
    $('bairroFirst').dataset.loaded = 'true';
    if (initial) {
      if (record(params.get('ano'))) $('year').value = params.get('ano');
      if (['pixels', 'neighborhoods'].includes(params.get('visualizacao'))) $('view').value = params.get('visualizacao');
      const key = params.get('camada');
      if (Object.hasOwn(layers, key)) {
        currentLayer = key;
        document.querySelectorAll('input[name=layer]').forEach(el => { el.checked = el.value === key; });
      }
      if (record(params.get('ano2'))) {
        $('compareYear').value = params.get('ano2');
        $('compare').checked = true;
        $('compare').dispatchEvent(new Event('change'));
      }
      if (names.has(params.get('bairro'))) {
        showMapSummary = true;
        locate([chosenFirst, chosenSecond]);
      }
    }
    $('bairroHistoryYear').value = $('year').value;
  }

  function update() {
    $('sharePanel').hidden = true;
    renderBairros();
  }

  document.addEventListener('DOMContentLoaded', () => {
    function searchBairro(exactOnly = false) {
      const query = normalize($('bairroQuery').value);
      const items = [...names];
      const exact = items.find(([, name]) => normalize(name) === query);
      if (exactOnly && !exact) return;
      const matches = exact ? [exact] : items.filter(([, name]) => query && normalize(name).includes(query));
      if (matches.length !== 1) {
        $('bairroSearchStatus').textContent = matches.length ? 'Escolha um bairro da lista.' : 'Bairro não encontrado.';
        return;
      }
      const [id, name] = matches[0];
      $('bairroFirst').value = id;
      $('bairroQuery').value = name;
      $('bairroSearchStatus').textContent = '';
      showMapSummary = true;
      locate([id]);
      update();
    }
    $('bairroQuery').addEventListener('input', () => searchBairro(true));
    $('bairroSearch').addEventListener('submit', event => {
      event.preventDefault();
      searchBairro();
    });
    $('bairroFirst').addEventListener('change', () => {
      showMapSummary = true;
      $('bairroQuery').value = names.get($('bairroFirst').value) ?? '';
      $('bairroSearchStatus').textContent = '';
      update();
    });
    $('bairroSecond').addEventListener('change', update);
    $('year').addEventListener('change', () => { $('bairroHistoryYear').value = $('year').value; historyDetail(); });
    $('bairroHistoryYear').addEventListener('change', historyDetail);
    $('showBairros').addEventListener('click', () => locate([$('bairroFirst').value, $('bairroSecond').value], true));
    $('shareMap').addEventListener('click', share);
  });
  return {load, update};
})();
