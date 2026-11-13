let els;
let statusState = {};
let translations = {};
let textTimerId = null;
let popupPinned = false;
let compactHide = [];
let lastData = null;
let refreshPending = false;
let usageRenderRevision = 0;

/**
 * Set CSS custom properties for theme colors and inject translation strings.
 *
 * Called once by Python after the page loads.  Translations are set as
 * textContent on heading elements so the HTML file stays language-neutral.
 *
 * @param {object} config - { colors, t (translations), app_version, data (initial snapshot) }
 */
function init(config) {
    const s = document.documentElement.style;
    for (const [key, value] of Object.entries(config.colors)) {
        s.setProperty(`--${key.replaceAll('_', '-')}`, value);
    }

    translations = config.t;
    compactHide = config.compact_hide || [];
    document.getElementById('title').textContent = translations.title;
    document.getElementById('headingAccount').textContent = translations.account;
    document.getElementById('labelEmail').textContent = translations.email;
    document.getElementById('labelPlan').textContent = translations.plan;
    document.getElementById('headingUsage').textContent = translations.usage;
    document.getElementById('headingExtraUsage').textContent = translations.extra_usage;
    document.getElementById('headingClaudeCode').textContent = translations.claude_code;

    const changelogLink = document.getElementById('changelogLink');
    changelogLink.textContent = translations.changelog;
    changelogLink.addEventListener('click', () => pywebview.api.open_url());
    document.getElementById('closeBtn').addEventListener('click', () => pywebview.api.close());
    setupRefreshButton();
    setupPinButton();
    setupPinnedDrag();

    document.getElementById('appVersion').textContent = config.app_version;

    els = {
        accountSection: document.getElementById('accountSection'),
        emailRow: document.getElementById('emailRow'),
        emailValue: document.getElementById('emailValue'),
        planRow: document.getElementById('planRow'),
        planValue: document.getElementById('planValue'),
        usageSection: document.getElementById('usageSection'),
        headingUsage: document.getElementById('headingUsage'),
        usageBars: document.getElementById('usageBars'),
        extraSection: document.getElementById('extraSection'),
        extraSpent: document.getElementById('extraSpent'),
        extraPct: document.getElementById('extraPct'),
        extraBarContainer: document.getElementById('extraBarContainer'),
        extraFill: document.getElementById('extraFill'),
        installSection: document.getElementById('installSection'),
        installRows: document.getElementById('installRows'),
        statusSection: document.getElementById('statusSection'),
        statusText: document.getElementById('statusText'),
    };

    updateData(config.data);
    requestAnimationFrame(() => document.body.classList.add('open'));
}

function setupRefreshButton() {
    const refreshBtn = document.getElementById('refreshBtn');
    refreshBtn.setAttribute('aria-label', translations.refresh);
    refreshBtn.title = translations.refresh;

    refreshBtn.addEventListener('click', async () => {
        if (refreshPending) {
            return;
        }

        refreshPending = true;
        refreshBtn.disabled = true;
        refreshBtn.classList.add('refreshing');
        try {
            const data = await pywebview.api.refresh();
            updateData(data);
        } catch (_error) {
            // The existing snapshot stays visible when a manual refresh fails.
        } finally {
            refreshPending = false;
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('refreshing');
        }
    });
}

function setupPinButton() {
    const pinBtn = document.getElementById('pinBtn');

    function render() {
        document.body.classList.toggle('pinned', popupPinned);
        pinBtn.classList.toggle('pinned', popupPinned);
        pinBtn.setAttribute('aria-pressed', popupPinned ? 'true' : 'false');
        pinBtn.setAttribute('aria-label', popupPinned ? translations.unpin_popup : translations.pin_popup);
        pinBtn.title = popupPinned ? translations.unpin_popup : translations.pin_popup;
    }

    pinBtn.addEventListener('click', () => {
        const nextPinned = !popupPinned;
        popupPinned = nextPinned;
        render();
        reapplyData();
        pywebview.api.set_pinned(nextPinned).then((applied) => {
            popupPinned = !!applied;
            render();
            reapplyData();
        }).catch(() => {
            popupPinned = !nextPinned;
            render();
            reapplyData();
        });
    });

    render();
}

/**
 * Return true if a section or usage bar is hidden by the pinned compact view.
 *
 * Hiding only applies while the popup is pinned; unpinned it always shows
 * everything.  `key` is a section key (account, extra_usage, claude_code,
 * status) or a usage field name (e.g. seven_day_opus).
 */
function compactHidden(key) {
    return popupPinned && compactHide.includes(key);
}

// Re-render the last snapshot so compact hiding takes effect on pin toggle.
function reapplyData() {
    if (lastData) {
        updateData(lastData);
    }
}

function setupPinnedDrag() {
    const header = document.querySelector('header');
    let dragging = false;

    function setDragging(active) {
        dragging = active;
        header.classList.toggle('dragging', active);
    }

    header.addEventListener('mousedown', (event) => {
        if (!popupPinned || event.button !== 0 || event.target.closest('button')) {
            return;
        }
        event.preventDefault();
        setDragging(true);
        pywebview.api.begin_drag().then((started) => {
            setDragging(!!started);
        }).catch(() => {
            setDragging(false);
        });
    });

    document.addEventListener('mousemove', (event) => {
        if (!dragging) {
            return;
        }
        // No button held (e.g. released outside the window): stop dragging.
        if (event.buttons === 0) {
            setDragging(false);
            pywebview.api.end_drag();
            return;
        }
        pywebview.api.drag().catch(() => {});
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) {
            return;
        }
        setDragging(false);
        pywebview.api.end_drag();
    });
}

/**
 * Update all popup sections with fresh data from Python.
 *
 * @param {object} data - Pre-formatted snapshot from _snapshot_to_dict().
 */
function updateData(data) {
    lastData = data;

    const hasProfile = !!data.profile;
    const accountVisible = hasProfile && !compactHidden('account');
    els.accountSection.classList.toggle('visible', accountVisible);
    if (hasProfile) {
        els.emailValue.textContent = data.profile.email;
        els.emailRow.style.display = data.profile.email ? '' : 'none';
        els.planValue.textContent = data.profile.plan;
        els.planRow.style.display = data.profile.plan ? '' : 'none';
    }

    const usage = (data.usage || []).filter((entry) => !compactHidden(entry.key));
    const hasUsage = !!usage.length;
    els.usageSection.classList.toggle('visible', hasUsage);
    updateUsageBars(usage);

    const hasExtra = !!data.extra;
    const extraVisible = hasExtra && !compactHidden('extra_usage');
    els.extraSection.classList.toggle('visible', extraVisible);
    if (hasExtra) {
        els.extraSpent.textContent = data.extra.spent_text;
        els.extraPct.style.display = data.extra.has_limit ? '' : 'none';
        els.extraPct.textContent = data.extra.pct_text;
        els.extraBarContainer.style.display = data.extra.has_limit ? '' : 'none';
        els.extraFill.style.width = `${data.extra.fill_pct * 100}%`;
    }

    const hasInstalls = !!data.installations?.length;
    const installsVisible = hasInstalls && !compactHidden('claude_code');
    els.installSection.classList.toggle('visible', installsVisible);

    // The "Usage" heading only labels the bars against the other sections;
    // when the usage bars stand alone, drop the now-redundant heading.
    els.headingUsage.style.display = (hasUsage && !accountVisible && !extraVisible && !installsVisible) ? 'none' : '';

    if (hasInstalls) {
        els.installRows.replaceChildren(...data.installations.map((inst) => {
            const row = document.createElement('div');
            const dt = document.createElement('dt');
            dt.textContent = inst.name;
            const dd = document.createElement('dd');
            dd.textContent = inst.version;
            row.append(dt, dd);
            return row;
        }));
    }

    updateStatus(data.status);
}

/**
 * Update the status footer with live timer data or static text.
 *
 * Live mode (has last_success_time): starts a 1-second interval for
 * the text counter.  Static mode (has text): shows plain text.
 */
function updateStatus(status) {
    if (textTimerId) {
        clearInterval(textTimerId);
        textTimerId = null;
    }

    if (!status) {
        els.statusSection.classList.remove('visible');
        return;
    }

    // Keep the live timer running even when the footer is hidden in compact
    // view, so the stale-dimming of the usage bars still updates.
    els.statusSection.classList.toggle('visible', !compactHidden('status'));

    if (status.last_success_time !== undefined) {
        statusState = {
            lastSuccessTime: status.last_success_time,
            nextPollTime: status.next_poll_time,
            refreshing: status.refreshing,
            error: status.error,
        };
        els.statusSection.classList.toggle('error', !!status.error);
        tickStatusText();
        textTimerId = setInterval(tickStatusText, 1000);
    } else {
        statusState = {};
        els.statusText.textContent = status.text || '';
        els.statusText.title = status.is_error ? (status.text || '') : '';
        els.statusSection.classList.toggle('error', !!status.is_error);
    }
}

/**
 * Build and display the status text from current state.
 *
 * < 60s:  "Updated Xs ago"
 * >= 60s: "Updated Xm ago · Next update in Ym"
 * + refreshing or error appended with · separator
 */
function tickStatusText() {
    if (!statusState.lastSuccessTime) return;

    const now = Date.now() / 1000;
    const secondsAgo = Math.max(0, Math.floor(now - statusState.lastSuccessTime));
    const isStale = !!statusState.nextPollTime && (now > statusState.nextPollTime + 30);
    els.usageSection.classList.toggle('stale', isStale);
    els.extraSection.classList.toggle('stale', isStale);

    const parts = [formatDuration(secondsAgo)];

    if (statusState.refreshing) {
        parts.push(translations.status_refreshing);
    } else if (statusState.error) {
        parts.push(statusState.error);
    } else if (secondsAgo >= 60 && statusState.nextPollTime) {
        const secondsUntil = Math.max(0, Math.floor(statusState.nextPollTime - now));
        if (secondsUntil > 0) {
            parts.push(translations.status_next_update.replace('{duration}', formatCountdown(secondsUntil)));
        }
    }

    els.statusText.textContent = parts.join(' \u00b7 ');
    // Errors are raw API messages that can overflow; reveal the full text on hover.
    els.statusText.title = statusState.error ? els.statusText.textContent : '';
}

/**
 * Format seconds into a localized "Updated Xs ago" / "Updated Xm ago" string.
 */
function formatDuration(totalSeconds) {
    if (totalSeconds < 60) {
        return translations.status_updated_s.replace('{s}', totalSeconds);
    }

    const totalMin = Math.floor(totalSeconds / 60);
    const hours = Math.floor(totalMin / 60);
    const mins = totalMin % 60;

    let duration;
    if (hours > 0) {
        duration = translations.duration_hm.replace('{h}', hours).replace('{m}', mins);
    } else {
        duration = translations.duration_m.replace('{m}', totalMin);
    }
    return translations.status_updated.replace('{duration}', duration);
}

/**
 * Format a countdown in seconds into a localized duration string.
 */
function formatCountdown(totalSeconds) {
    if (totalSeconds < 60) {
        return translations.duration_s.replace('{s}', totalSeconds);
    }

    const totalMin = Math.ceil(totalSeconds / 60);
    const hours = Math.floor(totalMin / 60);
    const mins = totalMin % 60;

    if (hours > 0) {
        return translations.duration_hm.replace('{h}', hours).replace('{m}', mins);
    }
    return translations.duration_m.replace('{m}', totalMin);
}

function updateUsageBars(entries) {
    const revision = ++usageRenderRevision;
    // The quota set or presentation can change independently of the count.
    const current = els.usageBars.children;
    const forecasts = entries.map((entry) => validForecast(entry.forecast) ? entry.forecast : null);
    const sameEntries = entries.length === current.length && entries.every((entry, i) =>
        current[i].dataset.key === entry.key && current[i].classList.contains('chart-entry') === !!forecasts[i]);

    if (!sameEntries) {
        for (const node of current) {
            const svg = node.querySelector('.forecast-chart');
            if (svg) forecastResizeObserver.unobserve(svg);
        }
        const nodes = entries.map((entry, i) => forecasts[i] ? createForecastElement(entry, forecasts[i]) : createBarElement(entry));
        els.usageBars.replaceChildren(...nodes);
        // A newer snapshot may update or replace these nodes before the frame runs.
        requestAnimationFrame(() => {
            if (revision !== usageRenderRevision) return;
            for (const [i, node] of nodes.entries()) {
                const fill = node.querySelector('.bar-fill');
                if (fill) fill.style.width = `${entries[i].fill_pct * 100}%`;
            }
        });
    } else {
        for (let i = 0; i < entries.length; i++) {
            const node = current[i];
            node.querySelector('.bar-label').textContent = entries[i].label;
            if (forecasts[i]) {
                updateForecastElement(node, entries[i], forecasts[i]);
            } else {
                updateBarElement(node, entries[i]);
            }
        }
    }
}

function createEntryHeader(entry) {
    const header = document.createElement('div');
    header.className = 'bar-header';
    const label = document.createElement('span');
    label.className = 'bar-label';
    label.textContent = entry.label;
    const pct = document.createElement('span');
    pct.className = 'bar-pct';
    pct.textContent = entry.pct_text;
    header.append(label, pct);
    return header;
}

function createBarElement(entry) {
    const div = document.createElement('div');
    div.className = 'usage-entry';
    div.dataset.key = entry.key;

    const header = createEntryHeader(entry);
    const container = document.createElement('div');
    container.className = 'bar-container';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.classList.toggle('warn', entry.warn);
    fill.style.width = '0%';
    container.appendChild(fill);

    for (const pos of entry.dividers) {
        const d = document.createElement('div');
        d.className = 'bar-divider';
        d.style.left = `calc(${pos * 100}% - 1px)`;
        container.appendChild(d);
    }

    if (entry.marker_rel !== null) {
        const marker = document.createElement('div');
        marker.className = 'bar-marker';
        marker.style.left = `calc(${entry.marker_rel * 100}% - 1px)`;
        container.appendChild(marker);
    }

    div.append(header, container);

    if (entry.reset_text) {
        const reset = document.createElement('div');
        reset.className = 'reset-text';
        reset.textContent = entry.reset_text;
        div.appendChild(reset);
    }

    return div;
}

function updateBarElement(div, entry) {
    div.querySelector('.bar-pct').textContent = entry.pct_text;

    const fill = div.querySelector('.bar-fill');
    fill.style.width = `${entry.fill_pct * 100}%`;
    fill.classList.toggle('warn', entry.warn);

    const container = div.querySelector('.bar-container');
    let marker = container.querySelector('.bar-marker');
    if (entry.marker_rel !== null) {
        if (!marker) {
            marker = document.createElement('div');
            marker.className = 'bar-marker';
            container.appendChild(marker);
        }
        marker.style.left = `calc(${entry.marker_rel * 100}% - 1px)`;
    } else if (marker) {
        marker.remove();
    }

    for (const d of container.querySelectorAll('.bar-divider')) d.remove();
    for (const pos of entry.dividers) {
        const d = document.createElement('div');
        d.className = 'bar-divider';
        d.style.left = `calc(${pos * 100}% - 1px)`;
        container.appendChild(d);
    }

    let resetEl = div.querySelector('.reset-text');
    if (entry.reset_text) {
        if (!resetEl) {
            resetEl = document.createElement('div');
            resetEl.className = 'reset-text';
            div.appendChild(resetEl);
        }
        resetEl.textContent = entry.reset_text;
    } else if (resetEl) {
        resetEl.remove();
    }
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const forecastResizeObserver = new ResizeObserver((entries) => {
    for (const { target } of entries) drawForecast(target, target.forecast);
});

/** Keep the normal bar if the forecast payload is absent or incomplete. */
function validForecast(forecast) {
    const fraction = (x) => Number.isFinite(x) && x >= 0 && x <= 1;
    const point = (pair) => Array.isArray(pair) && fraction(pair[0])
        && Number.isFinite(pair[1]) && pair[1] >= 0 && pair[1] <= 100;
    return forecast && fraction(forecast.now_x) && fraction(forecast.measured_from)
        && Array.isArray(forecast.actual) && forecast.actual.length >= 2 && forecast.actual.every(point)
        && Array.isArray(forecast.projection) && forecast.projection.every(point)
        && Array.isArray(forecast.ticks) && forecast.ticks.every((tick) => tick && fraction(tick.x));
}

function svgElement(tag, attributes) {
    const element = document.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attributes)) {
        element.setAttribute(name, value);
    }
    return element;
}

function createForecastElement(entry, forecast) {
    const div = document.createElement('div');
    div.className = 'usage-entry chart-entry';
    div.dataset.key = entry.key;

    // Header and footer carry the same quota information as the visual.
    const chart = svgElement('svg', { class: 'forecast-chart', 'aria-hidden': 'true' });
    const footer = document.createElement('div');
    footer.className = 'chart-footer';
    const reset = document.createElement('span');
    reset.className = 'reset-text';
    const summary = document.createElement('span');
    summary.className = 'forecast-summary';
    footer.append(reset, summary);
    div.append(createEntryHeader(entry), chart, footer);

    updateForecastElement(div, entry, forecast);
    forecastResizeObserver.observe(chart);
    return div;
}

function updateForecastElement(div, entry, forecast) {
    const svg = div.querySelector('.forecast-chart');
    svg.forecast = forecast;
    div.querySelector('.bar-pct').textContent = entry.pct_text;
    div.querySelector('.reset-text').textContent = entry.reset_text;
    div.querySelector('.forecast-summary').textContent = forecast.summary || '';
    drawForecast(svg, forecast);
}

/**
 * Draw utilization (y) over the wall-clock quota window (x). The dotted line
 * before the first reading is an estimate; the dashed line beyond now is the
 * projection. Recalculate in CSS pixels when the chart is resized.
 */
function drawForecast(svg, forecast) {
    const width = svg.clientWidth || 308;
    const height = svg.clientHeight || 80;
    const left = 30;
    const right = Math.max(left + 1, width - 4);
    const top = 5;
    const bottom = Math.max(top + 1, height - 16);
    const plotWidth = right - left;
    const plotHeight = bottom - top;
    const px = (x) => left + x * plotWidth;
    const py = (y) => bottom - (y / 100) * plotHeight;
    const path = (points) => points.map(([x, y], i) => `${i ? 'L' : 'M'}${px(x).toFixed(1)},${py(y).toFixed(1)}`).join(' ');
    const nowX = px(forecast.now_x);
    const children = [];
    children.push(svgElement('rect', {
        class: forecast.runs_out ? 'ahead warn' : 'ahead',
        x: nowX, y: top, width: right - nowX, height: plotHeight,
    }));

    for (const pct of [0, 50, 100]) {
        const y = py(pct);
        children.push(svgElement('line', { class: pct === 100 ? 'limit' : 'grid', x1: left, x2: right, y1: y, y2: y }));
        const label = svgElement('text', { class: 'axis-text', x: left - 5, y: y + 3.5, 'text-anchor': 'end' });
        label.textContent = `${pct}%`;
        children.push(label);
    }

    for (const [index, tick] of forecast.ticks.entries()) {
        const x = px(tick.x);
        children.push(svgElement('line', { class: 'grid', x1: x, x2: x, y1: top, y2: bottom }));
        const nextX = px(forecast.ticks[index + 1]?.x ?? 1);
        const labelX = (x + nextX) / 2;
        // Avoid labels overlapping the Now marker or the right edge.
        if (tick.label && Math.abs(labelX - nowX) > 26 && nextX - x > 24 && labelX < right - 8) {
            const label = svgElement('text', { class: 'axis-text', x: labelX, y: height - 3, 'text-anchor': 'middle' });
            label.textContent = tick.label;
            children.push(label);
        }
    }

    children.push(svgElement('line', { class: 'now', x1: nowX, x2: nowX, y1: top, y2: bottom }));
    const nowLabel = svgElement('text', {
        class: 'axis-text', x: Math.min(nowX, right - 12), y: height - 3, 'text-anchor': 'middle',
    });
    nowLabel.textContent = translations.forecast_now;
    children.push(nowLabel);

    const firstMeasured = forecast.actual.findIndex(([x]) => x >= forecast.measured_from);
    if (firstMeasured > 0) {
        children.push(svgElement('path', { class: 'assumed', d: path(forecast.actual.slice(0, firstMeasured + 1)) }));
    }
    if (firstMeasured >= 0 && firstMeasured < forecast.actual.length - 1) {
        children.push(svgElement('path', { class: 'actual', d: path(forecast.actual.slice(firstMeasured)) }));
    }

    if (forecast.projection.length) {
        const warnClass = forecast.runs_out ? ' warn' : '';
        children.push(svgElement('path', { class: `projection${warnClass}`, d: path(forecast.projection) }));
        const [endX, endY] = forecast.projection[forecast.projection.length - 1];
        children.push(svgElement('circle', { class: `end-dot${warnClass}`, cx: px(endX), cy: py(endY), r: 3 }));
    }

    svg.replaceChildren(...children);
}

// Report content height changes to the host (pywebview or dev.html iframe parent).
new ResizeObserver(() => {
    const height = document.body.scrollHeight;
    if (window.pywebview?.api?.report_height) {
        pywebview.api.report_height(height);
    }
}).observe(document.body);
