import { host, useValue, gatewayActivationEpoch, useGatewayActivationEpoch, ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk';
import { createElement as el, useEffect, useRef, useState } from 'react';

export const formatBytes = n => `${(Number(n || 0) / 1e9).toFixed(2)} GB`;
export const formatTarget = n => n >= 1e9 ? `${n / 1e9} GB` : n >= 1e6 ? `${n / 1e6} MB` : n >= 1e3 ? `${n / 1e3} KB` : `${n} B`;
const planSources = p => [...p.chosen, ...p.left_out.map(row => row.item)];
const ink = 'var(--ui-text)', muted = 'var(--ui-text-secondary)', brass = 'var(--ui-accent)', red = 'var(--ui-danger, var(--ui-text))';
const border = '1px solid var(--ui-border)';
const mono = { fontFamily: 'ui-monospace, SFMono-Regular, monospace', fontVariantNumeric: 'tabular-nums' };
const paths = {
  package: 'M3 7 12 3l9 4v10l-9 4-9-4V7Zm0 0 9 4 9-4M12 11v10M7 5l10 4',
  python: 'M5 9V5h10v7H7v7h12v-5M9 5v2M15 17v2M3 9h4M17 12h4',
  build: 'm4 19 7-7M14 4l6 6-4 4-6-6 4-4ZM3 16l5 5M15 3l6 6',
  model: 'M12 3 3 8v8l9 5 9-5V8l-9-5Zm0 0v18M3 8l18 8M21 8 3 16',
  container: 'M3 9h18v10H3V9Zm3-5h4v5M12 4h4v5M6 13h2m3 0h2m3 0h2',
};
function icon(source) {
  const family = ['ollama', 'lmstudio', 'huggingface'].includes(source) ? 'model' :
    ['pip', 'uv'].includes(source) ? 'python' : ['npm', 'pnpm', 'yarn', 'cocoapods'].includes(source) ? 'package' : source === 'docker' ? 'container' : 'build';
  return el('svg', { viewBox: '0 0 24 24', width: 26, height: 26, fill: 'none', stroke: 'currentColor', strokeWidth: 1.4, 'aria-hidden': true }, el('path', { d: paths[family] }));
}

function Waterline({ free, projected, actual, total }) {
  const ratio = Math.max(0, Math.min(1, (free + projected) / (total || 1)));
  const y = 122 - ratio * 92;
  return el('figure', { style: { margin: 0, border, padding: 20, background: 'var(--ui-bg-secondary)', borderRadius: 8 } },
    el('svg', { viewBox: '0 0 600 155', role: 'img', 'aria-label': `${formatBytes(free)} free; ${formatBytes(projected)} projected release; ${actual == null ? 'no completed cleanup' : formatBytes(actual) + ' actually released'}`, style: { width: '100%', maxHeight: 180, color: brass } },
      el('path', { d: `M0 ${y}H600V150H0Z`, fill: 'currentColor', opacity: .12 }),
      el('path', { d: `M0 ${y}H600`, stroke: 'currentColor', strokeWidth: 2 }),
      el('circle', { cx: 300, cy: 75, r: 24, stroke: 'currentColor', fill: 'none', strokeWidth: 2 }),
      el('path', { d: 'M260 75h80M300 20v110M353 35h35m-35 20h25m-25 20h35m-35 20h25m-25 20h35', stroke: 'currentColor', fill: 'none', strokeWidth: 2 }),
      el('text', { x: 15, y: 24, fill: 'currentColor', fontSize: 12, style: mono }, 'PLIMSOLL / FREE SPACE'),
      el('text', { x: 15, y: 144, fill: 'currentColor', fontSize: 12, style: mono }, `${(ratio * 100).toFixed(1)}% FREE AFTER PLAN`)),
    el('figcaption', { style: { display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16, ...mono } },
      el('span', null, `${formatBytes(free)} free now`),
      el('span', null, `+${formatBytes(projected)} projected`),
      el('span', null, actual == null ? 'Actual: awaiting cleanup' : `${formatBytes(actual)} actual release`)));
}

function BallastPage({ ctx }) {
  const profile = useValue(host.state.profile) || 'default';
  const [state, setState] = useState(null), [scan, setScan] = useState(null), [plan, setPlan] = useState(null);
  const [target, setTarget] = useState('15 GB'), [excluded, setExcluded] = useState([]), [optional, setOptional] = useState([]);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('Ready to inspect known developer caches.');
  const scope = useRef(''), requestId = useRef(0), live = useRef(true), current = useRef(null);
  const edited = useRef(false), visiblePlanId = useRef(null);
  const epoch = useGatewayActivationEpoch();
  const readScope = () => `${host.state.profile.get() || 'default'}:${gatewayActivationEpoch()}`;
  current.current = { plan, busy, excluded, optional, target, scope: `${profile}:${epoch}` };
  async function call(path, body) {
    const captured = readScope(), id = ++requestId.current;
    setBusy(true);
    try {
      const reply = await ctx.rest(path, body === undefined ? undefined : { method: 'POST', body });
      if (!live.current || id !== requestId.current || captured !== readScope()) return null;
      if (!reply.ok) throw new Error(reply.error?.message || 'Request refused');
      return reply;
    } catch (error) {
      if (live.current && id === requestId.current && captured === readScope()) setMessage(error.message || 'Backend unavailable. Enable Ballast and restart the gateway.');
      return null;
    } finally {
      if (live.current && id === requestId.current && captured === readScope()) setBusy(false);
    }
  }
  useEffect(() => {
    live.current = true;
    scope.current = `${profile}:${epoch}`;
    edited.current = false; visiblePlanId.current = null;
    ++requestId.current;
    setState(null); setPlan(null); setScan(null); setExcluded([]); setOptional([]); setBusy(false);
    let stopped = false;
    const refresh = async () => {
      const captured = scope.current;
      try {
        const reply = await ctx.rest('/status');
        if (stopped || captured !== readScope()) return;
        if (!reply.ok) { setMessage(reply.error?.message || 'Backend unavailable.'); return; }
        setState(reply);
        if (!edited.current && reply.last_plan?.ok && reply.last_plan.id !== visiblePlanId.current) {
          const p = reply.last_plan;
          visiblePlanId.current = p.id; setPlan(p); setTarget(formatTarget(p.target_bytes));
          const sources = planSources(p);
          setScan({ sources, free_bytes: reply.free_bytes, total_bytes: reply.total_bytes });
          setExcluded(p.exclude || p.left_out.filter(row => row.reason === 'Excluded by you.').map(row => row.item.id));
          setOptional(p.include_optional || sources.filter(item => item.optional && (p.chosen.includes(item) || p.left_out.some(row => row.item.id === item.id && row.reason.startsWith('Kept:')))).map(item => item.id));
        }
      } catch (_) { if (!stopped && captured === readScope()) setMessage('Backend unavailable. Enable the Python plugin and restart the gateway.'); }
    };
    refresh();
    const dispose = ctx.setInterval(refresh, 5000);
    return () => { stopped = true; live.current = false; ++requestId.current; if (typeof dispose === 'function') dispose(); };
  }, [profile, epoch]);
  async function inspect() {
    if (current.current.busy) return;
    edited.current = true;
    setPlan(null);
    const reply = await call('/scan', {});
    if (reply) { setScan(reply); setMessage('Inspection complete. Model stores stay excluded until you opt in.'); }
  }
  async function makePlan() {
    const c = current.current;
    if (c.busy) return;
    edited.current = true;
    setPlan(null);
    const reply = await call('/plan', { target_bytes: c.target, exclude: c.excluded, include_optional: c.optional });
    if (reply) { edited.current = false; visiblePlanId.current = reply.id; setPlan(reply); setScan({ sources: planSources(reply), free_bytes: reply.free_before, total_bytes: reply.total_bytes }); setMessage(reply.reachable ? 'Plan ready. Review its paths and rebuild costs before requesting approval.' : `Target unreachable. Shortfall: ${formatBytes(reply.shortfall_bytes)}. Lower the target or change exclusions.`); }
  }
  function toggle(item, checked) {
    edited.current = true;
    setPlan(null);
    const expand = values => items.filter(row => values.includes(row.id) || values.includes(row.source_id)).map(row => row.id);
    if (item.optional) setOptional(value => checked ? [...expand(value).filter(id => id !== item.id), item.id] : expand(value).filter(id => id !== item.id));
    else setExcluded(value => checked ? expand(value).filter(id => id !== item.id) : [...expand(value).filter(id => id !== item.id), item.id]);
    setMessage('Selection changed. Build a new signed plan.');
  }
  async function approve() {
    const c = current.current, p = c.plan;
    if (c.busy || !p?.reachable || c.scope !== readScope() || Date.now() / 1000 >= p.expires_at) { setMessage('Plan is unavailable or expired. Build it again.'); return; }
    const command = 'Please run the ballast_apply tool with exactly these arguments: ' + JSON.stringify({ plan_token: p.plan_token, dry_run: false }) + '. Show me Hermes’s normal approval prompt for this signed plan before deleting its caches.';
    const accepted = await host.composer.setDraft(null, command);
    if (live.current && c.scope === readScope()) setMessage(accepted ? 'Approval request placed in your Hermes composer. Send it, then answer Hermes’s confirmation. Nothing has been deleted by this button.' : 'Open a Hermes chat in this profile, then use Approve in Hermes again.');
  }
  const button = (label, onClick, disabled = busy) => el('button', { type: 'button', disabled, onClick, style: { padding: '10px 16px', border, borderRadius: 5, background: 'var(--ui-bg-secondary)', color: ink, cursor: disabled ? 'default' : 'pointer' } }, label);
  const items = scan?.sources || (plan ? [...plan.chosen, ...plan.left_out.map(row => row.item)] : []);
  const completed = state?.ledger?.filter(row => row.event === 'completed').at(-1);
  const validPlan = plan && (!state?.scan_home || plan.scan_home === state.scan_home) && plan.expires_at > Date.now() / 1000 && !state?.ledger?.some(row => row.event === 'started' && row.plan_id === plan.id);
  const home = state?.scan_home ? state : scan?.scan_home ? scan : plan;
  return el('main', { style: { maxWidth: 1080, margin: 'auto', padding: '30px clamp(16px, 4vw, 44px)', color: ink, lineHeight: 1.6 } },
    el('style', null, '.ballast-row:focus-within{outline:2px solid var(--ui-accent);outline-offset:3px} .ballast-path{overflow-wrap:anywhere} .ballast-table{width:100%;border-collapse:collapse} .ballast-table td,.ballast-table th{text-align:left;padding:12px 8px;border-bottom:1px solid var(--ui-border)}'),
    el('header', { style: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, borderBottom: border, paddingBottom: 20 } },
      el('div', null, el('p', { style: { ...mono, color: brass, letterSpacing: '.18em', fontSize: 12, margin: 0 } }, 'DEVELOPER CACHE / REGRET SOLVER'),
        el('h1', { style: { fontFamily: 'Georgia, serif', fontSize: 48, fontWeight: 400, margin: '0 0 2px' } }, 'Ballast'),
        el('p', { style: { color: muted, margin: 0 } }, 'Make room. Keep the work that costs the most to rebuild.')),
      el('span', { style: mono }, profile)),
    el('p', { className: 'ballast-path', style: mono }, home?.scanning || 'Scanning: awaiting backend',
      home?.demo_home ? el('strong', { style: { marginLeft: 12, color: brass, border, padding: '2px 8px' } }, 'DEMO HOME') : null),
    el('section', { 'aria-label': 'Free-space waterline', style: { margin: '24px 0' } }, el(Waterline, { free: state?.free_bytes || scan?.free_bytes || 0, total: state?.total_bytes || scan?.total_bytes || 1, projected: validPlan ? plan.projected_freed : 0, actual: completed?.actual_freed })),
    el('form', { onSubmit: e => { e.preventDefault(); makePlan(); }, style: { display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'end' } },
      el('label', null, el('span', { style: { display: 'block', color: muted } }, 'I need'),
        el('input', { value: target, onChange: e => { edited.current = true; setTarget(e.target.value); setPlan(null); }, placeholder: '15 GB', required: true, disabled: busy, style: { padding: 10, width: 160, border, borderRadius: 5, background: 'var(--ui-bg)', color: ink, ...mono }, 'aria-label': 'Space to reclaim, for example 15 GB' })),
      button('Inspect caches', inspect), button('Build least-regret plan', makePlan)),
    el('p', { role: 'status', 'aria-live': 'polite', style: { minHeight: 28, color: muted } }, busy ? 'Inspecting allocated bytes…' : message),
    el('h2', { style: { fontFamily: 'Georgia, serif', fontWeight: 400 } }, 'What can go overboard'),
    !items.length ? el('p', null, 'Inspect caches to see sizes, recent use and regeneration costs. Personal folders are outside the catalog.') :
      el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))', gap: 12 } }, ...items.map(item =>
        el('label', { key: item.id, className: 'ballast-row', style: { border, padding: 16, borderRadius: 6, display: 'block', opacity: item.eligible ? 1 : .75 } },
          el('div', { style: { display: 'flex', gap: 12, alignItems: 'center' } }, icon(item.source_id),
            el('input', { type: 'checkbox', disabled: busy || !item.eligible, checked: item.optional ? optional.includes(item.id) || optional.includes(item.source_id) : !excluded.includes(item.id) && !excluded.includes(item.source_id), onChange: e => toggle(item, e.target.checked), 'aria-label': `${item.optional ? 'Opt into expensive model deletion: ' : 'Include '}${item.label} ${item.id}` }),
            el('strong', null, item.label), el('span', { style: { marginLeft: 'auto', ...mono } }, formatBytes(item.size_bytes))),
          el('p', { className: 'ballast-path', style: { ...mono, fontSize: 12, color: muted } }, item.path),
          el('div', null, `${item.regen_minutes} min rebuild · ${item.regen_download_class} download · ${Math.round(item.confidence * 100)}% confidence`),
          el('div', { style: { fontSize: 13, color: muted } }, `Last used (uncertain): ${item.last_used ? new Date(item.last_used * 1000).toLocaleDateString() : 'unknown'}`),
          el('p', { style: { fontSize: 13, marginBottom: 0 } }, item.recipe),
          item.optional ? el('p', { style: { color: red } }, 'Expensive model store. Explicit opt-in required.') : null,
          item.reasons?.length ? el('p', { style: { fontSize: 13 } }, item.reasons.join(' ')) : null))),
    plan ? el('section', { 'aria-label': 'Signed plan', style: { marginTop: 30, borderTop: border, paddingTop: 15 } },
      el('h2', null, 'The drop list'),
      el('p', { style: mono }, `${formatBytes(plan.projected_freed)} / ${formatBytes(plan.target_bytes)} requested · regret ${plan.total_regret}`),
      !plan.reachable ? el('p', { role: 'status', style: { color: red, ...mono } }, `Target unreachable. Maximum reclaimable: ${formatBytes(plan.max_reclaimable_bytes)}. Shortfall: ${formatBytes(plan.shortfall_bytes)}. Choose a smaller target.`) : null,
      ...plan.chosen.map(item => el('details', { key: item.id }, el('summary', null, `${item.label} · ${formatBytes(item.size_bytes)} · ${item.regen_minutes} min rebuild`),
        el('p', { className: 'ballast-path', style: mono }, item.path), el('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }, JSON.stringify(item.action, null, 2)))),
      el('p', { style: { color: red } }, 'Permanent deletion. No Trash. Recipes rebuild caches; they cannot undo this action.'),
      button('Approve in Hermes', approve, busy || !validPlan || !plan.reachable),
      el('p', { style: { color: muted, fontSize: 13 } }, `Expires ${new Date(plan.expires_at * 1000).toLocaleTimeString()}. This button prepares a request in your chat; Hermes asks for a fresh human confirmation.`),
      el('details', null, el('summary', null, `Kept aboard (${plan.left_out.length})`),
        el('ul', null, ...plan.left_out.map(row => el('li', { key: row.item.id }, `${row.item.label}: ${row.reason}`))))) : null,
    completed ? el('section', null, el('h2', null, 'Last release'), el('p', { style: mono }, `${formatBytes(completed.projected_freed)} projected / ${formatBytes(completed.actual_freed)} measured`), el('p', { className: 'ballast-path' }, `Rebuild recipes: ${completed.recipes}`), !completed.ok ? el('p', { style: { color: red } }, 'Cleanup stopped early. Inspect the ledger before planning again.') : null) : null,
    el('footer', { style: { marginTop: 36, borderTop: border, color: muted, paddingTop: 15, fontSize: 13 } },
      el('p', null, 'Allocated space is an estimate. APFS clones and snapshots may retain blocks. Last-used times are uncertain. Shared hardlinks are conservatively excluded. No network requests or model downloads.'),
      el('p', null, 'Docker is informational only: ', scan?.docker?.stdout || scan?.docker?.reasons?.join(' ') || 'Inspect to check CLI availability.')));
}

export default {
  id: 'ballast', name: 'Ballast', defaultEnabled: false,
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: '/ballast' }, render: () => el(BallastPage, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/ballast', label: 'Ballast' }, render: () => icon('go-build') },
    ]);
  },
};
