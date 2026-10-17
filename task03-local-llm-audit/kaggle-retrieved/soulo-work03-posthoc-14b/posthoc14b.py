"""Post-hoc analysis after the freeze (plan: evaluation/posthoc14b-plan.md). Not part of the frozen system.

Runs Qwen3-14B through the frozen pipeline: load() (4-bit nf4, double quant, fp16 compute, one T4), messages(),
generate() (greedy), audit_one() (one repair) and the output contract are imported unchanged from the frozen bundle.
Only the model id and revision that the frozen load() reads from config() are switched to 14B; no adapter is loaded
(the 8B LoRA does not fit 14B).
Order: environment checks (disk, chat template, finite logits on a training prompt) -> hash-check and read the 8 test
articles -> batch audit. WORK03_ROOT points at the copied frozen bundle; outputs go to POSTHOC_OUT, outside the bundle."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(os.environ['WORK03_ROOT'])
OUT = Path(os.environ['POSTHOC_OUT'])
HOLDOUT = Path(os.environ['HOLDOUT_PATH'])
HOLDOUT_SHA256 = os.environ['HOLDOUT_SHA256']
MODEL_ID = 'Qwen/Qwen3-14B'
REVISION = '40c069824f4251a91eefaf281ebe4c544efd3e18'
NEEDED_FREE_BYTES = 35 * 10**9  # 29.6 GB of weights plus headroom
sys.path.insert(0, str(ROOT / 'scripts'))
import workflow as wf  # noqa: E402  frozen bundle code, imported unchanged

FROZEN_CONFIG = wf.config
FROZEN = FROZEN_CONFIG()


def config_14b():
    """Frozen run_config.json with only the model id and revision replaced; max_new_tokens and context_limit stay."""
    return {**FROZEN_CONFIG(), 'model_id': MODEL_ID, 'model_revision': REVISION}


def disk(paths):
    out = {}
    for p in paths:
        if p and os.path.exists(p):
            u = shutil.disk_usage(p)
            out[p] = dict(total_gb=round(u.total / 1e9, 1), free_gb=round(u.free / 1e9, 1))
    return out


def pick_cache():
    """Keep the 29.6 GB Hugging Face cache out of /kaggle/working (saved output, about 20 GB)."""
    cands = [p for p in ['/tmp', '/root', '/kaggle/tmp'] if os.path.isdir(p)]
    best = max(cands, key=lambda p: shutil.disk_usage(p).free)
    return Path(best) / 'hf', shutil.disk_usage(best).free


def versions():
    import importlib.metadata as meta
    import torch
    return dict(torch=torch.__version__, **{p: meta.version(p) for p in
                                          ['transformers', 'peft', 'bitsandbytes', 'accelerate', 'huggingface_hub']})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache, free = pick_cache()
    os.environ['HF_HOME'] = str(cache)  # before transformers/huggingface_hub are imported
    os.environ['HF_HUB_CACHE'] = str(cache / 'hub')  # a preset HF_HUB_CACHE would otherwise win over HF_HOME
    env = dict(started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), model_id=MODEL_ID, revision=REVISION,
               weights='4-bit nf4 via frozen load(adapter=False); no adapter',
               frozen_model=dict(model_id=FROZEN['model_id'], revision=FROZEN['model_revision']),
               hf_home=str(cache), disk=disk(['/', '/tmp', '/root', '/kaggle/tmp', '/kaggle/working']),
               lock_sha256=wf.sha(ROOT / 'outputs/frozen.json'))
    wf.write(OUT / 'env_14b.json', env)
    assert free >= NEEDED_FREE_BYTES, f'Not enough disk for the 14B weights: {free / 1e9:.1f} GB free at {cache.parent}'

    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer
    env.update(versions=versions(), gpus=[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])

    t0 = time.monotonic()
    snapshot_download(MODEL_ID, revision=REVISION, max_workers=8)
    env['seconds_download'] = round(time.monotonic() - t0, 1)
    env['disk_after_download'] = disk([str(cache.parent)])

    # Same chat template and tokenization as the frozen 8B, checked on a training article (test data not read yet).
    row = wf.data('train12')[0]
    tok8 = AutoTokenizer.from_pretrained(FROZEN['model_id'], revision=FROZEN['model_revision'])
    tok14 = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION)
    render = lambda t: t.apply_chat_template(wf.messages(row), tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
    env['chat_template_same_as_8b'] = tok8.chat_template == tok14.chat_template
    env['train_prompt_tokens_same_as_8b'] = (tok8(render(tok8), add_special_tokens=False).input_ids
                                             == tok14(render(tok14), add_special_tokens=False).input_ids)
    wf.write(OUT / 'env_14b.json', env)

    wf.config = config_14b  # the frozen load() and generate() read config() at call time
    t0 = time.monotonic()
    tok, model = wf.load(adapter=False)
    env.update(seconds_load=round(time.monotonic() - t0, 1), parameters=model.num_parameters(),
               footprint_bytes=model.get_memory_footprint(),
               devices=sorted(set(str(v) for v in model.hf_device_map.values())),
               quantization_config=json.loads(json.dumps(model.config.quantization_config.to_dict(), default=str)),
               gpu0_allocated_after_load=torch.cuda.memory_allocated(0))

    # fp16 overflow check: one full training prompt, last-position logits must be finite.
    x = tok(render(tok), add_special_tokens=False, return_tensors='pt').to('cuda:0')
    with torch.inference_mode():
        logits = model(**x, logits_to_keep=1).logits
    env['logits_check'] = dict(train_id=row['ID'], input_tokens=int(x.input_ids.shape[1]),
                               finite=bool(torch.isfinite(logits).all()),
                               top_token=tok.decode([int(logits[0, -1].argmax())]))
    wf.write(OUT / 'env_14b.json', env)
    assert env['logits_check']['finite'], 'Non-finite logits in fp16; stop before reading the test data'
    del x, logits

    # Test data: hash-check, then read through the frozen data()/batch().
    assert wf.sha(HOLDOUT) == HOLDOUT_SHA256, 'holdout8.csv bytes changed'
    shutil.copyfile(HOLDOUT, ROOT / 'data/holdout8.csv')
    env['holdout_sha256'] = wf.sha(ROOT / 'data/holdout8.csv')
    t0 = time.monotonic()
    wf.batch(wf.data('holdout8'), lambda msg: wf.generate(tok, model, msg), OUT / 'holdout_14b.jsonl')
    env.update(seconds_generation=round(time.monotonic() - t0, 1),
               finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               note='peak_gpu_bytes inside each record is per generate() call on device 0')
    wf.write(OUT / 'env_14b.json', env)
    print(json.dumps(env, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
