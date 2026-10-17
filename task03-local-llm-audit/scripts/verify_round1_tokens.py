"""Provenance check for round-1 outputs: recompute Qwen3 chat-template token counts (train12 only).

Round-1 training.json lengths and consistency.json input_tokens must equal counts computed from the v1 prompt
(outputs/experiments/initial/system_prompt.txt), train12, the round-1 targets retrieved from Kaggle
(kaggle-retrieved/v3/work03/data/train_targets.jsonl, sha256 d70c4aeb..., ID13 score 25), knowledge.json
and the tokenizer at the pinned revision. Also prints current-prompt lengths for the context/GPU-time budget.
Needs: pip install tokenizers; tokenizer.json from
https://huggingface.co/Qwen/Qwen3-8B/resolve/b968826d9c46dd6066d109eabc6255188de91218/tokenizer.json
Usage: python scripts/verify_round1_tokens.py <path/to/tokenizer.json>"""
import csv,json,sys
from pathlib import Path
from tokenizers import Tokenizer
R=Path(__file__).resolve().parents[1]
tok=Tokenizer.from_file(sys.argv[1])
know=json.loads((R/'knowledge.json').read_text(encoding='utf-8'))
with (R/'data/train12.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
def load_labels(p):return {x['ID']:x['target'] for x in map(json.loads,p.read_text(encoding='utf-8').splitlines()) if x}
labels=load_labels(R/'data/train_targets.jsonl')
def n(s):return len(tok.encode(s,add_special_tokens=False).ids)
def prompt(system,row):
 user=json.dumps({'article':row['Content Snippet (文章片段)'],'knowledge':know},ensure_ascii=False)
 return f'<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
def lengths(system,labels):return [(r['ID'],n(prompt(system,r)),n(json.dumps(labels[r['ID']],ensure_ascii=False,separators=(',',':'))+'<|im_end|>')) for r in rows]
v1=(R/'outputs/experiments/initial/system_prompt.txt').read_text(encoding='utf-8-sig')
round1_labels=load_labels(R/'kaggle-retrieved/v3/work03/data/train_targets.jsonl')  # round-1 file: ID13 25, no severity
training=json.loads((R/'outputs/experiments/initial/training.json').read_text(encoding='utf-8'))
cons=json.loads((R/'outputs/experiments/initial/consistency.json').read_text(encoding='utf-8'))
r1=lengths(v1,round1_labels);ok_train=[a+b for _,a,b in r1]==training['lengths']
ok_cons={x['input_tokens'] for x in cons['runs']}=={a for i,a,_ in r1 if i==cons['ID']}
cur=lengths((R/'system_prompt.txt').read_text(encoding='utf-8-sig'),labels)
print(json.dumps(dict(round1_training_lengths_match=ok_train,round1_consistency_input_tokens_match=ok_cons,
 current_prompt_tokens=[min(a for _,a,_ in cur),max(a for _,a,_ in cur)],current_max_train_length=max(a+b for _,a,b in cur),
 current_target_tokens=[min(b for *_,b in cur),max(b for *_,b in cur)])))
assert ok_train and ok_cons,'Round-1 outputs do not match the recorded prompt/data/tokenizer'
print('PASS: round-1 training lengths and consistency input tokens reproduce exactly')
