"""Score one run and optionally write a blind review packet. Never overwrites an existing score file.

python scripts/score_run.py --root RUN_ROOT [--run-id ID] [--out score.json] [--blind-dir DIR]
"""
from pathlib import Path
import argparse, json, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.scoring import KEYWORDS, score_run, write_blind_packet


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--run-id')
    p.add_argument('--keyword', action='append')
    p.add_argument('--out')
    p.add_argument('--blind-dir')
    a = p.parse_args()
    if a.out and Path(a.out).exists():
        p.error('refusing to overwrite ' + a.out)
    score = score_run(a.root, a.run_id, tuple(a.keyword or KEYWORDS))
    if a.blind_dir:
        score['blind_id'] = write_blind_packet(a.root, score['run_id'], a.blind_dir)
    text = json.dumps(score, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding='utf-8')
    sys.stdout.buffer.write(text.encode('utf-8') + b'\n')


if __name__ == '__main__':
    main()
