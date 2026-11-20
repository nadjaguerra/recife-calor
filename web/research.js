'use strict';
(() => {
  const el = id => document.getElementById(id);
  const available = value => typeof value === 'number' && Number.isFinite(value);
  const cache = new Map();
  let grid, catalog, current, reference, map, overlay, selectedLine;
  let activeValues = [], activeMode = 'difference';
  let requestVersion = 0;
  let tracing = false;
  let endpoints = [];
  const contextLayers = new Map();
  const explanations = {
    difference: 'O valor é a temperatura do ano da análise menos a do ano de referência, na mesma célula. Vermelho indica aumento e azul indica redução. O cálculo usa somente áreas válidas nos dois anos. Mudanças nas datas, no tempo e na cobertura também influenciam a diferença.',
    frequency: 'Uma área é considerada relativamente quente quando fica pelo menos 2 °C acima da mediana terrestre da cidade na composição daquele ano. O percentual divide os anos quentes pelos anos com observações válidas em cada célula. Entram locais com pelo menos três anos válidos. A frequência reúne todos os anos disponíveis, independentemente dos seletores.',
    count: 'Cada número mostra quantas cenas contribuíram com temperatura válida para a célula no ano escolhido. Mais cenas dão mais observações para a composição. Essa contagem ajuda a interpretar o mapa e não garante, sozinha, maior precisão.',
    error: 'O valor é a temperatura estimada menos a observada pelo satélite, usando previsões de validação espacial fora do treinamento. Vermelho indica superestimação e azul indica subestimação. Este mapa ajuda a localizar onde o modelo erra mais. A camada estimada do mapa principal usa o ajuste final e tem outra finalidade.'
  };

  function table(headers, rows, caption) {
    return `<table><caption class="sr-only">${esc(caption)}</caption><thead><tr>${headers.map(x => `<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(value => `<td>${esc(value)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }

  function degree(value) { return available(value) ? `${fmt(value)} °C` : 'Sem dados'; }

  async function loadYear(year) {
    if (!cache.has(year)) {
      const result = await api(`/api/research/${year}`);
      if (result.generated_at !== grid.generated_at) throw Error('As análises estão sendo atualizadas. Recarregue a página em instantes.');
      cache.set(year, result);
    }
    return cache.get(year);
  }

  function fillColor(value, mode) {
    if (mode === 'frequency') return value >= 75 ? '#8a1625' : value >= 50 ? '#d94b32' : value >= 25 ? '#f2ab52' : '#fff0ac';
    if (mode === 'count') return value >= 3 ? '#075e66' : value >= 2 ? '#57a6a0' : '#e1c682';
    return value < -2 ? '#2166ac' : value < -.5 ? '#86b9d6' : value <= .5 ? '#f4e6c6' : value <= 2 ? '#ed9875' : '#a51d32';
  }

  function renderMap() {
    if (!current) return;
    const mode = el('researchMode').value;
    const values = mode === 'frequency' ? grid.frequency : mode === 'count' ? current.count : mode === 'error' ? current.error : current.temperature.map((value, i) => available(value) && available(reference.temperature[i]) ? value - reference.temperature[i] : null);
    activeValues = values;
    activeMode = mode;
    let validCells = 0;
    values.forEach((value, index) => {
      if (available(value) && !(mode === 'count' && !available(current.temperature[index]))) validCells++;
    });
    const style = feature => {
      const index = feature.properties.index;
      const value = activeValues[index];
      const shown = available(value) && !(activeMode === 'count' && !available(current.temperature[index]));
      return {fillColor: shown ? fillColor(value, activeMode) : 'transparent', fillOpacity: shown ? .7 : 0, stroke: false};
    };
    if (!overlay) {
      const features = grid.polygons.map((ring, index) => ({
        type: 'Feature', geometry: {type: 'Polygon', coordinates: [[...ring, ring[0]]]}, properties: {index}
      }));
      overlay = L.geoJSON({type: 'FeatureCollection', features}, {
        style,
        onEachFeature: (feature, layer) => {
          layer.on('click', event => {
            if (tracing) { addEndpoint(event.latlng); return; }
            const index = feature.properties.index;
            const value = activeValues[index];
            if (!available(value) || (activeMode === 'count' && !available(current.temperature[index]))) return;
            const cell = grid.cells[index];
            const name = current.neighborhoods.find(x => x.id === cell[4])?.name || 'Área selecionada';
            const description = activeMode === 'frequency'
              ? `${fmt(value)}% · ${grid.hot_years[index]} anos quentes em ${grid.valid_years[index]} anos válidos`
              : activeMode === 'count' ? `${fmt(value, 0)} cenas válidas` : `${fmt(value)} °C`;
            L.popup().setLatLng(event.latlng).setContent(
              `<strong>${esc(bairroDisplayName(name))}</strong><p>${esc(description)}</p><small>Célula da grade de 120 m. Consulte o critério da camada acima do mapa.</small>`
            ).openOn(map);
          });
        }
      }).addTo(map);
    } else {
      if (!map.hasLayer(overlay)) overlay.addTo(map);
      overlay.setStyle(style);
    }
    contextLayers.forEach(layer => layer.bringToFront());
    if (selectedLine) selectedLine.bringToFront();
    el('researchExplanation').textContent = explanations[mode];
    const sameYear = mode === 'difference' && current.year === reference.year;
    const title = sameYear ? 'Os dois seletores estão no mesmo ano. A diferença é zero nas células válidas.' : mode === 'difference' ? `${current.year} menos ${reference.year}` : mode === 'frequency' ? 'Todos os anos disponíveis' : String(current.year);
    el('researchStatus').textContent = `${title} · ${fmt(validCells, 0)} células com dados para esta camada.${validCells ? '' : ' Nenhum resultado disponível para os critérios escolhidos.'}`;
    el('researchLegend').textContent = mode === 'frequency' ? 'Amarelo claro 0–25% · laranja 25–50% · vermelho 50–75% · vinho 75–100%. O percentual exato aparece ao clicar.' : mode === 'count' ? 'Amarelo 1 cena · verde claro 2 cenas · verde escuro 3 ou mais. Clique para ver o número exato.' : 'Azul escuro abaixo de −2 °C · azul claro de −2 a −0,5 °C · creme de −0,5 a +0,5 °C · laranja até +2 °C · vermelho acima de +2 °C.';
  }

  function boxPlot(row) {
    if (!row?.n) return '<p>Este bairro não tem células válidas neste período.</p>';
    const low = Math.floor(row.min - 1), high = Math.ceil(row.max + 1);
    const x = value => 45 + (value - low) / (high - low) * 370;
    return `<svg viewBox="0 0 460 150" role="img" aria-label="Distribuição da temperatura de ${esc(row.name)}"><line x1="${x(row.p10)}" x2="${x(row.p90)}" y1="60" y2="60" stroke="#7f3021" stroke-width="3"/><rect x="${x(row.q25)}" y="38" width="${Math.max(1, x(row.q75) - x(row.q25))}" height="44" fill="#ffd66b" stroke="#a32b20"/><line x1="${x(row.median)}" x2="${x(row.median)}" y1="32" y2="88" stroke="#a32b20" stroke-width="4"/>${[row.min, row.median, row.max].map(v => `<text x="${x(v)}" y="116" text-anchor="middle" font-size="13" fill="#733824">${fmt(v)} °C</text>`).join('')}</svg>`;
  }

  function renderNeighborhood() {
    if (!current) return;
    const row = current.neighborhoods.find(x => String(x.id) === el('researchBairro').value);
    el('researchBox').innerHTML = boxPlot(row);
    el('researchDistribution').innerHTML = row ? table(['Medida', 'Temperatura'], [['Mínimo', degree(row.min)], ['Percentil 10', degree(row.p10)], ['Q25', degree(row.q25)], ['Mediana', degree(row.median)], ['Q75', degree(row.q75)], ['Percentil 90', degree(row.p90)], ['Máximo', degree(row.max)], ['Média', degree(row.mean)], ['Células válidas', fmt(row.n, 0)]], 'Distribuição da temperatura no bairro') : '';
  }

  function renderProximity() {
    if (!current) return;
    const rows = current.proximity[el('researchNatural').value];
    el('researchProximity').innerHTML = table(['Distância', 'N', 'Média', 'Mediana'], rows.map(x => [x.label, fmt(x.n, 0), degree(x.mean), degree(x.median)]), 'Temperatura por distância de áreas naturais');
  }

  function renderTables() {
    renderNeighborhood();
    renderProximity();
    el('researchBins').innerHTML = table(['NDVI', 'N', 'Mediana', 'Q25', 'Q75'], current.ndvi_bins.map(x => [x.label, fmt(x.n, 0), degree(x.median), degree(x.q25), degree(x.q75)]), 'Temperatura por faixa de vegetação');
    const sensitivity = current.sensitivity;
    el('researchSensitivity').innerHTML = table(['Processamento', 'N', 'Média', 'Mediana'], [['Padrão', sensitivity.standard], [`Filtro de até ${fmt(sensitivity.strict_limit_k, 0)} K`, sensitivity.strict], ['Primeira cena selecionada', sensitivity.single]].map(([label, x]) => [label, fmt(x.n, 0), degree(x.mean), degree(x.median)]), 'Comparação de escolhas de processamento');
    el('researchSensitivityDetail').textContent = sensitivity.strict.n ? `Nas ${fmt(sensitivity.paired_difference.n, 0)} células comuns aos filtros, a diferença média (filtro rigoroso menos padrão) é ${degree(sensitivity.paired_difference.mean)}. K expressa a incerteza térmica informada pelo produto. Uma diferença de 1 K tem o mesmo tamanho que uma diferença de 1 °C.` : sensitivity.strict_available ? 'Nenhuma célula passou pelo filtro mais rigoroso neste período. A diferença em células comuns fica indisponível.' : 'O teste com filtro rigoroso será disponibilizado após o reprocessamento das cenas. Os demais resultados continuam disponíveis.';
    const population = current.neighborhoods.filter(x => x.coverage >= .5 && available(x.mean)).sort((a, b) => b.mean - a.mean);
    el('researchPopulation').innerHTML = table(['Bairro', 'Moradores (2022)', `Média (${current.year})`, 'Parcela quente da área observada', 'Cobertura'], population.map(x => [bairroDisplayName(x.name), fmt(x.population, 0), degree(x.mean), `${fmt(x.hot_share * 100)}%`, `${fmt(x.coverage * 100)}%`]), 'Contexto populacional dos bairros ordenados por temperatura média');
  }

  function clearTrace() {
    endpoints = [];
    tracing = false;
    if (selectedLine) selectedLine.remove();
    selectedLine = null;
    el('researchTrace').textContent = 'Marcar início e fim';
    el('researchTraceStatus').textContent = '';
    el('researchProfile').innerHTML = '';
  }

  function addEndpoint(point) {
    if (!tracing) return;
    // A map event can propagate from a cell. Ignore the same click twice.
    if (endpoints.length && endpoints.at(-1).distanceTo(point) < 1) return;
    endpoints.push(point);
    if (endpoints.length === 1) {
      el('researchTraceStatus').textContent = 'Início marcado. Agora clique no ponto final.';
      return;
    }
    tracing = false;
    selectedLine = L.polyline(endpoints, {color: '#6d1c1c', weight: 4, interactive: false}).addTo(map);
    renderProfile();
    el('researchTrace').textContent = 'Marcar outro trajeto';
  }

  function renderProfile() {
    if (endpoints.length !== 2) return;
    const [start, end] = endpoints;
    const distance = start.distanceTo(end);
    const steps = Math.max(1, Math.min(400, Math.ceil(distance / 120)));
    const samples = [];
    for (let step = 0; step <= steps; step++) {
      const fraction = step / steps;
      const point = L.latLng(start.lat + (end.lat - start.lat) * fraction, start.lng + (end.lng - start.lng) * fraction);
      let best = -1, nearest = 90;
      grid.cells.forEach((cell, index) => {
        const d = point.distanceTo([cell[2], cell[3]]);
        if (d < nearest && ringContainsPoint(grid.polygons[index], point.lng, point.lat)) { best = index; nearest = d; }
      });
      samples.push({distance: distance * fraction, value: best >= 0 ? current.temperature[best] : null});
    }
    const values = samples.filter(x => available(x.value)).map(x => x.value);
    el('researchTraceStatus').textContent = `Trajeto de ${fmt(distance / 1000, 2)} km · ${values.length} de ${samples.length} pontos amostrados com temperatura válida · ${current.year}.`;
    if (!values.length) { el('researchProfile').innerHTML = '<p>Este trajeto não cruza células com observações válidas no período selecionado.</p>'; return; }
    const low = Math.floor(Math.min(...values) - 1), high = Math.ceil(Math.max(...values) + 1);
    let path = '', connected = false;
    samples.forEach(sample => {
      if (!available(sample.value)) { connected = false; return; }
      path += `${connected ? 'L' : 'M'}${45 + sample.distance / Math.max(1, distance) * 370},${180 - (sample.value - low) / (high - low) * 140} `;
      connected = true;
    });
    el('researchProfile').innerHTML = `<svg viewBox="0 0 460 230" role="img" aria-label="Temperatura da superfície ao longo do trajeto"><path d="${path}" fill="none" stroke="#a72d20" stroke-width="3"/><text x="10" y="40" font-size="12">${high} °C</text><text x="10" y="180" font-size="12">${low} °C</text><text x="45" y="212" font-size="12">Início</text><text x="415" y="212" text-anchor="end" font-size="12">${fmt(distance / 1000, 2)} km</text></svg>`;
  }

  async function updateResearch() {
    const version = ++requestVersion;
    el('researchStatus').textContent = 'Carregando o período selecionado…';
    try {
      const [next, previous] = await Promise.all([loadYear(Number(el('researchYear').value)), loadYear(Number(el('researchReference').value))]);
      if (version !== requestVersion) return;
      current = next;
      reference = previous;
      const periods = [current.year, reference.year].map(year => {
        const record = catalog.years.find(x => x.year === year);
        return `${year} · ${record.scenes.map(x => new Date(x.date).toLocaleDateString('pt-BR', {timeZone: 'UTC'})).join(', ')}`;
      });
      el('researchPeriod').textContent = `Datas das composições — ${periods.join(' / ')}. Use o ano de referência para a camada de diferença.`;
      renderMap(); renderTables(); renderProfile();
      el('researchTrace').disabled = false;
    } catch (error) {
      if (version !== requestVersion) return;
      current = null;
      if (overlay) overlay.remove();
      ['researchBox', 'researchDistribution', 'researchBins', 'researchProximity', 'researchSensitivity', 'researchPopulation', 'researchProfile'].forEach(id => { el(id).innerHTML = ''; });
      el('researchTrace').disabled = true;
      el('researchStatus').textContent = `Não foi possível carregar esta análise. ${error.message}`;
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      [grid, catalog] = await Promise.all([api('/api/research-grid'), api('/api/manifest')]);
      if (grid.generated_at !== catalog.generated_at) throw Error('O mapa e as análises são de versões diferentes. Aguarde a conclusão da atualização.');
      map = L.map('researchMap', {preferCanvas: true, scrollWheelZoom: false}).fitBounds(catalog.bounds);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
      L.control.scale({imperial: false}).addTo(map);
      map.on('click', event => addEndpoint(event.latlng));
      const options = catalog.years.map(x => `<option value="${x.year}">${x.year}${x.partial ? ' · parcial' : ''}</option>`).join('');
      ['researchYear', 'researchReference'].forEach(id => { el(id).innerHTML = options; el(id).disabled = false; el(id).addEventListener('change', updateResearch); });
      el('researchYear').value = catalog.years.at(-1).year;
      el('researchReference').value = catalog.years[0].year;
      el('researchBairro').innerHTML = catalog.years[0].neighborhoods.map(x => `<option value="${x.id}">${esc(bairroDisplayName(x.name))}</option>`).join('');
      el('researchBairro').disabled = false;
      el('researchBairro').addEventListener('change', renderNeighborhood);
      el('researchNatural').addEventListener('change', renderProximity);
      el('researchMode').addEventListener('change', renderMap);
      el('researchTrace').addEventListener('click', () => { clearTrace(); tracing = true; el('researchTraceStatus').textContent = 'Clique no ponto inicial no mapa acima.'; });
      el('researchClearTrace').addEventListener('click', clearTrace);
      document.querySelectorAll('.research-context input').forEach(input => input.addEventListener('change', () => {
        if (contextLayers.has(input.value)) { contextLayers.get(input.value).remove(); contextLayers.delete(input.value); }
        if (input.checked) {
          const layer = L.geoJSON(grid.context[input.value], {style: {color: input.value === 'rios' ? '#1879a0' : '#176349', weight: 2, fillOpacity: .18}, onEachFeature: (feature, layer) => layer.bindTooltip(esc(feature.properties.name))}).addTo(map);
          contextLayers.set(input.value, layer);
        }
      }));
      await updateResearch();
    } catch (error) { el('researchStatus').textContent = `As análises adicionais estão indisponíveis. ${error.message}`; }
  });
})();
