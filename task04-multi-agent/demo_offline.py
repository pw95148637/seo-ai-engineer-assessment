import asyncio,json
from dataclasses import asdict
from pathlib import Path
from workflow import run,State
from fixtures import Fixture
async def main():
    for case in ("normal","conflict","immutable","stubborn","api_error","malformed","false_pass","timeout"):
        s=await run(Fixture("conflict" if case=="immutable" else case),
                    State(immutable_conflict=case=="immutable"),timeout=.02)
        Path("evidence",case+".json").write_text(json.dumps(asdict(s),ensure_ascii=False,indent=2),encoding="utf-8")
        print(case,s.status,s.iteration)
asyncio.run(main())
