(function () {
  const budgetEl = document.getElementById('token-budget');
  const injectedEl = document.getElementById('token-injected');
  const savedEl = document.getElementById('token-saved');
  const loadedEl = document.getElementById('token-loaded-nodes');
  const injectionEl = document.getElementById('token-injection-count');
  const detailList = document.getElementById('token-detail-list');
  const chart = d3.select('#token-trend-chart');
  const numberFormat = new Intl.NumberFormat('en-US');

  function formatValue(value) {
    return numberFormat.format(value || 0);
  }

  function renderChart(points) {
    chart.selectAll('*').remove();
    const width = chart.node().clientWidth || 360;
    const height = chart.node().clientHeight || 140;
    if (!points.length) {
      chart.append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', '#4a5568')
        .attr('font-size', 12)
        .text('No injection timeline yet');
      return;
    }

    const xScale = d3.scaleTime()
      .domain(d3.extent(points, d => d.time))
      .range([32, width - 12]);
    const yMax = d3.max(points, d => Math.max(d.actual, d.baseline)) || 1;
    const yScale = d3.scaleLinear()
      .domain([0, yMax])
      .nice()
      .range([height - 12, 12]);

    const axis = chart.append('g');
    const yAxis = d3.axisLeft(yScale)
      .ticks(3)
      .tickSize(-width + 48)
      .tickFormat(d => formatValue(d));
    axis.attr('transform', 'translate(32,0)').call(yAxis).selectAll('text').attr('fill', '#4a5568').attr('font-size', 10);
    axis.selectAll('line').attr('stroke', '#1c1f2b');
    axis.selectAll('path').remove();

    const lineActual = d3.line()
      .x(d => xScale(d.time))
      .y(d => yScale(d.actual))
      .curve(d3.curveMonotoneX);
    const lineBaseline = d3.line()
      .x(d => xScale(d.time))
      .y(d => yScale(d.baseline))
      .curve(d3.curveMonotoneX);

    chart.append('path')
      .datum(points)
      .attr('d', lineBaseline)
      .attr('fill', 'none')
      .attr('stroke', '#63b3ed')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '4,4');

    chart.append('path')
      .datum(points)
      .attr('d', lineActual)
      .attr('fill', 'none')
      .attr('stroke', '#a78bfa')
      .attr('stroke-width', 2);
  }

  function renderDetails(events) {
    if (!events || !events.length) {
      detailList.innerHTML = '<div class="empty">No injection history yet.</div>';
      return;
    }
    detailList.innerHTML = events.map(e => {
      const shortId = String(e.node_id || 'n/a').slice(0, 12);
      const hits = (e.load_hits || 1) - 1;
      const note = hits > 0 ? `${hits} dedup hits` : 'Fresh injection';
      const dedupBadge = hits > 0 ? '<span class="dedup-hit">dedup</span>' : '';
      const title = hits > 0 ? 'Already in context — demoted' : 'New node added to context';
      return `
        <div class="token-detail-event" title="${title}">
          <div>
            <div class="node-id">${shortId}</div>
            <div class="token-note">${e.node_type} · ${note}</div>
          </div>
          <div>
            <span>${formatValue(e.tokens)} tokens</span>
            ${dedupBadge}
          </div>
        </div>`;
    }).join('');
  }

  async function loadTokenMetrics() {
    try {
      const response = await fetch('/api/token-metrics');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const session = payload.sessions?.[0];
      if (!session) {
        detailList.innerHTML = '<div class="empty">Waiting for session data…</div>';
        chart.selectAll('*').remove();
        return;
      }

      budgetEl.textContent = formatValue(session.token_limit);
      injectedEl.textContent = formatValue(session.token_estimate);
      savedEl.textContent = formatValue(session.dedup_tokens_saved);
      loadedEl.textContent = formatValue(session.loaded_node_count);
      injectionEl.textContent = formatValue(session.injection_count);

      const timeline = (session.timeline || []).map(evt => {
        const time = evt.injected_at ? new Date(evt.injected_at) : null;
        return {
          ...evt,
          time,
        };
      }).filter(evt => evt.time && !Number.isNaN(evt.time.valueOf()));

      let actualAccum = 0;
      let baselineAccum = 0;
      const points = timeline.map(evt => {
        actualAccum += evt.tokens || 0;
        baselineAccum += (evt.tokens || 0) * Math.max(1, evt.load_hits || 1);
        return {
          time: evt.time,
          actual: actualAccum,
          baseline: baselineAccum,
        };
      });

      renderChart(points);
      renderDetails(session.timeline || []);
    } catch (err) {
      detailList.innerHTML = `<div class="empty">Token metrics unavailable: ${err.message}</div>`;
      chart.selectAll('*').remove();
      if (typeof toast === 'function') {
        toast('Unable to load token metrics', true);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadTokenMetrics();
    setInterval(loadTokenMetrics, 60000);
  });
})();
