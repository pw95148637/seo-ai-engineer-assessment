"""Human review of a finished run: label report items, confirm a clean review, or veto a lesson.

python scripts/feedback.py --root ROOT list [--run RUN_ID]
python scripts/feedback.py --root ROOT label --run RUN_ID --target claim:3 --label unsupported --reason "..." --reviewer NAME [--scope general]
python scripts/feedback.py --root ROOT ok --run RUN_ID --reviewer NAME
python scripts/feedback.py --root ROOT veto --lesson LESSON_ID --reason "..." --reviewer NAME

Labels become active human_feedback lessons shown to the next memory run; a veto is final.
"""
from pathlib import Path
import argparse, json, sqlite3, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.lessons import Ledger


def show(db, ledger, run):
    out = sys.stdout.buffer
    row = db.execute('SELECT run,data FROM events WHERE kind="report" AND (run=? OR ?) ORDER BY id DESC',
                     (run, run is None)).fetchone()
    if row:
        report = json.loads(row['data'])
        lines = [f'run {row["run"]}']
        lines += [f'  claim:{i} [{c.get("kind")}/{c.get("topic")}] {c.get("text")}' for i, c in
                  enumerate(report.get('claims') or [], 1)]
        lines += [f'  action:{i} {a.get("action")} | reason: {a.get("reason")}' for i, a in
                  enumerate(report.get('actions') or [], 1)]
        out.write(('\n'.join(lines) + '\n').encode('utf-8'))
    for lesson in ledger.export()['lessons']:
        out.write(f'lesson {lesson["id"]} {lesson["kind"]} {lesson["status"]}: {lesson["statement"]}\n'.encode('utf-8'))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('list')
    s.add_argument('--run')
    s = sub.add_parser('label')
    s.add_argument('--run', required=True)
    s.add_argument('--target', required=True, help='claim:N or action:N, 1-based as shown by list')
    s.add_argument('--label', required=True, choices=['unsupported', 'scope_error'])
    s.add_argument('--reason', required=True)
    s.add_argument('--reviewer', required=True)
    s.add_argument('--scope', default='host', choices=['host', 'general'])
    s = sub.add_parser('ok')
    s.add_argument('--run', required=True)
    s.add_argument('--reviewer', required=True)
    s.add_argument('--reason', default='')
    s = sub.add_parser('veto')
    s.add_argument('--lesson', required=True)
    s.add_argument('--reason', required=True)
    s.add_argument('--reviewer', required=True)
    a = p.parse_args()
    path = Path(a.root) / 'research.sqlite'
    if not path.exists():
        p.error('no research.sqlite under ' + a.root)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    ledger = Ledger(db)
    try:
        if a.cmd == 'list':
            show(db, ledger, a.run)
        elif a.cmd == 'label':
            print(ledger.add_feedback(a.run, a.target, a.label, a.reason, a.reviewer, a.scope))
        elif a.cmd == 'ok':
            ledger.add_feedback(a.run, 'run', 'reviewed_ok', a.reason, a.reviewer)
            print('recorded')
        else:
            ledger.veto(a.lesson, a.reason, a.reviewer)
            print('vetoed')
    except ValueError as e:
        p.error(str(e))


if __name__ == '__main__':
    main()
