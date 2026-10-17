"""Post-hoc analysis after the freeze (plan: evaluation/posthoc-plan.md). Not part of the frozen system.

Stages (each in its own process):
  fp16  Experiment A: Qwen3-8B in 16-bit across two T4s, no adapter, on the 8 test articles. Prompt, knowledge,
        messages(), generate() (greedy), audit_one() (one repair) and the output contract are imported unchanged
        from the frozen bundle; only the model loader differs from the frozen 4-bit loader.
  loss  Experiment B: answer-token cross-entropy of the 12 supervised targets, 4-bit base with and without the
        frozen adapter, eval mode, built with the frozen examples(). Test articles are not read.
WORK03_ROOT points at the copied frozen bundle; outputs go to POSTHOC_OUT, outside the bundle."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ['WORK03_ROOT'])
OUT = Path(os.environ['POSTHOC_OUT'])
sys.path.insert(0, str(ROOT / 'scripts'))
import workflow as wf  # noqa: E402  frozen bundle code, imported unchanged


def versions():
    import importlib.metadata as meta
    import torch
    return dict(torch=torch.__version__, **{p: meta.version(p) for p in
                                          ['transformers', 'peft', 'bitsandbytes', 'accelerate', 'datasets']})


def fp16():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    c = wf.config()
    assert torch.cuda.device_count() == 2, 'Experiment A needs both T4s for 16-bit weights'
    tok = AutoTokenizer.from_pretrained(c['model_id'], revision=c['model_revision'])
    tok.pad_token = tok.eos_token
    tok.padding_side = 'right'
    model = AutoModelForCausalLM.from_pretrained(c['model_id'], revision=c['model_revision'], torch_dtype=torch.float16,
                                                 device_map='auto', max_memory={0: '9GiB', 1: '12GiB'})
    for i in range(2):
        torch.cuda.reset_peak_memory_stats(i)
    env = dict(started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), weights='float16, no adapter',
               model_id=c['model_id'], revision=c['model_revision'], parameters=model.num_parameters(),
               footprint_bytes=model.get_memory_footprint(),
               devices=sorted(set(str(v) for v in model.hf_device_map.values())),
               gpus=[torch.cuda.get_device_name(i) for i in range(2)], versions=versions(),
               holdout_sha256=wf.sha(ROOT / 'data/holdout8.csv'), lock_sha256=wf.sha(ROOT / 'outputs/frozen.json'))
    wf.write(OUT / 'fp16_env.json', env)
    started = time.monotonic()
    wf.batch(wf.data('holdout8'), lambda msg: wf.generate(tok, model, msg), OUT / 'holdout_fp16.jsonl')
    env.update(seconds_total=time.monotonic() - started,
               peak_gpu1_bytes_all_items=torch.cuda.max_memory_allocated(1),
               note='peak_gpu_bytes inside each record is device 0 only (frozen generate()); device 1 peak is above')
    wf.write(OUT / 'fp16_env.json', env)
    print(json.dumps(env, ensure_ascii=False, indent=1))


def loss():
    import torch
    tok, model = wf.load(adapter=True)
    model.eval()
    c = wf.config()
    rows, labels = wf.data('train12'), wf.targets()
    ds = wf.examples(tok, rows, labels, c['max_length'])

    def answer_ce(ex):
        ids = torch.tensor([ex['input_ids']], device='cuda:0')
        lab = torch.tensor([ex['labels']], device='cuda:0')
        j0 = max(1, int((lab != -100).nonzero(as_tuple=True)[1].min()))
        with torch.inference_mode():
            out = model(input_ids=ids, attention_mask=torch.ones_like(ids), logits_to_keep=lab.shape[1] - j0 + 1)
        logits = out.logits[:, :-1, :].float()
        tgt = lab[:, j0:]
        s = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt.reshape(-1),
                                              ignore_index=-100, reduction='sum')
        return float(s), int((tgt != -100).sum())

    items = []
    for row, ex in zip(rows, ds):
        a_sum, n = answer_ce(ex)
        with model.disable_adapter():
            b_sum, n2 = answer_ce(ex)
        assert n == n2
        items.append(dict(ID=row['ID'], answer_tokens=n, ce_adapter=a_sum / n, ce_base=b_sum / n,
                          ce_sum_adapter=a_sum, ce_sum_base=b_sum))
    tokens = sum(x['answer_tokens'] for x in items)
    ce_a = sum(x['ce_sum_adapter'] for x in items) / tokens
    ce_b = sum(x['ce_sum_base'] for x in items) / tokens
    result = dict(created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  setup='4-bit NF4 base as in training, eval mode, answer tokens only, frozen examples(); '
                        'base = same model with the adapter disabled',
                  answer_tokens=tokens, ce_base=ce_b, ce_adapter=ce_a, relative_reduction=(ce_b - ce_a) / ce_b,
                  items=items, versions=versions())
    wf.write(OUT / 'train_target_loss.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'items'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    {'fp16': fp16, 'loss': loss}[sys.argv[1]]()
