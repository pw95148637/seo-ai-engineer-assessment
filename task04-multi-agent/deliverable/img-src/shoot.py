"""Render the slide images in this folder to ../img/ at their fixed sizes with headless Chrome.

usage: python shoot.py [--chrome <path to chrome.exe>]

Each HTML file is drawn at an exact CSS size so the PNG fits its slot: full-width "diagram"
slides are 1920 wide (846 tall, or 768 when the slide has a caption), the right-hand image of a
"split" slide is 1600 x 1070, and the architecture diagram is 1600 x 840 because doc.md uses it
too (doc images: 1600 wide, smallest text 30 px). Edit the HTML, rerun, rebuild the deck.

It also captures the "State 交給第 2 輪 Planner 的內容" block of ../../report/state-log.html for
doc.md, 1600 px wide, as the context list plus the table in two halves that each repeat the header
row, so no part is taller than the doc builder's 5.5 x 6.4 in image box (which would shrink it). Rebuild that page with
report/build_state_log.py first if the evidence it reads has changed.
"""
import argparse
import asyncio
import base64
import io
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

HERE = Path(__file__).resolve().parent
SIZES = {
    "slide-approach.html": (1600, 1070),
    "slide-architecture.html": (1600, 840),
    "slide-negotiation.html": (1920, 768),
    "slide-final-outline.html": (1920, 846),
    "slide-v7-comparison.html": (1920, 768),
}
PORT = 9333
STATE_LOG = HERE.parent.parent / "report" / "state-log.html"
# Narrow enough that the smallest text in the block (12.4 CSS px) lands above 30 px at 1600 px wide.
STATE_LOG_VIEW_W = 700
FIND_HANDOFF = r"""
(() => {
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,div,strong')]
    .filter(e => e.textContent.trim().startsWith('State 交給第 2 輪'));
  let el = heads.length ? heads[heads.length - 1] : null;
  while (el && !el.classList.contains('handoff')) el = el.parentElement;
  if (!el) return null;
  const r = el.getBoundingClientRect(), t = el.querySelector('table').getBoundingClientRect();
  const rows = [...el.querySelectorAll('table tr')].map(tr => {
    const b = tr.getBoundingClientRect(); return [b.top + scrollY, b.bottom + scrollY]; });
  const sizes = [...el.querySelectorAll('*')].map(n => parseFloat(getComputedStyle(n).fontSize)).filter(x => x > 0);
  return JSON.stringify({x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height,
                         tableTop: t.top + scrollY, tableBottom: t.bottom + scrollY, rows, minFont: Math.min(...sizes)});
})()
"""


async def shoot(chrome):
    profile = tempfile.mkdtemp(prefix="slide-shot-")
    proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise SystemExit("Chrome did not start")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**27) as ws:
            n = 0

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        if "error" in msg:
                            raise RuntimeError(msg["error"])
                        return msg["result"]

            await cmd("Page.enable")
            for name, (w, h) in SIZES.items():
                # Fix the viewport to the target size; a plain --window-size screenshot clips the bottom.
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
                await cmd("Page.navigate", url=(HERE / name).as_uri())
                for _ in range(100):
                    r = await cmd("Runtime.evaluate", returnByValue=True,
                                  expression="document.readyState==='complete' && document.fonts.status==='loaded'")
                    if r["result"]["value"]:
                        break
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.3)
                shot = await cmd("Page.captureScreenshot", format="png",
                                 clip={"x": 0, "y": 0, "width": w, "height": h, "scale": 1})
                out = HERE.parent / "img" / name.replace(".html", ".png")
                out.write_bytes(base64.b64decode(shot["data"]))
                print("wrote", out)

            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await cmd("Emulation.setDeviceMetricsOverride", width=STATE_LOG_VIEW_W, height=1200, deviceScaleFactor=1,
                      mobile=False)
            await cmd("Page.navigate", url=STATE_LOG.as_uri())
            await asyncio.sleep(1.5)
            value = (await cmd("Runtime.evaluate", expression=FIND_HANDOFF, returnByValue=True))["result"].get("value")
            if not value:
                raise SystemExit("handoff block not found in state-log.html")
            box = json.loads(value)
            scale = 1600 / box["w"]
            if box["minFont"] * scale < 30:
                raise SystemExit(f"smallest text would be {box['minFont'] * scale:.1f} px; lower STATE_LOG_VIEW_W")

            async def grab(y0, y1):
                shot = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                                 clip={"x": box["x"], "y": y0, "width": box["w"], "height": y1 - y0, "scale": scale})
                return Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")

            def save(im, part):
                out = HERE.parent / "img" / f"state-log-handoff-{part}.png"
                im.save(out)
                print("wrote", out, im.size)

            top = box["tableTop"] - 6
            save(await grab(box["y"], top), "context")
            rows = box["rows"]  # rows[0] is the header row
            half = 1 + (len(rows) - 1 + 1) // 2
            header = await grab(top, rows[0][1])
            for part, chunk in (("table-1", rows[1:half]), ("table-2", rows[half:])):
                body = await grab(chunk[0][0], chunk[-1][1] + 8)
                im = Image.new("RGB", (header.width, header.height + body.height), "white")
                im.paste(header, (0, 0))
                im.paste(body, (0, header.height))
                save(im, part)
    finally:
        proc.terminate()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chrome", default=r"C:/Program Files/Google/Chrome/Application/chrome.exe")
    asyncio.run(shoot(ap.parse_args().chrome))
