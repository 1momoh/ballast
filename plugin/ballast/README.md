# Ballast

Reclaim developer cache space with the least regeneration regret. Ask Hermes **“I need 15 GB”**, inspect a signed plan, then confirm its permanent cleanup through Hermes.

Ballast 0.1.0 is a macOS Hermes plugin requiring Hermes >=0.23.0. Author: **1momoh <alaminmomoh@gmail.com>**. MIT licensed.

## Tools and workflow

1. `ballast_scan({})` inspects only the closed cache catalog below. It reports allocated file bytes, uncertain last-used time, regeneration minutes, download class, rebuild recipe, confidence and eligibility reasons. Missing caches are reported, not created. Docker is a separate information-only report.
2. `ballast_plan({"target_bytes":"15 GB","exclude":["xcode-derived"],"include_optional":[]})` selects the exact minimum total integer regret among eligible candidates of at least 1 MB (1,000,000 allocated bytes). Smaller caches stay in `left_out` with a planning-floor reason. Root IDs can exclude an entire family; returned item IDs can exclude individual stores/models. GB is decimal; GiB is binary. An unreachable target returns the available set, `max_reclaimable_bytes` (the sum of selectable candidates after exclusions, opt-in and floor), and `shortfall_bytes` (target minus projected bytes, bounded at zero), and cannot be applied until you choose a reachable target.
3. `ballast_apply({"plan_token":"…"})` defaults to **dry-run** and returns exact root paths and actions. It never requests deletion approval or modifies cache contents.
4. A normal Hermes tool call to `ballast_apply({"plan_token":"…","dry_run":false})` requests a fresh human confirmation. Confirm in the host's own approval interface. Denial, timeout, missing approval hooks, cron, unattended operation, automatic approval modes and direct handler dispatch cannot supply a valid human receipt. A new unpredictable approval rule is used on every attempt; even a prior “always” answer does not authorize a later cleanup.
5. `ballast_ledger({})` reads full durable history and recipe locations. `ballast_status({})` returns the latest started/completed summaries, current disk space and the latest plan or its expiry/consumed reason. Status polling verifies a separately signed public summary, lifetime and plan-file metadata without rereading file inventories or full history. Older local state migrates once. Preview/apply still verify the complete signed plan and revalidate snapshots.

`/ballast 15 GB` is a deterministic planning shortcut. `/ballast {"action":"apply","args":{"plan_token":"…"}}` previews. Slash-command dispatch in the pinned runtime calls handlers without the normal pre-tool gate; real cleanup through that shortcut is deliberately refused. Use the normal Hermes tool flow for a real apply.

Regret is `ceil(10 × regeneration_minutes + download_MB / 100 + recency + 100 × (1 − confidence))`, at least 1. Recency adds 100 for use within a day, 45 within a week, 15 within 30 days, otherwise 0. Catalog costs/confidence are estimates. An exact dynamic program minimizes the sum of these integer scores; stable IDs break ties deterministically. It does not claim to minimize elapsed rebuild time or overshoot among equal-regret sets.

The Desktop page shows per-source selection toggles, expensive-model opt-in, regeneration costs, confidence, uncertain last-used dates, the signed drop list, reasons for keeping other sources and a free-space waterline. **Approve in Hermes** prepares a normal tool request in your active chat composer. Send it and answer Hermes's subsequent confirmation. The button never deletes anything itself. If a model/chat is unavailable, the request cannot run. Plans created by tools appear in the same profile's pane; local selection edits require a new plan.

## What Ballast does to your machine

**Cache deletion is permanent.** Ballast does not use Trash: moving files to same-volume Trash frees zero bytes. Rebuild recipes recreate caches; they do not restore their exact previous contents. Close builds/package managers using a selected cache before planning. An active tool can change a cache and invalidate the plan, or encounter missing cache files after an approved cleanup.

By default, only these roots below the process's actual HOME are cataloged. For a disclosed demo, the supported plugin setting below can select a different home. Tool arguments cannot add paths or override the setting:

```yaml
plugins:
  entries:
    ballast:
      settings:
        scan_home: /Users/<you>/BallastDemoHome
```

An empty `scan_home` uses actual HOME. The setting appears in **Settings → Plugins → Ballast**, also reachable through the gear in **Capabilities → Plugins**. Ballast resolves its realpath and refuses missing, relative, non-directory, other-owner, system, personal and Hermes data paths. The personal-folder denylist applies beneath both the chosen home and actual HOME. All catalog roots remain relative to the chosen home; real HOME's personal directories stay protected. Symlink escapes remain refused. Every scan, plan and status reports **Scanning: &lt;resolved path&gt;** and `demo_home`; the Desktop pane shows a **DEMO HOME** badge when it differs from actual HOME. The complete signed plan binds both homes; changing either invalidates prior plans and their status summaries. Old plans lacking this binding must be recreated. This setting changes the cleanup target, so review the displayed path before approval. It does not redirect Hermes's own data or credentials.

| Source | Allowed roots relative to HOME | Rebuild |
| --- | --- | --- |
| npm | `.npm/_cacache` | `npm install` |
| pnpm | `Library/pnpm/store`, `.pnpm-store` | `pnpm install` |
| Yarn | `Library/Caches/Yarn` | `yarn install` |
| pip | `Library/Caches/pip` | Install project requirements again |
| uv | `.cache/uv` | `uv sync` |
| Cargo | `.cargo/registry/cache`, `.cargo/registry/src`, `.cargo/git/checkouts` | `cargo fetch`, `cargo build`; installed `.cargo/bin` tools are untouched |
| Homebrew downloads | `Library/Caches/Homebrew` | `brew fetch <formula>` |
| Xcode DerivedData | `Library/Developer/Xcode/DerivedData/*`, individual project directories | Rebuild in Xcode |
| Xcode device support | `Library/Developer/Xcode/iOS DeviceSupport/*`, individual device/version directories | Reconnect a device with matching Xcode |
| CoreSimulator caches | `Library/Developer/CoreSimulator/Caches` | Relaunch Simulator; device data/runtimes are outside the catalog |
| HuggingFace hub | `.cache/huggingface/hub/models--*`, `datasets--*`, `spaces--*`, individually | Download the named model/dataset/space again |
| Gradle | `.gradle/caches` | `./gradlew build` |
| CocoaPods | `Library/Caches/CocoaPods` | `pod install` |
| Go | `Library/Caches/go-build`, `go/pkg/mod` | `go build`, `go mod download` |
| Ollama — explicit opt-in | `.ollama/models` | `ollama pull <model>` |
| LM Studio — explicit opt-in | `.lmstudio/models`, `Library/Application Support/LM Studio/models` | Download models again in LM Studio |

Personal folders, iCloud Mobile Documents, keychains, SSH/GPG data, Hermes data, Mail, Messages, Photos, `/`, HOME itself are refused by Ballast’s own registry allowlist and protected-path denylist. Custom cache locations and environment overrides such as `HF_HOME` are intentionally outside the catalog. Symlink roots, absolute or lexically escaping link targets, dataless iCloud stubs and other volumes make a candidate ineligible. Relative links wholly inside one candidate, including chained framework links and internal loops, can be unlinked; targets are never followed for sizing or deletion. Sockets/FIFOs and other special files are skipped and reported, remain in their original directories, and do not prevent ordinary cache files from being reclaimed. Approved deletion restores owner write permission on open directory descriptors, including read-only Go module directories. Descriptor traversal checks volume/inode identity and never follows child symlinks; Ballast’s protected-path checks remain active per entry.

pnpm stores preserve each immediate `v<number>/projects` registry (including v10/v11): Ballast never opens, sizes, snapshots, stages, follows or deletes its entries. All other store contents retain the normal escape refusal and snapshot checks. The action explicitly lists `v*/projects` as preserved. [pnpm’s official store documentation](https://pnpm.io/cli/store#prune) says `store prune` removes unreferenced packages; current documentation also describes walking registered projects for global virtual store garbage collection. Ballast therefore uses bounded content deletion instead of pruning or promising whole-store bytes from a prune. Its estimate excludes registries, directory metadata and shared hardlinks. This can remove reusable package content, so later installs may download/rebuild it; project registry links and their targets remain untouched. This choice supersedes the earlier pnpm staged-prune implementation.

Xcode IDs include the project/device directory name, for example `xcode-derived:MyApp-abc`. Exclude an individual ID to keep an active project, or `xcode-derived` to keep the whole family. Loose files in the parent DerivedData/DeviceSupport folders are outside these candidates. Writes inside an unselected project do not invalidate another project's signed snapshot. Selected projects still require zero drift.

Sizes use allocated **file** bytes (`st_blocks * 512`), conservatively omitting directory metadata. Hardlinks count once only when every link is inside that same candidate; external or cross-candidate links count zero. APFS clones, local snapshots, delayed accounting and simultaneous disk activity mean measured free space can differ from the projection, including a negative measured change. Last-used time is max(atime, mtime) over regular-file metadata; noatime/relatime and copied timestamps make it uncertain. Inspection reads names/metadata, not cache file contents.

Plans expire after 15 minutes. A private random local HMAC-SHA256 key signs the complete plan, exact paths, allocated sizes, root/entry inode/device/mode/mtime/link-count/flags snapshot, relative link text, executable identities and actions. There is **zero drift tolerance**. The complete selected set is revalidated before execution and again after the human wait. A consumed token cannot be replayed. A process lock serializes Ballast state mutations; each candidate is checked again immediately before cleanup. This is not a filesystem transaction: if a cache changes during cleanup or a command fails, an already completed action cannot be rolled back. Execution stops on the first failure and records partial results.

### Commands it may run

Executables are resolved with `shutil.which`, fixed to absolute real paths and bound into the plan. Commands use argv lists, no shell, no stdin, captured output and a 120-second timeout. Node shebangs and JS entry extensions use a separately resolved, snapshot-bound Node executable; native package managers and shell/version-manager launchers are invoked directly. For pip Python shebangs, the fixed interpreter is also bound into the plan. A simple `env python3` shebang prefers the adjacent executable, then a resolved interpreter; Python venv symlink paths are preserved. Missing/unsupported env interpreters fall back to bounded deletion. The sanitized PATH stays restricted to system directories. Offline/config-isolation settings and a private command HOME prevent reading your normal tool config or requesting downloads.

After approval, the scoped native cleaner runs against the original cache before any staging. npm uses separate empty user and global config files in the private command HOME. A successful cleaner that empties or removes the root records `native clean ok` without staging. pip's “No matching packages” exit is treated as success when the cache is empty. A successful command that leaves contents reports them as retained and does not stage them. If the cleaner returns nonzero, times out or cannot launch, only unchanged approved leftovers move into private, same-volume staging for descriptor-relative deletion. The ledger retains the command result and reports the fallback neutrally. New top-level cache writes stay untouched; changes within approved leftovers or unsafe entries stop execution. Special-file candidates use direct deletion so skipped entries remain at their original paths.

Here `CACHE` is the original scoped cache path and `COMMAND_HOME` is private under Ballast's plugin data directory; the dry-run gives exact argv:

| Cleaner | Scoped command |
| --- | --- |
| npm | `[NODE] NPM --cache CACHE --logs-dir COMMAND_HOME/npm-logs --userconfig COMMAND_HOME/npm-user.conf --globalconfig COMMAND_HOME/npm-global.conf cache clean --force` (`CACHE` is the parent of the approved `_cacache` root) |
| pnpm | No cleaner command: descriptor-relative deletion, preserving `v<number>/projects` in place |
| Yarn classic | `[NODE] YARN --no-default-rc --offline --cache-folder CACHE cache clean` |
| pip / pip3 | `[PYTHON] PIP --isolated --cache-dir CACHE cache purge` |
| uv | `UV --no-config --cache-dir CACHE cache clean` |
| Go build | `GO clean -cache` with `GOCACHE=CACHE`, `GOENV=off`, `GOTOOLCHAIN=local`, offline proxy/sum settings |
| Go modules | `GO clean -modcache` with `GOMODCACHE=CACHE` and the same isolation settings |
| Docker — read-only | `DOCKER system df --format '{{json .}}'`; raw reclaimable figures are reported, never included in a cleanup plan |

If an available cleaner cannot be strictly scoped, or its prerequisites/same-volume staging are unavailable, Ballast uses descriptor-relative deletion of validated directory contents. `brew cleanup -s` also touches installed packages, so it is **never** run; only the cataloged Homebrew download contents can be removed. No mutating Docker command runs: aggregate figures cannot be bound to the inode snapshot required for a signed plan. There is no Docker daemon traversal. Ollama/LM Studio model directories are never selected without explicit opt-in.

### Durable state and external access

All Ballast state uses the documented profile-scoped `plugin_data_dir("ballast")`: normally `$HERMES_HOME/plugin-data/ballast/`. It contains `plan-key` (random local signing material), `plan-*.json`, signed public `last-plan.json`, compact `ledger-status.json`, `state.lock`, append-only `ledger.jsonl`, per-cleanup `recipes-*.md`, private command HOME and staging/log directories. Plans include a detailed cache metadata inventory; keep this local. Creating a new plan prunes expired plan files and empty staging directories; nonempty retained data, ledgers and recipes are preserved. Successful command cleanup removes its empty staging ancestors immediately. The started ledger entry and recipes are persisted before cache changes. Completed/item entries record failures/fallbacks, projected bytes and actual `shutil.disk_usage` free space before/after. A crash can leave a started entry and consumed plan without a completed entry; inspect that entry and staging before replanning.

No credential files are read, no telemetry, external service calls, network downloads, self-updates, remote loaders, compiled binaries or WASM are included. Desktop uses only Hermes's existing authenticated `ctx.rest` bridge. Optional Docker reporting communicates with the default local Docker daemon through the CLI using a sanitized HOME; no user Docker context or remote endpoint is inherited. Rebuild recipes are text; Ballast never executes them. No core tools or host approval policies are replaced. `capabilities: []` declares that no privileged capability IDs are requested; this does not mean Python filesystem operations are sandboxed by Hermes.

Ballast is distinct from bundled **disk-cleanup**, which tracks disposable agent-created paths within Hermes data, and **file-intelligence PR #149964**, which concerns general files. Ballast has a closed developer/AI cache catalog, target-size planning, regeneration regret and a rebuild ledger; it does not sort or clean personal files.
## Install and local verification

Requires Hermes `>=0.23.0` on macOS. The Desktop page's backend routes use the host-supplied `fastapi>=0.97,<1`.

```sh
hermes plugins install ballast
hermes plugins enable ballast
```

From a checkout of the repository, run the test suite and the scripted demo:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/demo.py
```

Tests run in temporary directories with fake cache trees and stub command runners. They never touch your real caches or credentials.

Demo (plays on the repo page):

https://github.com/user-attachments/assets/51c99369-b6b0-472f-bec0-dff5ace87f68

Download: [docs/demo/ballast_demo.mp4](../../docs/demo/ballast_demo.mp4)
