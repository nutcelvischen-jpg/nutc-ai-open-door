#!/usr/bin/env node
/**
 * Render videos/nutc_open_door/index.html (1920x1080 @ 30fps) via Metal GPU Headless Chrome CDP.
 * Modes:
 *   node scripts/render_muji_video.js --stills-only   # Render 26-frame contact sheet + 4 inspection stills
 *   node scripts/render_muji_video.js                 # Full 1080p30 video-only MP4 render + sheet_zh.png
 */
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const VIDEO_DIR = path.join(ROOT, "videos", "nutc_open_door");
const CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg";
const ART_SCRATCH = "/Users/chenchunchih/.gemini/antigravity/brain/f2c8e357-2f7b-4554-87c9-fc9f391a45c8/scratch";
const FPS = 30;
const STILLS_ONLY = process.argv.includes("--stills-only");
const WORKERS = STILLS_ONLY ? 1 : 6;

async function startChromeWorker(fileUrl) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "muji-cdp-"));
  const chrome = spawn(CHROME_BIN, [
    "--headless=new",
    "--no-sandbox",
    "--disable-component-update",
    "--hide-scrollbars",
    "--remote-debugging-port=0",
    `--user-data-dir=${tmpDir}`,
    "--window-size=1920,1080",
    "--force-device-scale-factor=1",
    fileUrl
  ], { stdio: ["ignore", "ignore", "pipe"] });

  const wsUrl = await new Promise((resolve, reject) => {
    let err = "";
    chrome.stderr.on("data", (d) => {
      err += d.toString();
      const m = err.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (m) resolve(m[1]);
    });
    chrome.on("exit", (code) => reject(new Error(`Chrome exited ${code}: ${err.slice(-300)}`)));
  });

  const cdp = await new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let nextId = 0;
    const pending = new Map();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { r, j } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) j(new Error(msg.error.message));
        else r(msg.result);
      }
    };
    ws.onopen = () => resolve({
      send: (method, params = {}, sessionId) => new Promise((r, j) => {
        const id = ++nextId;
        pending.set(id, { r, j });
        ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
      }),
      close: () => ws.close()
    });
    ws.onerror = reject;
  });

  const { targetInfos } = await cdp.send("Target.getTargets");
  const pageTarget = targetInfos.find((t) => t.type === "page");
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId: pageTarget.targetId, flatten: true });
  await cdp.send("Page.enable", {}, sessionId);
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1920,
    height: 1080,
    deviceScaleFactor: 1,
    mobile: false
  }, sessionId);

  for (let i = 0; i < 120; i++) {
    const r = await cdp.send("Runtime.evaluate", { expression: "Boolean(window.__ready)", returnByValue: true }, sessionId);
    if (r.result && r.result.value) {
      await cdp.send("Runtime.evaluate", { expression: "window.__ready", awaitPromise: true }, sessionId);
      break;
    }
    await new Promise((r) => setTimeout(r, 100));
  }

  return { chrome, tmpDir, cdp, sessionId };
}

function stopWorker(w) {
  try { w.cdp.close(); } catch (_) {}
  try { w.chrome.kill("SIGKILL"); } catch (_) {}
  try { fs.rmSync(w.tmpDir, { recursive: true, force: true }); } catch (_) {}
}

function buildKeyframes(tl) {
  const pts = [];
  for (const sc of tl.scenes) {
    sc.lines.forEach((ln, idx) => {
      const t = ln.start + (ln.end - ln.start) * 0.62;
      pts.push({ tag: `${sc.id}_${idx + 1}`, t: Number(t.toFixed(3)) });
    });
  }
  pts.push({ tag: "end_hold", t: Number(Math.max(0, tl.total - 1.4).toFixed(3)) });
  return pts;
}

async function captureContactSheet(worker, tl) {
  const stillsTmp = fs.mkdtempSync(path.join(os.tmpdir(), "muji-stills-"));
  const keyframes = buildKeyframes(tl);
  const keyPaths = [];
  const inspectMap = new Map([
    ["s01_3", "muji_s01_portal.png"],
    ["s02_3", "muji_s02_fde.png"],
    ["s04_3", "muji_s04_studio.png"],
    ["s05_4", "muji_s05_sandbox.png"],
    ["s06_3", "muji_s06_four_doors.png"],
  ]);
  fs.mkdirSync(ART_SCRATCH, { recursive: true });

  for (let i = 0; i < keyframes.length; i++) {
    const kf = keyframes[i];
    await worker.cdp.send("Runtime.evaluate", { expression: `window.__seek(${kf.t})`, returnByValue: true }, worker.sessionId);
    const { data } = await worker.cdp.send("Page.captureScreenshot", { format: "png" }, worker.sessionId);
    const p = path.join(stillsTmp, `kf_${String(i).padStart(2, "0")}_${kf.tag}.png`);
    const buf = Buffer.from(data, "base64");
    fs.writeFileSync(p, buf);
    keyPaths.push(p);
    if (inspectMap.has(kf.tag)) {
      fs.writeFileSync(path.join(ART_SCRATCH, inspectMap.get(kf.tag)), buf);
    }
  }

  fs.mkdirSync(path.join(VIDEO_DIR, "stills"), { recursive: true });
  fs.mkdirSync(path.join(ROOT, "docs", "assets"), { recursive: true });
  const sheetOut1 = path.join(VIDEO_DIR, "stills", "sheet_zh.png");
  const sheetOut2 = path.join(ROOT, "docs", "assets", "sheet_zh.png");

  const pyCode = `
import json, sys
from PIL import Image
paths = json.loads(sys.argv[1])
cols, rows = 4, 7
tw, th, gap = 480, 270, 6
W = cols * tw + (cols - 1) * gap
H = rows * th + (rows - 1) * gap
sheet = Image.new("RGB", (W, H), (213, 206, 192))
for idx in range(cols * rows):
    r, c = divmod(idx, cols)
    x = c * (tw + gap)
    y = r * (th + gap)
    if idx < len(paths):
        im = Image.open(paths[idx]).convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        sheet.paste(im, (x, y))
    else:
        sheet.paste(Image.new("RGB", (tw, th), (237, 232, 221)), (x, y))
sheet.save(sys.argv[2], optimize=True)
sheet.save(sys.argv[3], optimize=True)
print(f"SHEET SAVED: {sheet.size} -> {sys.argv[2]} & {sys.argv[3]}")
`;
  const out = execFileSync("python3", ["-c", pyCode, JSON.stringify(keyPaths), sheetOut1, sheetOut2], { encoding: "utf8" });
  process.stdout.write(out);
  fs.rmSync(stillsTmp, { recursive: true, force: true });
}

async function renderFullVideo(workers, tl) {
  const totalFrames = Math.ceil(tl.total * FPS);
  const outDir = path.join(VIDEO_DIR, "out");
  fs.mkdirSync(outDir, { recursive: true });
  const outMp4 = path.join(outDir, "nutc_open_door_zh.mp4");

  const ff = spawn(FFMPEG_BIN, [
    "-y",
    "-loglevel", "error",
    "-f", "image2pipe",
    "-vcodec", "mjpeg",
    "-framerate", String(FPS),
    "-i", "pipe:0",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
    outMp4
  ], { stdio: ["pipe", "inherit", "inherit"] });

  const ffExit = new Promise((resolve, reject) => {
    ff.on("error", reject);
    ff.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}`)));
  });

  let nextAssign = 0;
  let nextWrite = 0;
  const MAX_AHEAD = 36;
  const frameBuf = new Map();
  let drainWaiters = [];
  let writing = false;

  const wakeWaiters = () => {
    const cur = drainWaiters;
    drainWaiters = [];
    cur.forEach((fn) => fn());
  };

  async function flushOrdered() {
    if (writing) return;
    writing = true;
    try {
      while (frameBuf.has(nextWrite)) {
        const buf = frameBuf.get(nextWrite);
        frameBuf.delete(nextWrite);
        nextWrite++;
        const ok = ff.stdin.write(buf);
        if (!ok) {
          await new Promise((res) => ff.stdin.once("drain", res));
        }
        wakeWaiters();
      }
    } finally {
      writing = false;
    }
  }

  const t0 = performance.now();
  await Promise.all(workers.map(async (w) => {
    while (true) {
      while (nextAssign >= nextWrite + MAX_AHEAD && nextAssign < totalFrames) {
        await new Promise((res) => drainWaiters.push(res));
      }
      if (nextAssign >= totalFrames) break;
      const f = nextAssign++;
      const tSec = (f / FPS).toFixed(5);
      await w.cdp.send("Runtime.evaluate", { expression: `window.__seek(${tSec})`, returnByValue: true }, w.sessionId);
      const { data } = await w.cdp.send("Page.captureScreenshot", {
        format: "jpeg",
        quality: 95,
        optimizeForSpeed: true
      }, w.sessionId);
      frameBuf.set(f, Buffer.from(data, "base64"));
      await flushOrdered();
      if (f > 0 && f % 600 === 0) {
        const dt = ((performance.now() - t0) / 1000).toFixed(1);
        console.log(`  rendered ${f}/${totalFrames} frames (${dt}s)`);
      }
    }
  }));

  await flushOrdered();
  ff.stdin.end();
  await ffExit;
  const dt = ((performance.now() - t0) / 1000).toFixed(2);
  console.log(`✓ Rendered ${totalFrames} frames in ${dt}s (${(totalFrames / Number(dt)).toFixed(1)} fps) -> ${outMp4}`);
}

(async () => {
  const tl = JSON.parse(fs.readFileSync(path.join(VIDEO_DIR, "timeline_zh.json"), "utf8"));
  const fileUrl = "file://" + path.join(VIDEO_DIR, "index.html");
  const workers = await Promise.all(Array.from({ length: WORKERS }, () => startChromeWorker(fileUrl)));
  try {
    console.log(`▶ Chrome GPU workers ready (${WORKERS}), capturing 26 MUJI contact-sheet stills...`);
    await captureContactSheet(workers[0], tl);
    if (!STILLS_ONLY) {
      console.log(`▶ Rendering full 1080p30 sequence (total=${tl.total}s, ${Math.ceil(tl.total * FPS)} frames)...`);
      await renderFullVideo(workers, tl);
    }
  } finally {
    workers.forEach(stopWorker);
  }
})();
