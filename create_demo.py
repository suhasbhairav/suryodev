"""Analyze a Next.js project and render a narrated product-demo MP4."""
from __future__ import annotations
import argparse, base64, json, os, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv

IGNORE = {"node_modules", ".next", ".git", "dist", "build", "coverage", "__pycache__"}
EXTS = {".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".css", ".scss", ".html", ".py"}

def snapshot(root: Path | None, limit=120000):
    if root is None:
        return "No local project source was provided. Use the discovered live routes, screenshots, and visible page content as the source of truth."
    root = root.resolve()
    files, content = [], []
    seen = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(x in IGNORE for x in p.parts): continue
        seen += 1
        if seen > 1500: break
        rel = p.relative_to(root); files.append(str(rel))
        if p.suffix.lower() in EXTS and p.stat().st_size < 80000:
            try: content.append(f"\n--- {rel} ---\n{p.read_text(errors='ignore')[:8000]}")
            except OSError: pass
    return ("PROJECT FILES:\n" + "\n".join(files) + "\n\nSELECTED CONTENT:" + "".join(content))[:limit]

def discover_and_capture(base_url, run, headed=False, same_page_only=True):
    """Discover only same-origin hrefs from the live app and capture each route."""
    from playwright.sync_api import sync_playwright
    parsed_base = urlparse(base_url)
    origin = parsed_base.netloc
    origin_url = f"{parsed_base.scheme}://{origin}"
    found, queue = [], [base_url]
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width":1440,"height":900})
        page = ctx.new_page()
        while queue and len(found) < 12:
            target = queue.pop(0)
            parsed = urlparse(target)
            route = parsed.path or "/"
            if not route.startswith("/"): route = "/" + route
            if parsed.netloc != origin or route in seen or any(x in route for x in ["/_next", ".png", ".jpg", ".svg", ".css", ".js"]): continue
            seen.add(route)
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1800)
                shot = run / "screens" / ("root" if route == "/" else re.sub(r"[^a-zA-Z0-9_-]", "_", route.strip("/")))
                shot = shot.with_suffix(".png"); shot.parent.mkdir(exist_ok=True)
                page.screenshot(path=str(shot), full_page=True)
                title = page.title()
                text = page.locator("body").inner_text(timeout=5000)[:3000]
                found.append({"path": route, "url": page.url, "title": title, "text": text, "screenshot": shot.name})
                if not same_page_only:
                    for href in page.locator("a").evaluate_all("els => els.map(e => e.href)"):
                        if urlparse(href).netloc == origin and urlparse(href).path not in seen: queue.append(href)
            except Exception as exc:
                print(f"Skipping route {route}: {exc}", file=sys.stderr)
        ctx.close(); browser.close()
    (run / "routes.json").write_text(json.dumps(found, indent=2))
    return found

def plan_with_gpt(text, routes, run, target_seconds=None):
    route_text = "\n\n".join(f"ROUTE {r['path']}\nTITLE: {r['title']}\nVISIBLE TEXT:\n{r['text']}" for r in routes)
    length_guidance = f"Aim for approximately {target_seconds} seconds, but prioritize a complete flow." if target_seconds else "Use as much time as the complete story needs; there is no fixed duration limit."
    prompt = f'''Analyze this product and create a professional narrated product demo.
Return ONLY valid JSON: {{"title":"...","scenes":[{{"id":"scene-1","spoken":"...","caption":"...","bullet_points":["key capability","user benefit"],"duration_seconds":8,"path":"/","focus":"optional CSS selector","action":"hold|scroll|click"}}]}}
Rules: create as many scenes as needed for a coherent end-to-end flow, with no fixed total duration. {length_guidance}
Narrate the story as a guided product walkthrough. Each scene must explicitly connect to the next with natural transition language such as "Now let's move to...", "Next, we can...", "From there...", or "Finally..." so the audience always understands why the video is changing screens. Start with the user problem, then show the key product workflow from start to finish, and end with a strong closing scene explaining why this product is valuable and why someone should use it. The final spoken line and caption must clearly communicate the product's strongest reason to use it.
Focus only on core product capabilities, meaningful workflows, user benefits, and measurable or observable outcomes. Do not narrate visual design or website presentation details: never talk about typography, fonts, colors, spacing, layout, buttons as design elements, navigation menus, contact pages, about pages, pricing pages, testimonials, or generic marketing copy unless that item is itself a core product feature being demonstrated. Do not describe a screen merely because it exists; explain what the user can accomplish there.
For every scene, provide 2 or 3 short bullet_points that reinforce the specific capability visible in that scene. Bullets must be concrete, benefit-led, and readable in under two seconds each; never use design commentary or generic filler.
Narration must explain the product shown on screen; every path MUST exactly match one of the discovered routes below; never invent routes or features; use ellipses for emphasis; do not zoom or transform the page; native Chatterbox tags only when natural; captions tag-free; no SSML or markdown.

DISCOVERED ROUTES:
{route_text}

PROJECT SOURCE SUMMARY:
{text}'''
    content = [{"type":"input_text", "text":prompt}]
    for route in routes:
        image = run / "screens" / route["screenshot"]
        content.append({"type":"input_image", "image_url":"data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()})
    provider = os.getenv("AI_PROVIDER", "auto").lower()

    def call_ollama():
        ollama_content = [{"type": "text", "text": prompt}]
        for route in routes:
            image = run / "screens" / route["screenshot"]
            ollama_content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()}})
        payload = json.dumps({
            "model": os.getenv("OLLAMA_MODEL", "gemma4"),
            "stream": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "5m"),
            "messages": [{"role": "system", "content": "You produce strict JSON for a visual product-demo pipeline. Use screenshots as ground truth."}, {"role": "user", "content": prompt, "images": [x["image_url"]["url"].split(",", 1)[1] for x in ollama_content if x["type"] == "image_url"]}]
        }).encode()
        request = urllib.request.Request(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode())["message"]["content"]

    def call_openai():
        from openai import OpenAI
        r = OpenAI(timeout=60.0, max_retries=1).responses.create(model=os.getenv("OPENAI_MODEL", "gpt-5-nano"), reasoning={"effort":"minimal"}, input=[
            {"role":"system", "content":"You produce strict JSON for a visual product-demo pipeline. Use screenshots as ground truth."}, {"role":"user", "content":content}])
        return r.output_text

    if provider == "ollama":
        raw = call_ollama()
    elif provider == "openai":
        raw = call_openai()
    else:
        try:
            if os.getenv("OPENAI_API_KEY"):
                raw = call_openai()
            else:
                raise RuntimeError("OPENAI_API_KEY is not configured")
        except Exception as openai_error:
            print(f"OpenAI unavailable ({openai_error}); trying Ollama {os.getenv('OLLAMA_MODEL', 'gemma4')}...", file=sys.stderr)
            raw = call_ollama()
    raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip(), flags=re.I)
    result = json.loads(raw)
    if not result.get("scenes"): raise ValueError("No scenes returned")
    allowed = {r["path"] for r in routes}
    for scene in result["scenes"]:
        if scene.get("path") not in allowed: scene["path"] = routes[0]["path"]
    return result

def fallback():
    scenes = [
        ("Let's begin with the problem this product is designed to solve... it turns a complex workflow into a clear, focused experience.", "Start with the problem.", 8, 1.0, ""),
        ("Now let's move to the core workflow... this is where the important work comes together in one place.", "Move into the core workflow.", 8, 1.15, "main"),
        ("Next, we can see how the product helps you move faster... without losing the context needed for good decisions.", "Work faster with context.", 9, 1.25, "button"),
        ("From there, the workflow becomes simpler and more focused, making it easier to take the next meaningful action.", "Turn insight into action.", 9, 1.1, ""),
        ("Finally, this brings the full journey together... from the original problem to a clear, confident outcome.", "Complete the journey.", 9, 1.0, ""),
        ("That is why this product matters... it turns the full journey into a workflow that is clear, fast, and easy to act on. Use it to move from uncertainty to a confident outcome.", "Why use it? Clarity from start to finish.", 12, 1.0, ""),
    ]
    bullets = [
        ["Clarify the user problem", "Start with a focused workflow"],
        ["Bring key work into one place", "Keep the important context visible"],
        ["Move from insight to action", "Make decisions with confidence"],
        ["Reduce unnecessary steps", "Keep the workflow focused"],
        ["Follow the journey end to end", "Turn work into an outcome"],
        ["Clear value from the first step", "Faster path to a confident outcome"],
    ]
    return {"title":"Product demo", "scenes":[{"id":f"scene-{i+1}","spoken":a,"caption":b,"bullet_points":bullets[i],"duration_seconds":c,"path":"/","zoom":d,"focus":e,"action":"hold"} for i,(a,b,c,d,e) in enumerate(scenes)]}

def ensure_closing_scene(plan, routes):
    """Guarantee an explicit value-proposition ending in every generated demo."""
    last = plan.get("scenes", [])[-1] if plan.get("scenes") else {}
    if not re.search(r"\b(why|use|valuable|value|worth|amazing|helps you|should)\b", str(last.get("spoken", "")), re.I):
        plan.setdefault("scenes", []).append({
            "id": "closing-scene",
            "spoken": f"That is why {plan.get('title', 'this product')} is worth using... it brings the important journey together in one clear, focused experience, so you can move from problem to outcome with confidence.",
            "caption": "Why use it? Turn the journey into the outcome.",
            "bullet_points": ["Clear value from start to finish", "Move from problem to outcome"],
            "duration_seconds": 11,
            "path": routes[-1]["path"],
            "zoom": 1.0,
            "focus": "",
            "action": "hold"
        })
    return plan

def synthesize(plan, run, voice, model_name):
    import soundfile as sf, torch
    import perth
    if perth.PerthImplicitWatermarker is None:
        class _NoopWatermarker:
            def apply_watermark(self, wav, sample_rate=None): return wav
        perth.PerthImplicitWatermarker = _NoopWatermarker
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    if model_name == "nano":
        print("Nano is not exposed by the current Python class; using the documented Turbo loader.", file=sys.stderr)
    tts = ChatterboxTurboTTS.from_pretrained(device=device)
    for s in plan["scenes"]:
        out = run / f"{s['id']}.wav"; kw = {"audio_prompt_path":str(voice)} if voice else {}
        wav = tts.generate(s["spoken"], **kw); sf.write(out, wav.squeeze().detach().cpu().numpy(), tts.sr)
        s["audio"] = out.name; s["audio_duration_seconds"] = round(len(wav.squeeze()) / tts.sr, 3)

def record(url, plan, run, headed, screenshot_scale=0.78):
    from playwright.sync_api import sync_playwright
    vd = run / "playwright-video"; vd.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width":1440,"height":900}, record_video_dir=str(vd), record_video_size={"width":1440,"height":900})
        page = ctx.new_page()
        navigation_started = time.monotonic()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)
        initial_offset = max(0.0, time.monotonic() - navigation_started)
        page.evaluate('''() => {
            const style = getComputedStyle(document.body);
            const button = document.querySelector('button, a[role="button"], [class*="button"]');
            const buttonStyle = button ? getComputedStyle(button) : null;
            const accent = buttonStyle?.backgroundColor && buttonStyle.backgroundColor !== 'rgba(0, 0, 0, 0)'
                ? buttonStyle.backgroundColor : (buttonStyle?.color || '#b7f34a');
            const css = document.createElement('style');
            css.id = 'demo-motion-overlay-style';
            css.textContent = `
                #demo-motion-overlay { position: fixed; z-index: 2147483647; left: 4vw; bottom: 7vh; width: min(37vw, 560px); padding: 24px 28px; color: ${style.color}; font-family: ${style.fontFamily}; background: color-mix(in srgb, ${style.backgroundColor} 86%, transparent); border: 1px solid color-mix(in srgb, ${accent} 45%, transparent); border-radius: 18px; box-shadow: 0 18px 55px rgba(0,0,0,.28); backdrop-filter: blur(14px); opacity: 0; transform: translateY(18px); transition: opacity .55s ease, transform .55s cubic-bezier(.2,.8,.2,1); }
                #demo-motion-overlay.visible { opacity: 1; transform: translateY(0); }
                #demo-motion-overlay .demo-kicker { color: ${accent}; font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; margin-bottom: 10px; }
                #demo-motion-overlay h2 { margin: 0 0 13px; font-size: clamp(20px, 2.1vw, 34px); line-height: 1.05; font-weight: 750; }
                #demo-motion-overlay ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
                #demo-motion-overlay li { display: flex; gap: 9px; align-items: flex-start; font-size: clamp(12px, 1vw, 16px); line-height: 1.3; opacity: .9; }
                #demo-motion-overlay li::before { content: '✓'; color: ${accent}; font-weight: 800; }
            `;
            document.head.appendChild(css);
        }''')
        for s in plan["scenes"]:
            parsed_base = urlparse(url)
            origin_url = f"{parsed_base.scheme}://{parsed_base.netloc}"
            target = urljoin(origin_url + "/", (s.get("path") or "/").lstrip("/"))
            if page.url != target:
                page.goto(target, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1800)
            had_previous_slide = page.evaluate('''() => {
                const oldSlide = document.querySelector('#demo-slide');
                if (oldSlide) {
                    oldSlide.style.opacity = '0';
                    oldSlide.style.transform = 'scale(.985)';
                }
                return Boolean(oldSlide);
            }''')
            if had_previous_slide:
                page.wait_for_timeout(420)
            page.evaluate('''() => {
                const oldSlide = document.querySelector('#demo-slide');
                oldSlide?.remove();
                document.querySelector('#demo-motion-overlay-style')?.remove();
                document.documentElement.style.overflow = '';
                document.body.style.overflow = '';
            }''')
            if s.get("action") == "scroll": page.mouse.wheel(0, 300)
            page.evaluate('''(scale) => {
                document.documentElement.style.zoom = String(scale);
                document.body.style.zoom = '';
            }''', screenshot_scale)
            screenshot_data = "data:image/png;base64," + base64.b64encode(page.screenshot(type="png", full_page=False)).decode()
            page.evaluate('''({scene, screenshot}) => {
                const rgb = value => (value.match(/[0-9]+(?:[.][0-9]+)?/g) || []).slice(0, 3).map(Number);
                const luminance = value => { const c = rgb(value); return c.length === 3 ? (0.2126*c[0] + 0.7152*c[1] + 0.0722*c[2]) : 245; };
                const bodyStyle = getComputedStyle(document.body);
                const rootStyle = getComputedStyle(document.documentElement);
                const rawBg = bodyStyle.backgroundColor !== 'rgba(0, 0, 0, 0)' ? bodyStyle.backgroundColor : rootStyle.backgroundColor;
                const darkSite = luminance(rawBg) < 145;
                const bg = rawBg && rawBg !== 'rgba(0, 0, 0, 0)' ? rawBg : (darkSite ? '#111510' : '#f5f7f4');
                const ink = darkSite ? '#f7faf4' : '#172018';
                const muted = darkSite ? 'rgba(247,250,244,.7)' : 'rgba(23,32,24,.68)';
                const accent = darkSite ? '#c8ff3d' : '#176b4d';
                document.querySelector('#demo-slide')?.remove();
                document.querySelector('#demo-motion-overlay-style')?.remove();
                const css = document.createElement('style'); css.id = 'demo-motion-overlay-style';
                css.textContent = `
                    html,body { background:${bg} !important; overflow:hidden !important; }
                    #demo-slide { position:fixed; inset:0; z-index:2147483647; padding:5vh 5vw; box-sizing:border-box; color:${ink}; font-family:${bodyStyle.fontFamily}; background:radial-gradient(circle at 78% 35%, ${darkSite ? 'rgba(200,255,61,.13)' : 'rgba(23,107,77,.13)'}, transparent 34%), linear-gradient(135deg, ${bg}, ${darkSite ? '#080b09' : '#ffffff'}); display:flex; align-items:center; gap:5vw; opacity:0; transform:scale(.985); animation:demo-slide-in .72s cubic-bezier(.2,.8,.2,1) forwards; transition:opacity .42s ease, transform .42s ease; }
                    #demo-slide .demo-copy { width:34%; max-width:520px; flex:none; opacity:0; transform:translateY(22px); animation:demo-copy-in .65s .08s forwards; }
                    #demo-slide .demo-kicker { color:${accent}; font-size:11px; font-weight:750; letter-spacing:.15em; text-transform:uppercase; margin-bottom:14px; }
                    #demo-slide h2 { margin:0 0 18px; font-size:clamp(25px,3.2vw,54px); line-height:1.02; letter-spacing:-.035em; font-weight:780; }
                    #demo-slide .demo-bullets { margin:0; padding:0; list-style:none; display:grid; gap:11px; color:${muted}; }
                    #demo-slide li { display:flex; gap:10px; align-items:flex-start; font-size:clamp(13px,1.1vw,18px); line-height:1.32; opacity:0; transform:translateX(-12px); animation:demo-bullet-in .5s forwards; }
                    #demo-slide li:nth-child(1) { animation-delay:.28s } #demo-slide li:nth-child(2) { animation-delay:.4s } #demo-slide li:nth-child(3) { animation-delay:.52s }
                    #demo-slide li::before { content:'✓'; color:${accent}; font-weight:850; }
                    #demo-slide .demo-screen { position:relative; width:61%; height:78vh; overflow:hidden; border-radius:16px; background:#fff; border:1px solid ${darkSite ? 'rgba(255,255,255,.22)' : 'rgba(0,0,0,.15)'}; box-shadow:0 26px 80px rgba(0,0,0,.3); opacity:0; transform:translateX(24px) scale(.985); animation:demo-screen-in .75s .12s forwards; }
                    #demo-slide .demo-screen > * { width:100% !important; height:100% !important; }
                    #demo-slide .demo-product-shot { display:block; object-fit:contain; object-position:center; background:${darkSite ? '#101411' : '#ffffff'}; }
                    @keyframes demo-slide-in { to { opacity:1; transform:scale(1) } } @keyframes demo-copy-in { to { opacity:1; transform:translateY(0) } } @keyframes demo-bullet-in { to { opacity:1; transform:translateX(0) } } @keyframes demo-screen-in { to { opacity:1; transform:translateX(0) scale(1) } }
                `;
                document.head.appendChild(css);
                const slide = document.createElement('main'); slide.id = 'demo-slide';
                const screen = document.createElement('div'); screen.className = 'demo-screen';
                const image = document.createElement('img'); image.className = 'demo-product-shot'; image.src = screenshot; image.alt = 'Product screen';
                screen.appendChild(image);
                const copy = document.createElement('section'); copy.className = 'demo-copy';
                const bullets = (scene.bullet_points || []).slice(0, 3).map(item => `<li>${item}</li>`).join('');
                copy.innerHTML = `<div class="demo-kicker">${scene.id === 'closing-scene' ? 'The outcome' : 'Key capability'}</div><h2>${scene.caption || ''}</h2><ul class="demo-bullets">${bullets}</ul>`;
                slide.append(copy, screen); document.body.appendChild(slide);
            }''', {"scene": s, "screenshot": screenshot_data})
            page.wait_for_timeout(int(float(s.get("audio_duration_seconds", s.get("duration_seconds",8))) * 1000))
        video = page.video
        if not video: raise RuntimeError("Playwright video was not created")
        out = run / "screen.webm"; page.close(); video.save_as(str(out)); ctx.close(); browser.close(); return out, initial_offset

def mux(screen, plan, run, output, initial_offset=0.0, music=None):
    concat = run / "audio.txt"; concat.write_text("\n".join(f"file '{(run/s['audio']).resolve().as_posix()}'" for s in plan["scenes"]))
    audio = run / "narration.wav"
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(audio)], check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Playwright records from page creation, while narration starts after the
    # initial navigation. Trim that recorded page-load lead-in instead of
    # delaying the voice, so the first spoken scene starts immediately on the
    # first usable product screen.
    video_input = ["-ss", f"{initial_offset:.3f}", "-stream_loop", "-1", "-i", str(screen)]
    music_input = ["-stream_loop", "-1", "-i", str(music)] if music else []
    if music:
        filter_complex = "[2:a]volume=1[narration];[1:a]volume=0.12[music];[narration][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        audio_args = ["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[aout]"]
    else:
        audio_args = ["-map", "0:v:0", "-map", "1:a:0"]
    subprocess.run(["ffmpeg","-y",*video_input,*music_input,"-i",str(audio),*audio_args,"-shortest","-c:v","libx264","-preset","medium","-crf","20","-c:a","aac","-movflags","+faststart",str(output)], check=True)

def main():
    load_dotenv()
    ap=argparse.ArgumentParser()
    ap.add_argument("--url",default=os.getenv("DEMO_URL"),help="Website URL to record; supports local and live sites (or set DEMO_URL)")
    ap.add_argument("--project",type=Path,help="Optional local project source for deeper narrative context")
    ap.add_argument("--music",type=Path,default=Path(__file__).resolve().parent / "intro_music_gemini.mp3",help="Optional looping background music file")
    ap.add_argument("--screenshot-scale",type=float,default=0.78,help="Browser scale used to fit the complete website inside each product frame (default: 0.78)")
    ap.add_argument("--duration",type=int,default=None,help="Optional target duration; never truncates a complete story"); ap.add_argument("--model",choices=["turbo","nano"],default="turbo"); ap.add_argument("--voice",type=Path); ap.add_argument("--output",type=Path,default=Path("output/demo.mp4")); ap.add_argument("--headed",action="store_true"); args=ap.parse_args()
    if not args.url: raise SystemExit("Provide --url https://example.com or set DEMO_URL in .env")
    same_page_only = os.getenv("CRAWL_SAME_PAGE_ONLY", "true").lower() in {"1", "true", "yes", "on"}
    if args.project and not args.project.exists(): raise SystemExit(f"Project not found: {args.project}")
    if args.music and not args.music.exists(): raise SystemExit(f"Music file not found: {args.music}")
    if not 0.4 <= args.screenshot_scale <= 1.0: raise SystemExit("--screenshot-scale must be between 0.4 and 1.0")
    if not shutil.which("ffmpeg"): raise SystemExit("ffmpeg is required on PATH")
    run=Path("output/run-"+time.strftime("%Y%m%d-%H%M%S")); run.mkdir(parents=True,exist_ok=True)
    print("Discovering routes and capturing screenshots...")
    routes = discover_and_capture(args.url, run, args.headed, same_page_only)
    if not routes: raise SystemExit("No same-origin application routes could be discovered")
    print(f"Discovered {len(routes)} routes: {', '.join(r['path'] for r in routes)}")
    print("Analyzing project and screenshots...")
    try: plan=plan_with_gpt(snapshot(args.project), routes, run, args.duration)
    except Exception as e:
        print(f"Narrative API unavailable ({e}); using route-aware fallback.",file=sys.stderr)
        plan=fallback()
        for i, scene in enumerate(plan["scenes"]): scene["path"] = routes[i % len(routes)]["path"]
    plan = ensure_closing_scene(plan, routes)
    print("Synthesizing narration..."); synthesize(plan,run,args.voice,args.model); (run/"narrative.json").write_text(json.dumps(plan,indent=2))
    print("Recording browser..."); screen, initial_offset=record(args.url,plan,run,args.headed,args.screenshot_scale); print(f"Muxing MP4 (audio offset: {initial_offset:.2f}s, background music: {args.music.name})..."); mux(screen,plan,run,args.output,initial_offset,args.music); print(f"Done: {args.output.resolve()}")

if __name__ == "__main__": main()
