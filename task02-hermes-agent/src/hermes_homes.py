"""Hermes homes for the v0.8 arms: creation, learned-content manifests, snapshots and isolation checks.

Every arm and every evaluation run gets its own Hermes profile home, <task>/.runtime/user/profiles/<name>. Hermes keeps
memory in <home>/memories and skills in <home>/skills, so separate homes cannot see each other's learning. The OAuth
store stays in the root home <task>/.runtime/user and Hermes reads it through its profile fallback; nothing here copies
or opens it. Only files are touched; no Hermes import, so the checks run offline on any platform.
"""
from pathlib import Path, PurePosixPath
import hashlib, json, os, re, shutil

ROOT_HOME = PurePosixPath('.runtime/user')
PROFILES = ROOT_HOME / 'profiles'
LEARNED_DIRS = ('memories', 'skills')
PLUGIN_NAME = 'soulo-research'
# JSON is valid YAML, so config.yaml is written without a YAML library.
BASE_CONFIG = {'auth': {'adopt_external_logins': False}, 'plugins': {'enabled': [PLUGIN_NAME]},
               'tools': {'tool_search': {'enabled': 'off'}}}
# Hermes defaults are 10 user turns (memory) and 10 tool iterations (skills); a research run is one user turn of
# about 7 iterations, so with the defaults the end-of-turn review would never run.
LEARN_SETTINGS = {'memory': {'nudge_interval': 1}, 'skills': {'creation_nudge_interval': 1}}
ENTRY_DELIMITER = '\n§\n'  # Hermes MEMORY.md / USER.md entry separator
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')


# The only files Hermes changes when skills or memory are merely read or locked (tools/skill_usage.py,
# tools/skill_manager_tool.py, tools/skill_ledger.py, agent/curator.py, tools/memory_tool_store.py at the pinned commit).
# Everything else under memories/ and skills/, such as references/notes.lock, is learned content.
TELEMETRY_FILES = {'skills/.usage.json', 'skills/.usage.json.lock', 'skills/.curator_state',
                   'memories/MEMORY.md.lock', 'memories/USER.md.lock'}


def is_telemetry(rel):
    """Usage counters and lock files, which change when a store is only read; they are not learned content."""
    p = PurePosixPath(rel)
    return str(p) in TELEMETRY_FILES or (p.parent == PurePosixPath('skills/.locks') and p.suffix == '.lock')


def home_path(task, name):
    if not NAME.match(name or ''):
        raise ValueError('home names are lowercase letters, digits and dashes')
    return Path(task) / PROFILES / name


def check_home_path(task, path):
    """The resolved home when `path` is <task>/.runtime/user/profiles/<name> with a config.yaml; otherwise ValueError."""
    p = Path(path).resolve()
    if p.parent != (Path(task) / PROFILES).resolve() or not NAME.match(p.name) or not (p / 'config.yaml').is_file():
        raise ValueError('hermes home must be an existing <task>/.runtime/user/profiles/<name> with config.yaml')
    return p


def config_for(learn):
    cfg = json.loads(json.dumps(BASE_CONFIG))
    if learn:
        cfg.update(json.loads(json.dumps(LEARN_SETTINGS)))
    return cfg


def create_home(task, name, learn=False, link_plugin=True):
    """A new, empty home. An existing home is never reused, so no run inherits another run's files."""
    home = home_path(task, name)
    if home.exists() or home.is_symlink():
        raise ValueError(f'home {name} already exists; every run starts from a new home')
    for d in LEARNED_DIRS + ('plugins',):
        (home / d).mkdir(parents=True)
    (home / 'config.yaml').write_text(json.dumps(config_for(learn), indent=2) + '\n', encoding='utf-8')
    if link_plugin:
        os.symlink(Path(task).resolve() / 'plugin', home / 'plugins' / PLUGIN_NAME, target_is_directory=True)
    return home


def learned_files(home):
    """relative path -> SHA-256 of every learned file under memories/ and skills/, telemetry excluded.

    Symlinks are refused: a linked memories/ or skills/ would let two homes share one store."""
    out = {}
    for d in LEARNED_DIRS:
        base = Path(home) / d
        if base.is_symlink():
            raise ValueError(f'{base} is a symlink; learned stores must belong to their home')
        if not base.exists():
            continue
        for f in sorted(base.rglob('*')):
            rel = f.relative_to(home).as_posix()
            if f.is_symlink():
                raise ValueError(f'symlink inside learned content: {rel}')
            if f.is_file() and not is_telemetry(rel):
                out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode('utf-8')).hexdigest()


EMPTY = digest({})


def snapshot(home, dest):
    """Copy the learned files of `home` into a new directory `dest`; return their manifest."""
    dest = Path(dest)
    if dest.exists():
        raise ValueError(f'{dest} exists; snapshots are never overwritten')
    manifest = learned_files(home)
    dest.mkdir(parents=True)
    for d in LEARNED_DIRS:
        (dest / d).mkdir()
    for rel in manifest:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(home) / rel, dest / rel)
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return manifest


def restore(snap, home, task):
    """Make the learned files of `home` exactly those of snapshot `snap` and check the result."""
    home = Path(home)
    if home.resolve().parent != (Path(task) / PROFILES).resolve():
        raise ValueError('restore only writes inside a v0.8 profile home')
    expected = json.loads((Path(snap) / 'manifest.json').read_text(encoding='utf-8'))
    for d in LEARNED_DIRS:
        if (home / d).exists():
            shutil.rmtree(home / d)
        (home / d).mkdir()
    for rel in expected:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(snap) / rel, home / rel)
    if learned_files(home) != expected:
        raise ValueError('restored home differs from its snapshot')
    return expected


def user_hermes_state(user_home=None):
    """The shared ~/.hermes: absent, or the digest of its learned files. v0.8 never uses it."""
    base = Path(user_home or Path.home()) / '.hermes'
    return None if not base.exists() else digest(learned_files(base))


def isolation_state(task, user_home=None):
    profiles = Path(task) / PROFILES
    homes = {p.name: digest(learned_files(p)) for p in sorted(profiles.iterdir()) if p.is_dir()} if profiles.exists() else {}
    return dict(homes=homes, root_learned=sorted(learned_files(Path(task) / ROOT_HOME)),
                user_hermes=user_hermes_state(user_home))


def isolation_check(before, after, own, own_expected=None):
    """Problems found between two isolation states of one step; an empty list means isolated.

    Only `own` may change, and only when own_expected is None (a learning step). Every other home, the root home's
    stores and ~/.hermes must stay as they were."""
    problems = []
    if before['root_learned'] or after['root_learned']:
        problems.append('root home has learned files: ' + ', '.join(after['root_learned'] or before['root_learned']))
    if before['user_hermes'] != after['user_hermes']:
        problems.append('~/.hermes changed')
    for name in sorted(set(before['homes']) | set(after['homes'])):
        if name == own:
            continue
        if before['homes'].get(name) != after['homes'].get(name):
            problems.append(f'home {name} changed during a run of {own}')
    if own_expected is not None and after['homes'].get(own) != own_expected:
        problems.append(f'home {own} learned content changed although the run was frozen')
    return problems


# Learned items for the blind classification -------------------------------------------------------------------
LIST_ITEM = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+')
# Front-matter fields that only identify or tag a skill; they are not knowledge to classify.
METADATA_FIELDS = {'name', 'version', 'tags', 'author', 'license', 'platforms', 'metadata', 'created_by', 'category'}


def memory_items(root):
    out = []
    for name in ('MEMORY.md', 'USER.md'):
        f = Path(root) / 'memories' / name
        if f.is_file():
            entries = [e.strip() for e in f.read_text(encoding='utf-8').split(ENTRY_DELIMITER)]
            out += [dict(source=f'memories/{name}', section='', text=e) for e in entries if e]
    return out


def _blocks(text):
    """Split markdown into items: the front matter, list items, paragraphs and code blocks; headings give context."""
    items, section, para, fence = [], '', [], None
    lines = text.replace('\r\n', '\n').split('\n')
    if lines and lines[0].strip() == '---':
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == '---'), None)
        if end:
            # One item for the whole front matter, without the fields that only name or tag the skill.
            kept, skip = [], False
            for l in lines[1:end]:
                if l.strip() and not l[0].isspace():
                    skip = l.split(':', 1)[0].strip() in METADATA_FIELDS
                if l.strip() and not skip:
                    kept.append(l.rstrip())
            if kept:
                items.append(('front matter', '\n'.join(kept).strip()))
            lines = lines[end + 1:]

    def flush():
        if para:
            items.append((section, '\n'.join(para).strip()))
            para.clear()
    for line in lines:
        if fence is not None:
            fence.append(line)
            if line.strip().startswith('```'):
                items.append((section, '\n'.join(fence)))
                fence = None
            continue
        if line.strip().startswith('```'):
            flush()
            fence = [line]
        elif line.lstrip().startswith('#'):
            flush()
            section = line.strip('# ').strip()
        elif not line.strip():
            flush()
        elif LIST_ITEM.match(line):
            flush()
            para.append(line.strip())
        else:
            para.append(line.strip())
    flush()
    if fence:
        items.append((section, '\n'.join(fence)))
    return [(s, t) for s, t in items if t]


def skill_items(root):
    out = []
    base = Path(root) / 'skills'
    for f in sorted(base.rglob('*')) if base.exists() else []:
        rel = f.relative_to(root).as_posix()
        # Hidden entries (.curator_ledger.jsonl, .archive/) are bookkeeping, not skills the agent loads.
        if not f.is_file() or is_telemetry(rel) or any(p.startswith('.') for p in PurePosixPath(rel).parts):
            continue
        text = f.read_text(encoding='utf-8', errors='replace')
        if f.suffix.lower() in ('.md', '.markdown', '.txt'):
            out += [dict(source=rel, section=s, text=t) for s, t in _blocks(text)]
        elif text.strip():
            out.append(dict(source=rel, section='', text=text.strip()))
    return out
