"""Closed catalog. Paths are relative to HOME; tool arguments never add roots."""

def source(id, label, paths, owner, minutes, download_mb, recipe, confidence=.95,
           optional=False, command=None):
    return dict(id=id, label=label, paths=paths, owner=owner, regen_minutes=minutes,
                download_mb=download_mb, recipe=recipe, confidence=confidence,
                optional=optional, command=command)


CATALOG = [
    source('npm', 'npm packages', ['.npm/_cacache'], 'npm', 3, 300, 'Run npm install in the project.', command='npm'),
    source('pnpm', 'pnpm store', ['Library/pnpm/store', '.pnpm-store'], 'pnpm', 5, 500, 'Run pnpm install in the project; versioned projects registries are preserved.'),
    source('yarn', 'Yarn packages', ['Library/Caches/Yarn'], 'yarn', 4, 400, 'Run yarn install in the project.', command='yarn cache clean'),
    source('pip', 'pip downloads', ['Library/Caches/pip'], 'pip', 3, 300, 'Run python -m pip install -r requirements.txt.', command='pip'),
    source('uv', 'uv packages', ['.cache/uv'], 'uv', 2, 300, 'Run uv sync in the project.', command='uv'),
    source('cargo', 'Cargo sources & downloads', ['.cargo/registry/cache', '.cargo/registry/src', '.cargo/git/checkouts'], 'cargo', 8, 700, 'Run cargo fetch, then cargo build. Installed ~/.cargo/bin tools are untouched.'),
    source('homebrew', 'Homebrew downloads', ['Library/Caches/Homebrew'], 'brew', 6, 1000, 'Run brew fetch <formula> or brew install <formula>.', command='brew cleanup -s'),
    source('xcode-derived', 'Xcode DerivedData', ['Library/Developer/Xcode/DerivedData'], 'xcodebuild', 12, 0, 'Open the project in Xcode and build again.'),
    source('xcode-device', 'Xcode device support', ['Library/Developer/Xcode/iOS DeviceSupport'], 'Xcode', 15, 1500, 'Reconnect the device with its matching Xcode version; device symbols are prepared again.', .8),
    source('simulator', 'CoreSimulator caches', ['Library/Developer/CoreSimulator/Caches'], 'Simulator', 6, 200, 'Launch Simulator; rebuild its caches. Device runtimes and device data are untouched.', .85),
    source('huggingface', 'HuggingFace model', ['.cache/huggingface/hub'], 'huggingface_hub', 40, 5000, 'Download the named model again with your normal HuggingFace workflow.', .9),
    source('gradle', 'Gradle caches', ['.gradle/caches'], 'gradle', 10, 1000, 'Run ./gradlew build; dependencies and transforms are recreated.'),
    source('cocoapods', 'CocoaPods downloads', ['Library/Caches/CocoaPods'], 'pod', 6, 500, 'Run pod install in the project.'),
    source('go-build', 'Go build cache', ['Library/Caches/go-build'], 'go', 4, 0, 'Run go build ./... in the project.', command='go-build'),
    source('go-mod', 'Go module downloads', ['go/pkg/mod'], 'go', 6, 500, 'Run go mod download in the project.', command='go-mod'),
    source('ollama', 'Ollama models', ['.ollama/models'], 'ollama', 90, 12000, 'Run ollama pull <model> for each model you need.', .8, True),
    source('lmstudio', 'LM Studio models', ['.lmstudio/models', 'Library/Application Support/LM Studio/models'], 'LM Studio', 90, 12000, 'Download your models again from LM Studio.', .8, True),
]

DENIED = ['Documents', 'Desktop', 'Downloads', 'Pictures', 'Movies', 'Music',
          'Library/Mobile Documents', 'Library/Keychains', 'Library/Mail',
          'Library/Messages', 'Library/Photos', '.ssh', '.gnupg', '.hermes']

WARNINGS = [
    'Allocated bytes (st_blocks × 512); APFS clones and local snapshots can make actual space freed lower.',
    'Last-used is sampled max(atime, mtime) of regular-file metadata; noatime/relatime and copied timestamps make this uncertain.',
    'Hardlinks count once only when all links are inside the same candidate; shared/external links count zero.',
    'Deletion is permanent. Rebuild recipes recreate caches, not their exact previous contents.',
]
