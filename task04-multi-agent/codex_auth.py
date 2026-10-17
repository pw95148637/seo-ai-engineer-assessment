"""Normal, independent CLI login. No credentials are read or exported by this script."""
import argparse,asyncio,json,subprocess
from codex_subscription import cli_base,cli_environment,rpc_preflight
p=argparse.ArgumentParser()
p.add_argument("action",choices=("status","login","quota","version"))
args=p.parse_args()
if args.action=="quota":
    try: print(json.dumps(asyncio.run(rpc_preflight()),ensure_ascii=False,indent=2))
    except (Exception,) as e:
        print(json.dumps({"included_only_confirmed":False,"error":type(e).__name__}))
        raise SystemExit(2)
else:
    action={"status":["login","status"],"login":["login","--device-auth"],"version":["--version"]}[args.action]
    raise SystemExit(subprocess.call(cli_base()+action,env=cli_environment()))
