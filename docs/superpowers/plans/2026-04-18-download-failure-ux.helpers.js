// JS helpers to paste into library.html, directly after the closing `}` of
// the `checkExhaustedBanner` function. Uses innerHTML + escHTML() matching
// the rest of library.html's established pattern; every user-supplied string
// flowing into markup is passed through escHTML.

    function formatReasonsLine(topReasons) {
      if (!topReasons || !topReasons.length) return '';
      return topReasons.map(r => `${r[0]} (${r[1]})`).join(', ');
    }

    async function fetchFailureReport(filename, withDetails) {
      const url = `/api/collection/${encodeURIComponent(filename)}/failure-report${withDetails ? '?details=1' : ''}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error('failure-report fetch failed');
      return await resp.json();
    }

    function renderFailureExpand(cardEl, report) {
      const container = cardEl.querySelector('.card-failure-expand');
      if (!container) return;

      const name = cardEl.querySelector('h3')?.textContent?.trim() || '';
      const completed = report.completed || 0;
      const total = report.total || 0;
      const likely = report.likely || {count: 0, top_reasons: []};
      const unlikely = report.unlikely || {count: 0, top_reasons: []};
      const totalFailed = (likely.count || 0) + (unlikely.count || 0);
      const retryLabel = report.in_progress
        ? `Downloading... ${totalFailed} failed so far`
        : `Retry all ${totalFailed} failed`;
      const retryDisabled = report.in_progress ? 'disabled' : '';

      const likelyHTML = likely.count > 0 ? `
        <div class="card-failure-row card-failure-row-likely">
          <span class="icon">⚠</span>
          <div class="meta">
            <span class="count">${likely.count}</span> likely to succeed on retry
            <span class="reasons">${escHTML(formatReasonsLine(likely.top_reasons))}</span>
          </div>
        </div>` : '';

      const unlikelyHTML = unlikely.count > 0 ? `
        <div class="card-failure-row card-failure-row-unlikely">
          <span class="icon">✗</span>
          <div class="meta">
            <span class="count">${unlikely.count}</span> less likely (may need time or a new gateway)
            <span class="reasons">${escHTML(formatReasonsLine(unlikely.top_reasons))}</span>
          </div>
        </div>` : '';

      const html = `
        <div class="card-failure-header">${escHTML(name)} — ${completed} of ${total} downloaded</div>
        ${likelyHTML}
        ${unlikelyHTML}
        <div class="card-failure-actions">
          <button class="card-failure-retry" ${retryDisabled} data-filename="${escHTML(report.filename)}">${escHTML(retryLabel)}</button>
          <button class="card-failure-details-toggle" data-filename="${escHTML(report.filename)}">View details ▾</button>
        </div>
        <div class="card-failure-details-list"></div>
      `;
      container.innerHTML = html;

      container.querySelector('.card-failure-retry').onclick = () => {
        retryFailedDownloads(report.filename, cardEl);
      };
      container.querySelector('.card-failure-details-toggle').onclick = () => {
        toggleDetailsList(report.filename, cardEl);
      };
    }

    async function toggleFailureExpand(filename, cardEl) {
      const container = cardEl.querySelector('.card-failure-expand');
      if (!container) return;
      const isOpen = container.classList.contains('open');
      if (isOpen) {
        container.classList.remove('open');
        return;
      }
      container.classList.add('open');
      container.innerHTML = '<div class="card-failure-header">Loading…</div>';
      try {
        const report = await fetchFailureReport(filename, false);
        renderFailureExpand(cardEl, report);
      } catch (e) {
        container.innerHTML = '<div class="card-failure-header">Could not load failure details</div>';
      }
    }

    async function toggleDetailsList(filename, cardEl) {
      const listEl = cardEl.querySelector('.card-failure-details-list');
      if (!listEl) return;
      if (listEl.classList.contains('open')) {
        listEl.classList.remove('open');
        return;
      }
      listEl.innerHTML = 'Loading details…';
      listEl.classList.add('open');
      try {
        const report = await fetchFailureReport(filename, true);
        const rows = (report.details || []).map(d => `
          <div class="row">
            <span class="name" title="${escHTML(d.name)}">${escHTML(d.name)}</span>
            <span class="err">${escHTML(d.err)}</span>
          </div>
        `).join('');
        listEl.innerHTML = rows || '<div class="row"><span class="name">No details available</span></div>';
      } catch (e) {
        listEl.innerHTML = '<div class="row"><span class="name">Could not load details</span></div>';
      }
    }

    async function retryFailedDownloads(filename, cardEl) {
      const btn = cardEl.querySelector('.card-failure-retry');
      if (!btn) return;
      const origLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Retrying…';
      try {
        const resp = await fetch('/api/retry-failed', {method: 'POST'});
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || 'Retry failed');
        if (typeof showInfo === 'function') showInfo(data.message || 'Retry started');
        else alert(data.message || 'Retry started');
        setTimeout(async () => {
          try {
            const report = await fetchFailureReport(filename, false);
            renderFailureExpand(cardEl, report);
          } catch (e) { /* silent */ }
        }, 1500);
      } catch (e) {
        btn.disabled = false;
        btn.textContent = origLabel;
        if (typeof showError === 'function') showError('Retry failed: ' + e.message);
        else alert('Retry failed: ' + e.message);
      }
    }
