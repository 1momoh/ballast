// Real React server rendering with a small SDK fixture; this is not native Desktop proof.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const desktop = '/Users/a87/Projects/PeelHere/tmp/compatibility/hermes-agent-ad4fa2f47cb689d4ca4a6ee465ab8d152b46cc73/apps/desktop';
const require = createRequire(desktop + '/package.json');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const source = fs.readFileSync(root + 'plugin/ballast/desktop/plugin.js', 'utf8');
const imports = [...source.matchAll(/from\s+['"]([^'"]+)['"]/g)].map(match => match[1]);
assert.deepEqual(imports.sort(), ['@hermes/plugin-sdk', 'react']);
assert.doesNotMatch(source, /\beval\s*\(|new\s+Function\b|\bimport\s*\(/);
const sdk = {
  host: { state: { profile: { get: () => 'fake-profile' } }, composer: { setDraft: async () => false } },
  useValue: atom => atom.get(), gatewayActivationEpoch: () => 1, useGatewayActivationEpoch: () => 1,
  ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar.nav',
};
const context = vm.createContext({ console, Date, Math, JSON });
const modules = new Map();
for (const [name, exports] of [['@hermes/plugin-sdk', sdk], ['react', React]]) {
  modules.set(name, new vm.SyntheticModule(Object.keys(exports), function () {
    for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
  }, { context }));
}
const plugin = new vm.SourceTextModule(source, { context });
await plugin.link(name => { assert.ok(modules.has(name), `unexpected import ${name}`); return modules.get(name); });
await plugin.evaluate();
const exported = plugin.namespace;
assert.equal(exported.formatBytes(15000000000), '15.00 GB');
assert.equal(exported.formatBytes(-1000000000), '-1.00 GB');
assert.equal(exported.formatTarget(15000000000), '15 GB');
assert.equal(exported.formatTarget(1500000), '1.5 MB');
let contributions;
exported.default.register({ registerMany: value => { contributions = value; } });
assert.equal(contributions.length, 2);
assert.equal(contributions[0].data.path, '/ballast');
const page = contributions[0].render();
const html = renderToStaticMarkup(page);
assert.match(html, /Ballast/);
assert.match(html, /PLIMSOLL/);
assert.match(html, /role="status"/);
assert.match(html, /aria-label="Space to reclaim/);
assert.match(html, /Inspect caches/);
assert.match(html, /Personal folders are outside the catalog/);
assert.match(html, /Scanning: awaiting backend/);
assert.doesNotMatch(html, /<canvas|<iframe|<script/);
fs.writeFileSync(root + 'evidence/desktop-render.html', '<!doctype html><meta charset="utf-8">' + html);

// Exercise the real page's handlers with deterministic state/effect hooks, without native UI.
let slots = [], cursor = 0, effects = [], intervals = [], calls = [], currentProfile = 'fake-profile';
const hooks = {
  ...React,
  useState(initial) {
    const index = cursor++;
    if (!(index in slots)) slots[index] = initial;
    return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
  },
  useRef(initial) {
    const index = cursor++;
    if (!(index in slots)) slots[index] = { current: initial };
    return slots[index];
  },
  useEffect(effect, deps) {
    const index = cursor++, old = slots[index];
    if (!old || deps.some((value, i) => value !== old.deps[i])) {
      old?.dispose?.();
      slots[index] = { deps };
      effects.push(() => { slots[index].dispose = effect(); });
    }
  },
};
const hookContext = vm.createContext({ console, Date, Math, JSON });
const fixtureSdk = { ...sdk, host: { ...sdk.host, state: { profile: { get: () => currentProfile } } } };
const fixtures = new Map();
for (const [name, values] of [['@hermes/plugin-sdk', fixtureSdk], ['react', hooks]]) {
  fixtures.set(name, new vm.SyntheticModule(Object.keys(values), function () {
    for (const [key, value] of Object.entries(values)) this.setExport(key, value);
  }, { context: hookContext }));
}
const interactive = new vm.SourceTextModule(source, { context: hookContext });
await interactive.link(name => fixtures.get(name));
await interactive.evaluate();
const npm = { id: 'npm', source_id: 'npm', label: 'npm packages', eligible: true, size_bytes: 2e9, confidence: .95, reasons: [] };
const model = { ...npm, id: 'ollama', source_id: 'ollama', label: 'Ollama', optional: true };
const project = { ...npm, id: 'xcode-derived:Active', source_id: 'xcode-derived', label: 'Xcode Active' };
const hydrated = { ok: true, id: 'signed-plan', target_bytes: 15e9, chosen: [npm],
  scan_home: '/demo/home', scanning: 'Scanning: /demo/home', demo_home: true,
  left_out: [{ item: model, reason: 'Kept: target met with a lower total regeneration regret.' }, { item: project, reason: 'Excluded by you.' }],
  include_optional: ['ollama'], exclude: ['xcode-derived'], reachable: true, expires_at: Date.now() / 1000 + 900 };
let statusReply = { ok: true, last_plan: hydrated, free_bytes: 30e9, total_bytes: 100e9, ledger: [],
  scan_home: '/demo/home', scanning: 'Scanning: /demo/home', demo_home: true };
const ctx = {
  rest: async (path, options) => { calls.push([path, options]); return path === '/status' ? statusReply : { ...hydrated, id: 'rebuilt' }; },
  setInterval: callback => { intervals.push(callback); return () => { intervals = intervals.filter(value => value !== callback); }; },
  registerMany: value => { contributions = value; },
};
interactive.namespace.default.register(ctx);
const component = contributions[0].render();
const render = () => { cursor = 0; return component.type(component.props); };
const flush = async () => { while (effects.length) effects.shift()(); await Promise.resolve(); await Promise.resolve(); };
const descendants = (element, predicate) => {
  if (!element || typeof element !== 'object') return [];
  const children = [element.props?.children].flat(Infinity);
  return [...(predicate(element) ? [element] : []), ...children.flatMap(child => descendants(child, predicate))];
};
const inputs = tree => descendants(tree, e => e.type === 'input');
const checkbox = (tree, id) => inputs(tree).find(e => e.props.type === 'checkbox' && e.props['aria-label'].endsWith(id));
render(); await flush();
let tree = render();
assert.match(renderToStaticMarkup(tree), /Scanning: \/demo\/home/);
assert.match(renderToStaticMarkup(tree), /DEMO HOME/);
assert.equal(descendants(tree, e => e.type === 'button' && e.props.children === 'Approve in Hermes')[0].props.disabled, false);
assert.equal(inputs(tree).find(e => e.props.type !== 'checkbox').props.value, '15 GB');
assert.equal(checkbox(tree, 'ollama').props.checked, true, 'left-out model opt-in survives hydration');
assert.equal(checkbox(tree, 'xcode-derived:Active').props.checked, false, 'family exclusions hydrate');
checkbox(tree, 'npm').props.onChange({ target: { checked: false } });
tree = render();
assert.equal(inputs(tree).filter(e => e.props.type === 'checkbox').length, 3, 'toggle must not blank hydrated cards');
assert.equal(checkbox(tree, 'npm').props.checked, false);
assert.equal(checkbox(tree, 'ollama').props.checked, true);
await intervals[0](); tree = render();
assert.equal(checkbox(tree, 'npm').props.checked, false, 'poll must not clobber edits');
checkbox(tree, 'xcode-derived:Active').props.onChange({ target: { checked: true } });
tree = render();
const build = descendants(tree, e => e.type === 'button' && e.props.children === 'Build least-regret plan')[0];
await build.props.onClick(); tree = render();
const body = calls.find(([path]) => path === '/plan')[1].body;
assert.equal(body.target_bytes, '15 GB');
assert.equal(JSON.stringify(body.include_optional), '["ollama"]');
assert.equal(JSON.stringify(body.exclude), '["npm"]');
checkbox(tree, 'npm').props.onChange({ target: { checked: true } });
tree = render();
assert.equal(inputs(tree).filter(e => e.props.type === 'checkbox').length, 3, 'newly planned cards also survive toggles');
currentProfile = 'other-profile'; statusReply = { ok: true, last_plan: null, ledger: [] };
render(); await flush(); tree = render();
assert.equal(inputs(tree).filter(e => e.props.type === 'checkbox').length, 0, 'profile switch clears old caches');
statusReply = { ok: true, last_plan: { ...hydrated, id: 'unreachable', reachable: false,
  projected_freed: 2e9, max_reclaimable_bytes: 2e9, shortfall_bytes: 13e9 }, ledger: [] };
await intervals[0](); tree = render();
const unreachableHtml = renderToStaticMarkup(tree);
assert.match(unreachableHtml, /Target unreachable\. Maximum reclaimable: 2\.00 GB\. Shortfall: 13\.00 GB/);
assert.equal(descendants(tree, e => e.type === 'button' && e.props.children === 'Approve in Hermes')[0].props.disabled, true);
console.log('PASS: import restriction, no code loaders, byte/target formatting, SDK contributions, real React SSR, accessible empty state; hydrated toggles, left-out optional IDs, family exclusions, edited polling, replanning, profile reset, unreachable maximum/shortfall and disabled approval (13 check groups).');
