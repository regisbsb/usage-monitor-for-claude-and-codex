"""
Popup JS Tests
===============

Behavior tests for popup.js DOM update logic, executed with Node.js
against a minimal DOM stub.  Skipped when Node.js is not installed -
the app itself never needs Node; it is only used as a test runner
for the popup's JavaScript.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_POPUP_JS = Path(__file__).parent.parent / 'usage_monitor' / 'popup' / 'popup.js'

_NODE = shutil.which('node')

# Minimal DOM stub covering exactly the APIs the bar create/update path uses.
_DOM_STUB = r'''
class StubElement {
    constructor(tag) {
        this.tagName = tag;
        this.className = '';
        this.textContent = '';
        this.title = '';
        this.disabled = false;
        this.style = {};
        this.dataset = {};
        this.children = [];
        this.listeners = {};
        this.parentNode = null;
        const element = this;
        this.classList = {
            toggle(name, force) {
                const classes = element._classSet();
                const on = force === undefined ? !classes.has(name) : !!force;
                if (on) classes.add(name); else classes.delete(name);
                element.className = [...classes].join(' ');
                return on;
            },
            add(name) { const classes = element._classSet(); classes.add(name); element.className = [...classes].join(' '); },
            remove(name) { const classes = element._classSet(); classes.delete(name); element.className = [...classes].join(' '); },
            contains(name) { return element._classSet().has(name); },
        };
    }
    _classSet() { return new Set(this.className.split(/\s+/).filter(Boolean)); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    setAttribute(name, value) { this[name === 'class' ? 'className' : name] = String(value); }
    getAttribute(name) { return this[name === 'class' ? 'className' : name]; }
    click() { if (this.listeners.click) this.listeners.click(); }
    appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
    append(...nodes) { for (const node of nodes) this.appendChild(node); }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    remove() {
        if (this.parentNode) {
            const index = this.parentNode.children.indexOf(this);
            if (index >= 0) this.parentNode.children.splice(index, 1);
            this.parentNode = null;
        }
    }
    matches(selector) { return selector.startsWith('.') && this._classSet().has(selector.slice(1)); }
    querySelector(selector) {
        for (const child of this.children) {
            if (child.matches(selector)) return child;
            const nested = child.querySelector(selector);
            if (nested) return nested;
        }
        return null;
    }
    querySelectorAll(selector) {
        const found = [];
        for (const child of this.children) {
            if (child.matches(selector)) found.push(child);
            found.push(...child.querySelectorAll(selector));
        }
        return found;
    }
}

globalThis.document = {
    createElement: (tag) => new StubElement(tag),
    createElementNS: (_namespace, tag) => new StubElement(tag),
    body: new StubElement('body'),
};
const observers = [];
globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
    observe(target) { this.targets.add(target); }
    unobserve(target) { this.targets.delete(target); }
};
globalThis.requestAnimationFrame = (callback) => callback();
'''

_SCENARIO_PRELUDE = r'''
els = { usageBars: document.createElement('div') };
document.getElementById = () => null;

function makeEntry(overrides) {
    return Object.assign({
        key: 'five_hour', label: '5h', pct_text: '0%', fill_pct: 0.0,
        warn: false, dividers: [], marker_rel: null, reset_text: '',
    }, overrides);
}

function makeForecast(overrides) {
    return Object.assign({
        actual: [[0, 0], [0.2, 20], [0.5, 50]], measured_from: 0.2, now_x: 0.5,
        ticks: [{ x: 0.1, label: 'Fri' }, { x: 0.25, label: 'Sat' }],
        projection: [[0.5, 50], [0.75, 75], [1, 100]], runs_out: false,
        summary: 'At this pace: ~100% at reset',
    }, overrides);
}

function forecastPaths(chart) {
    return chart.children.filter((node) => node.tagName === 'path').map((node) => node.className);
}
'''


def _run_scenario(scenario: str) -> dict:
    """Execute the DOM stub + popup.js + scenario with Node and parse its JSON output."""
    script = _DOM_STUB + _POPUP_JS.read_text(encoding='utf-8') + _SCENARIO_PRELUDE + scenario
    with TemporaryDirectory() as tmp:
        script_path = Path(tmp) / 'scenario.js'
        script_path.write_text(script, encoding='utf-8')
        proc = subprocess.run([_NODE, str(script_path)], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f'Node scenario failed:\n{proc.stderr}')
    return json.loads(proc.stdout)


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestUsageBarUpdates(unittest.TestCase):
    """Tests for updateUsageBars/updateBarElement in popup.js."""

    def test_changed_field_set_with_equal_count_updates_labels(self):
        """When the set of quota fields changes but the count stays the same
        (e.g. an account switch between plans), the bars must not show the new
        percentages under the old labels."""
        result = _run_scenario('''
updateUsageBars([
    makeEntry({ key: 'five_hour', label: '5h', pct_text: '10%' }),
    makeEntry({ key: 'seven_day', label: '7d', pct_text: '20%' }),
]);
updateUsageBars([
    makeEntry({ key: 'five_hour', label: '5h', pct_text: '30%' }),
    makeEntry({ key: 'seven_day_opus', label: '7d Opus', pct_text: '99%' }),
]);
console.log(JSON.stringify(els.usageBars.children.map((bar) => ({
    label: bar.children[0].children[0].textContent,
    pct: bar.querySelector('.bar-pct').textContent,
}))));
''')
        self.assertEqual(result, [
            {'label': '5h', 'pct': '30%'},
            {'label': '7d Opus', 'pct': '99%'},
        ])

    def test_marker_and_divider_positions_stable_across_update(self):
        """The 2 px marker/divider elements are centered with a -1px correction
        on create; an in-place update must use the identical expression, or the
        elements shift by 1 px after the first data update."""
        result = _run_scenario('''
const fields = { key: 'five_hour', label: '5h', marker_rel: 0.5, dividers: [0.25] };
updateUsageBars([makeEntry(Object.assign({ pct_text: '10%' }, fields))]);
const container = els.usageBars.children[0].querySelector('.bar-container');
const before = {
    marker: container.querySelector('.bar-marker').style.left,
    divider: container.querySelector('.bar-divider').style.left,
};
updateUsageBars([makeEntry(Object.assign({ pct_text: '11%' }, fields))]);
const after = {
    marker: container.querySelector('.bar-marker').style.left,
    divider: container.querySelector('.bar-divider').style.left,
};
console.log(JSON.stringify({ before, after }));
''')
        self.assertEqual(result['after'], result['before'])

    def test_unchanged_field_set_updates_in_place(self):
        """With an unchanged field set, bars are updated in place (no rebuild)."""
        result = _run_scenario('''
updateUsageBars([makeEntry({ key: 'five_hour', label: '5h', pct_text: '10%' })]);
const barBefore = els.usageBars.children[0];
updateUsageBars([makeEntry({ key: 'five_hour', label: '5h', pct_text: '50%', fill_pct: 0.5 })]);
console.log(JSON.stringify({
    sameElement: els.usageBars.children[0] === barBefore,
    pct: els.usageBars.children[0].querySelector('.bar-pct').textContent,
    fillWidth: els.usageBars.children[0].querySelector('.bar-fill').style.width,
}));
''')
        self.assertEqual(result, {'sameElement': True, 'pct': '50%', 'fillWidth': '50%'})


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestAccountPlan(unittest.TestCase):
    """Tests for the optional plan details on the account row."""

    def test_plan_tooltip_is_plain_text_and_clears_without_details(self):
        result = _run_scenario('''
for (const name of ['accountSection', 'emailRow', 'emailValue', 'planRow', 'planValue',
    'usageSection', 'extraSection', 'installSection', 'headingUsage', 'statusSection']) {
    els[name] = document.createElement('div');
}
const details = 'Organization Type: Claude Max\\nRate Limit Tier: Default Claude Max 20x';
updateData({ profile: { email: '', plan: 'Ultra', plan_details: details } });
const claude = { plan: els.planValue.textContent, title: els.planValue.title };
updateData({ profile: null });
const signedOut = { visible: els.accountSection.classList.contains('visible'), title: els.planValue.title };
updateData({ profile: { email: '', plan: 'Plus' } });
const codex = { plan: els.planValue.textContent, title: els.planValue.title };
console.log(JSON.stringify({ claude, signedOut, codex }));
''')
        self.assertEqual(result, {
            'claude': {'plan': 'Ultra', 'title': 'Organization Type: Claude Max\nRate Limit Tier: Default Claude Max 20x'},
            'signedOut': {'visible': False, 'title': ''},
            'codex': {'plan': 'Plus', 'title': ''},
        })


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestManualRefresh(unittest.TestCase):
    """Tests for the popup refresh button's async request state."""

    def test_duplicate_click_suppressed_and_success_updates_immediately(self):
        result = _run_scenario('''
const refreshBtn = document.createElement('button');
document.getElementById = (id) => id === 'refreshBtn' ? refreshBtn : null;
translations = { refresh: 'Refresh' };
let resolveRefresh;
let calls = 0;
let updated = null;
globalThis.pywebview = { api: { refresh: () => {
    calls += 1;
    return new Promise((resolve) => { resolveRefresh = resolve; });
} } };
updateData = (data) => { updated = data; };
setupRefreshButton();
refreshBtn.click();
refreshBtn.click();
const loading = refreshBtn.disabled && refreshBtn.classList.contains('refreshing');
resolveRefresh({ status: { text: 'fresh' } });
setTimeout(() => console.log(JSON.stringify({
    calls, loading, updated, disabled: refreshBtn.disabled,
    refreshing: refreshBtn.classList.contains('refreshing'),
    title: refreshBtn.title, ariaLabel: refreshBtn['aria-label'],
})), 0);
''')
        self.assertEqual(result, {
            'calls': 1,
            'loading': True,
            'updated': {'status': {'text': 'fresh'}},
            'disabled': False,
            'refreshing': False,
            'title': 'Refresh',
            'ariaLabel': 'Refresh',
        })

    def test_wait_from_static_error_snapshot_blocks_click_then_expires(self):
        result = _run_scenario('''
const refreshBtn = document.createElement('button');
const refreshControl = document.createElement('span');
document.getElementById = (id) => ({ refreshBtn, refreshControl })[id];
els.statusSection = document.createElement('footer');
els.statusText = document.createElement('span');
translations = {
    refresh: 'Refresh', refresh_backoff: 'Rate limit: retry in {duration}', duration_s: '{s}s',
};
let calls = 0;
let now = 100_000;
Date.now = () => now;
globalThis.pywebview = { api: { refresh: async () => { calls += 1; } } };
updateData = () => {};
setupRefreshButton();
updateStatus({
    text: 'Provider unavailable', is_error: true,
    manual_refresh_reason: 'backoff', manual_refresh_retry_at: 115,
});
const waiting = { disabled: refreshBtn.disabled, title: refreshControl.title, status: els.statusText.textContent };
refreshBtn.click();
const callsWhileWaiting = calls;
now = 115_000;
tickStatusText();
const enabled = !refreshBtn.disabled;
refreshBtn.click();
clearInterval(textTimerId);
console.log(JSON.stringify({ waiting, enabled, callsWhileWaiting, calls }));
''')
        self.assertEqual(result, {
            'waiting': {'disabled': True, 'title': 'Rate limit: retry in 15s', 'status': 'Provider unavailable'},
            'enabled': True,
            'callsWhileWaiting': 0,
            'calls': 1,
        })

    def test_rejection_restores_button_without_replacing_data(self):
        result = _run_scenario('''
const refreshBtn = document.createElement('button');
document.getElementById = (id) => id === 'refreshBtn' ? refreshBtn : null;
translations = { refresh: 'Refresh' };
let rejectRefresh;
let updates = 0;
globalThis.pywebview = { api: { refresh: () => new Promise((_resolve, reject) => { rejectRefresh = reject; }) } };
updateData = () => { updates += 1; };
setupRefreshButton();
refreshBtn.click();
const loading = refreshBtn.disabled && refreshBtn.classList.contains('refreshing');
rejectRefresh(new Error('offline'));
setTimeout(() => console.log(JSON.stringify({
    loading, updates, disabled: refreshBtn.disabled,
    refreshing: refreshBtn.classList.contains('refreshing'),
})), 0);
''')
        self.assertEqual(result, {
            'loading': True,
            'updates': 0,
            'disabled': False,
            'refreshing': False,
        })


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestForecastChart(unittest.TestCase):
    """Tests for the quota forecast renderer and its normal-bar fallback."""

    def test_chart_replaces_bar_but_keeps_text_accessible(self):
        result = _run_scenario('''
translations = { forecast_now: 'Agora' };
updateUsageBars([makeEntry({
    key: 'seven_day', label: 'Weekly', pct_text: '50%', reset_text: 'Resets Thu',
    forecast: makeForecast({ runs_out: true, summary: 'At this pace: empty ~Mon' }),
})]);
const entry = els.usageBars.children[0];
const chart = entry.querySelector('.forecast-chart');
console.log(JSON.stringify({
    bar: !!entry.querySelector('.bar-container'),
    label: entry.querySelector('.bar-label').textContent,
    pct: entry.querySelector('.bar-pct').textContent,
    reset: entry.querySelector('.reset-text').textContent,
    summary: entry.querySelector('.forecast-summary').textContent,
    paths: forecastPaths(chart),
    localized: chart.children.some((node) => node.textContent === 'Agora'),
    hidden: chart.getAttribute('aria-hidden'),
}));
''')
        self.assertEqual(result, {
            'bar': False, 'label': 'Weekly', 'pct': '50%', 'reset': 'Resets Thu',
            'summary': 'At this pace: empty ~Mon', 'paths': ['assumed', 'actual', 'projection warn'],
            'localized': True, 'hidden': 'true',
        })

    def test_missing_or_invalid_forecast_keeps_bar(self):
        result = _run_scenario('''
const payloads = [undefined, null, {}, makeForecast({ projection: [[1, Infinity]] })];
console.log(JSON.stringify(payloads.map((forecast) => {
    updateUsageBars([makeEntry({ forecast })]);
    const entry = els.usageBars.children[0];
    return { bar: !!entry.querySelector('.bar-container'), chart: !!entry.querySelector('.forecast-chart') };
})));
''')
        self.assertEqual(result, [{'bar': True, 'chart': False}] * 4)

    def test_update_and_resize_keep_same_chart(self):
        result = _run_scenario('''
updateUsageBars([makeEntry({ forecast: makeForecast() })]);
const entry = els.usageBars.children[0];
const chart = entry.querySelector('.forecast-chart');
updateUsageBars([makeEntry({
    label: 'Updated label', pct_text: '60%',
    forecast: makeForecast({ projection: [], summary: 'Updated forecast' }),
})]);
const initialLine = chart.querySelector('.actual').getAttribute('d');
chart.clientWidth = 200;
const observer = observers.find((item) => item.targets.has(chart));
observer.callback([{ target: chart }]);
console.log(JSON.stringify({
    same: els.usageBars.children[0] === entry && entry.querySelector('.forecast-chart') === chart,
    label: entry.querySelector('.bar-label').textContent,
    pct: entry.querySelector('.bar-pct').textContent,
    summary: entry.querySelector('.forecast-summary').textContent,
    resized: chart.querySelector('.actual').getAttribute('d') !== initialLine,
    paths: forecastPaths(chart),
}));
''')
        self.assertEqual(result, {
            'same': True, 'label': 'Updated label', 'pct': '60%', 'summary': 'Updated forecast',
            'resized': True, 'paths': ['assumed', 'actual'],
        })

    def test_removing_forecast_releases_resize_observer(self):
        result = _run_scenario('''
updateUsageBars([makeEntry({ key: 'seven_day', forecast: makeForecast() })]);
const oldChart = els.usageBars.children[0].querySelector('.forecast-chart');
updateUsageBars([makeEntry({ key: 'seven_day' })]);
const bar = !!els.usageBars.children[0].querySelector('.bar-container');
updateUsageBars([makeEntry({ key: 'seven_day', forecast: makeForecast({
    actual: [[0, 0], [0.5, 50]], measured_from: 0.5,
}) })]);
const chart = els.usageBars.children[0].querySelector('.forecast-chart');
updateUsageBars([]);
console.log(JSON.stringify({
    bar, newChart: chart !== oldChart, paths: forecastPaths(chart), removed: els.usageBars.children.length === 0,
    detached: observers.every((observer) => !observer.targets.has(oldChart) && !observer.targets.has(chart)),
}));
''')
        self.assertEqual(result, {
            'bar': True, 'newChart': True, 'paths': ['assumed', 'projection'], 'removed': True, 'detached': True,
        })

    def test_queued_bar_animation_cannot_overwrite_newer_snapshot(self):
        result = _run_scenario('''
const frames = [];
globalThis.requestAnimationFrame = (callback) => frames.push(callback);
updateUsageBars([makeEntry({ forecast: makeForecast() })]);
updateUsageBars([makeEntry({ fill_pct: 0.2 })]);
updateUsageBars([makeEntry({ fill_pct: 0.7 })]);
for (const frame of frames) frame();
console.log(JSON.stringify(els.usageBars.children[0].querySelector('.bar-fill').style.width));
''')
        self.assertEqual(result, '70%')


if __name__ == '__main__':
    unittest.main()
