"""Check Ballast's isolated native Desktop. Only the user runs --launch."""
import argparse
import hashlib
import json
import re
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'tmp/desktop'
SOURCE = BASE / 'runtime'
REFERENCE = Path('/Users/a87/Projects/PeelHere')
PYTHON = REFERENCE / 'tmp/hermes/installs/ea094c1b20f774f5/environments/cd9b3058a7764801b9510fa012a8606f/venv/bin/python'
NODE = REFERENCE / 'tmp/compatibility/tools/node/node-v26.12.1-darwin-arm64/bin/node'
PNPM = REFERENCE / 'tmp/compatibility/tools/pnpm-native/package/pnpm'
CACHE = BASE / 'cache'
HERMES = BASE / 'hermes-home'
USER_DATA = BASE / 'user-data'
DEMO = Path('/Users/a87/BallastDemoHome')
APP = SOURCE / 'apps/desktop'
BINARY = APP / 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'


def environment():
    # Allowlist excludes inherited credentials, provider URLs, auth/profile and backend overrides.
    env = {key: os.environ[key] for key in ('LANG', 'LC_ALL', 'USER', 'LOGNAME', 'TERM') if key in os.environ}
    env.update(PATH=f'{NODE.parent}:{PNPM.parent}:/usr/bin:/bin:/usr/sbin:/sbin',
        SHELL='/bin/zsh', ZDOTDIR=str(BASE/'shell'), TMPDIR=str(BASE/'tmp'), XDG_CACHE_HOME=str(CACHE), XDG_CONFIG_HOME=str(CACHE/'config'),
        XDG_DATA_HOME=str(CACHE/'data'), XDG_STATE_HOME=str(CACHE/'state'), XDG_RUNTIME_DIR=str(CACHE/'runtime'),
        npm_config_userconfig=str(BASE/'npm-user-empty.conf'), npm_config_globalconfig=str(BASE/'npm-global-empty.conf'),
        npm_config_cache=str(CACHE/'npm'), npm_config_store_dir=str(CACHE/'pnpm-store'),
        npm_config_update_notifier='false', COREPACK_HOME=str(CACHE/'corepack'), PNPM_HOME=str(CACHE/'pnpm-home'),
        PIP_CACHE_DIR=str(CACHE/'pip'), PIP_CONFIG_FILE='/dev/null', PIP_DISABLE_PIP_VERSION_CHECK='1',
        UV_CACHE_DIR=str(CACHE/'uv'), UV_OFFLINE='1', UV_NO_CONFIG='1', HF_HOME=str(CACHE/'huggingface'),
        HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_DISABLE_TELEMETRY='1',
        ELECTRON_CACHE=str(CACHE/'electron'), electron_config_cache=str(CACHE/'electron'),
        PLAYWRIGHT_BROWSERS_PATH=str(CACHE/'playwright'), PYTHONDONTWRITEBYTECODE='1',
        HERMES_HOME=str(HERMES), HERMES_DESKTOP_USER_DATA_DIR=str(USER_DATA),
        HERMES_DESKTOP_HERMES_ROOT=str(SOURCE), HERMES_DESKTOP_PYTHON=str(PYTHON),
        HERMES_DESKTOP_CWD=str(BASE/'work'), HERMES_DESKTOP_APP_NAME='Ballast Demo (Isolated)',
        HERMES_DESKTOP_CDP_PORT='off')
    return env


def check():
    for path in (BASE, SOURCE, HERMES, USER_DATA, CACHE, BASE/'tmp', BASE/'work', BASE/'shell', APP/'dist/electron-main.mjs', BINARY):
        assert path.exists() and path.resolve().is_relative_to(BASE.resolve()), f'Missing or escaping workspace path: {path}'
        assert path.stat().st_uid == os.getuid(), f'Wrong owner: {path}'
    for path in (PYTHON, NODE, PNPM):
        assert path.is_file() and os.access(path, os.X_OK) and path.is_relative_to(REFERENCE), f'Missing read-only tool: {path}'
    text = (HERMES/'config.yaml').read_text()
    # Hermes may rewrite config.yaml as YAML; check the required isolation facts textually.
    for needle in ('ballast', str(DEMO), 'adopt_external_logins', 'deepseek', 'deepseek-flash'):
        assert needle in text, f'config.yaml missing {needle}'
    assert re.search(r'adopt_external_logins["\']?\s*:\s*false', text), 'external-login adoption must be disabled'
    assert DEMO.resolve() == DEMO and DEMO.is_dir() and DEMO.stat().st_uid == os.getuid()
    for source in (ROOT/'plugin/ballast').rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts:
            installed = HERMES/'plugins/ballast'/source.relative_to(ROOT/'plugin/ballast')
            assert installed.is_file() and hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(installed.read_bytes()).digest(), f'Plugin copy differs: {source}'
    env = environment()
    assert not any('KEY' in key or 'TOKEN' in key or key in ('HOME', 'PYTHONPATH', 'NODE_OPTIONS') for key in env if key != 'HF_HUB_DISABLE_IMPLICIT_TOKEN')
    for key in ('ZDOTDIR','TMPDIR','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_RUNTIME_DIR','npm_config_cache','PIP_CACHE_DIR','UV_CACHE_DIR','HF_HOME','HERMES_HOME','HERMES_DESKTOP_USER_DATA_DIR'):
        assert Path(env[key]).resolve().is_relative_to(BASE.resolve()), f'Unisolated {key}'
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true', help='User only: launch this isolated native app in the foreground')
    options = parser.parse_args()
    env = check()
    # Start the already-built Electron package, as pnpm start does after its build.
    # Avoid rebuilding: source build stamps invoke git, which this demo forbids.
    argv = [str(BINARY), str(APP)]
    print(json.dumps(dict(argv=argv, cwd=str(SOURCE), isolated_environment=env,
        checks='PASS: workspace state, owned demo HOME, matching plugin, built Electron package, external adoption disabled; credentials excluded',
        gui_launched=options.launch, runtime='APFS clone of pinned ad4fa2f47cb689d4ca4a6ee465ab8d152b46cc73; no build/install command'), indent=2), flush=True)
    if options.launch:
        return subprocess.call(argv, cwd=SOURCE, env=env)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
