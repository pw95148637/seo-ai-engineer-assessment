#!/usr/bin/env python3
"""Record a real terminal session for the Demo video. Runs in WSL; needs tmux, no sudo, no model calls of its own.

A private tmux server (-L soulo-demo) gets three stacked panes: the run viewer, the Hermes agent.log tail and the
main command (for R4: the registered evaluation step). Every --interval seconds the recorder stores each pane's
visible screen exactly as tmux renders it (capture-pane -e: text plus colours) whenever it changed, with the time
since recording started. Each pane's raw output bytes are archived as well (tmux pipe-pane). demo_render.py turns
the capture into video; nothing is re-typeset from logs.

  python3 scripts/demo_record.py --out demo/v07/r4 --cwd ~/soulo/task02-hermes \
      --viewer 'python3 scripts/demo_live_view.py events --root RUN_ROOT --hermes-log .runtime/user/logs/agent.log' \
      --log 'python3 scripts/demo_live_view.py hermes-log --log .runtime/user/logs/agent.log' \
      --main 'python3 scripts/evaluate_v07.py --step R4'

Output directory: layout.json (geometry, titles, commands, times), frames.jsonl (one screen per line),
raw-<pane>.log (raw bytes), pane-<pane>.sh (the exact scripts each pane ran), main.done / viewer.done markers.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse, json, os, shlex, subprocess, sys, time

SOCKET = 'soulo-demo'
SESSION = 'demo'
TITLES = dict(viewer='檢視器：research.sqlite 控制器事件（即時）',
              log='Hermes agent.log（即時 tail，略去連線細節行）',
              main='執行命令')


def tmux(*args, check=True):
    return subprocess.run(['tmux', '-L', SOCKET, *args], capture_output=True, text=True, check=check).stdout


def write_script(out, name, cwd, body):
    path = out / f'pane-{name}.sh'
    path.write_text('#!/usr/bin/env bash\n'
                    'export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1\n'
                    'sleep 0.5  # let the recorder attach pipe-pane first\n'
                    f'cd {shlex.quote(str(cwd))} || exit 1\n' + body + '\n'
                    'exec sleep 86400  # keep the final screen; the recorder ends the session\n', encoding='utf-8')
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', required=True, help='new directory for this recording (refuses to overwrite)')
    p.add_argument('--cwd', required=True, help='working directory of all panes (the WSL task checkout)')
    p.add_argument('--viewer', required=True, help='command for the top pane')
    p.add_argument('--log', required=True, help='command for the middle pane')
    p.add_argument('--main', required=True, help='command for the bottom pane (the real run)')
    p.add_argument('--main-display', help='command text shown after "$" (default: --main)')
    p.add_argument('--title', action='append', default=[], metavar='PANE=TEXT', help='override a pane title')
    p.add_argument('--cols', type=int, default=120)
    p.add_argument('--rows', type=int, default=28)
    p.add_argument('--log-rows', type=int, default=6)
    p.add_argument('--main-rows', type=int, default=3)
    p.add_argument('--pre', type=float, default=12, help='seconds the main command waits so the ledger can be read')
    p.add_argument('--tail', type=float, default=6, help='seconds kept after the viewer and main command finish')
    p.add_argument('--viewer-grace', type=float, default=240, help='max seconds to wait for the viewer after main ends')
    p.add_argument('--interval', type=float, default=0.25)
    p.add_argument('--max-seconds', type=float, default=2400)
    p.add_argument('--end-marker', default='檢視器結束')
    a = p.parse_args()

    out = Path(a.out).expanduser().resolve()
    if (out / 'frames.jsonl').exists():
        p.error(f'{out} already holds a recording; choose a new --out')
    out.mkdir(parents=True, exist_ok=True)
    cwd = Path(a.cwd).expanduser().resolve()
    titles = dict(TITLES)
    for item in a.title:
        k, _, v = item.partition('=')
        titles[k] = v
    shown = a.main_display or a.main
    scripts = dict(
        viewer=write_script(out, 'viewer', cwd, f'{a.viewer}\ntouch {shlex.quote(str(out / "viewer.done"))}'),
        log=write_script(out, 'log', cwd, a.log),
        main=write_script(out, 'main', cwd,
                          f'printf "%s\\n" {shlex.quote(f"（{a.pre:g} 秒後開始，先讓上方檢視器顯示帳本）")}\n'
                          f'sleep {a.pre}\n'
                          'printf "\\033[2J\\033[H"\n'
                          f'printf "$ %s\\n" {shlex.quote(shown)}\n'
                          f'{a.main}\n'
                          'ec=$?\n'
                          'printf "[命令結束 exit=%s %s]\\n" "$ec" "$(date +%H:%M:%S)"\n'
                          f'touch {shlex.quote(str(out / "main.done"))}'))

    tmux('kill-server', check=False)
    tmux('-f', '/dev/null', 'new-session', '-d', '-s', SESSION, '-x', str(a.cols), '-y', str(a.rows), '-c', str(cwd),
         'bash ' + shlex.quote(str(scripts['viewer'])))
    for opt in (('status', 'off'), ('pane-border-status', 'top'),
                ('pane-border-format', ' #{pane_title} '), ('history-limit', '5000'), ('allow-rename', 'off')):
        tmux('set-option', '-g', *opt, check=False)
    tmux('set-option', '-g', 'allow-set-title', 'off', check=False)
    ids = dict(viewer=tmux('display-message', '-p', '-t', SESSION, '#{pane_id}').strip())
    ids['main'] = tmux('split-window', '-v', '-d', '-P', '-F', '#{pane_id}', '-l', str(a.main_rows), '-t', ids['viewer'],
                       '-c', str(cwd), 'bash ' + shlex.quote(str(scripts['main']))).strip()
    ids['log'] = tmux('split-window', '-v', '-d', '-P', '-F', '#{pane_id}', '-l', str(a.log_rows), '-t', ids['viewer'],
                      '-c', str(cwd), 'bash ' + shlex.quote(str(scripts['log']))).strip()
    for name, pid in ids.items():
        tmux('select-pane', '-t', pid, '-T', titles[name])
        tmux('pipe-pane', '-t', pid, '-o', 'cat >> ' + shlex.quote(str(out / f'raw-{name}.log')))

    def geometry():
        panes = []
        for line in tmux('list-panes', '-t', SESSION, '-F',
                         '#{pane_id} #{pane_top} #{pane_left} #{pane_width} #{pane_height}').splitlines():
            pid, top, left, width, height = line.split()
            name = next(k for k, v in ids.items() if v == pid)
            panes.append(dict(name=name, id=pid, top=int(top), left=int(left), width=int(width), height=int(height),
                              title=titles[name]))
        return sorted(panes, key=lambda x: x['top'])

    started = datetime.now(timezone.utc)
    layout = dict(started_utc=started.isoformat(), cols=a.cols, rows=a.rows, interval=a.interval,
                  tmux=subprocess.run(['tmux', '-V'], capture_output=True, text=True).stdout.strip(),
                  capture='tmux capture-pane -p -e (visible screen, text and colours), stored when changed',
                  panes=geometry(), commands=dict(viewer=a.viewer, log=a.log, main=a.main, main_display=shown),
                  pre_seconds=a.pre, cwd=str(cwd), host=os.uname().nodename)
    (out / 'layout.json').write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'recording to {out} (tmux -L {SOCKET} attach -t {SESSION} to watch)', flush=True)

    t0 = time.monotonic()
    last = {}
    done_at = None
    viewer_end = False
    frames = open(out / 'frames.jsonl', 'a', encoding='utf-8')
    try:
        while True:
            t = time.monotonic() - t0
            for name, pid in ids.items():
                text = subprocess.run(['tmux', '-L', SOCKET, 'capture-pane', '-p', '-e', '-t', pid],
                                      capture_output=True, text=True, errors='replace').stdout
                if text != last.get(name):
                    last[name] = text
                    lines = text.split('\n')
                    if lines and lines[-1] == '':
                        lines.pop()
                    frames.write(json.dumps(dict(t=round(t, 3), pane=name, lines=lines), ensure_ascii=False) + '\n')
                    if name == 'viewer' and a.end_marker in text:
                        viewer_end = True
            frames.flush()
            main_done = (out / 'main.done').exists()
            viewer_done = viewer_end or (out / 'viewer.done').exists()
            if main_done and done_at is None and viewer_done:
                done_at = t
            if main_done and done_at is None and t - main_finished_at(out, t0) > a.viewer_grace:
                done_at = t
            if done_at is not None and t - done_at >= a.tail:
                break
            if t > a.max_seconds:
                print('max-seconds reached; stopping', flush=True)
                break
            time.sleep(max(0.0, a.interval - (time.monotonic() - t0 - t)))
    except KeyboardInterrupt:
        print('interrupted; keeping what was captured', flush=True)
    finally:
        frames.close()
        ended = datetime.now(timezone.utc)
        layout.update(ended_utc=ended.isoformat(), duration=round(time.monotonic() - t0, 3), panes=geometry())
        (out / 'layout.json').write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding='utf-8')
        tmux('kill-server', check=False)
    print(json.dumps(dict(out=str(out), duration=layout['duration'], main_done=(out / 'main.done').exists(),
                          viewer_end=viewer_end), ensure_ascii=False), flush=True)
    return 0


def main_finished_at(out, t0):
    """Monotonic-relative time at which main.done appeared (approximated from its mtime)."""
    stat = (out / 'main.done').stat()
    return time.monotonic() - t0 - (time.time() - stat.st_mtime)


if __name__ == '__main__':
    sys.exit(main())
