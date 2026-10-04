# Suryodev

### Turn any website into a polished, narrated product video.

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/browser-Playwright-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: experimental](https://img.shields.io/badge/status-experimental-orange.svg)](#status)

Suryodev creates an end-to-end product demo from a reachable website URL. It discovers routes, understands visible product screens, writes a scene plan, generates narration, captures zoomed-out screens, adds animated presentation slides and background music, and exports a shareable MP4.

The input can be a local development server or a live website. A local source directory is optional and provides extra context for the narrative planner.

Created by **Suhas Bhairav** · [suhasbhairav.com](https://suhasbhairav.com)

## Why Suryodev

- Turns any reachable website into a product story.
- Focuses narration on capabilities, workflows, and user outcomes.
- Generates scene-specific voiceover with a strong closing value proposition.
- Presents the actual product beside animated feature bullets.
- Adapts presentation colors and typography to the captured website.
- Keeps the complete website viewport visible through browser zoom-out.
- Adds quiet looping background music beneath narration.
- Produces natural-length videos without a forced one-minute cutoff.

## How it works

```text
URL → route discovery → screenshots + visible text → scene plan → narration
    → zoomed-out capture → animated slides → music mix → MP4
```

## Requirements

- macOS or Linux (Windows may work with equivalent FFmpeg/Playwright setup)
- Python 3.11+
- FFmpeg
- Chromium installed through Playwright
- An OpenAI API key for scene planning
- A machine capable of running Chatterbox TTS; CPU works, while Apple Silicon/CUDA/MPS is recommended
- A website reachable from the machine running Suryodev

## Installation

```bash
git clone <your-repository-url>
cd suryodev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Alternatively, install the package in editable mode with `pip install -e .`.

Set credentials in `.env`:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5-nano
```

Keep API keys out of source control. The `.env` file should remain local.

## Quick start

Start the product you want to demonstrate, then run:

```bash
python main.py --url http://localhost:3000
```

For a live website:

```bash
python main.py --url https://example.com
```

The result is written to `output/demo.mp4`. Intermediate route screenshots, the scene plan, narration WAVs, and raw screen video are retained under `output/run-*`.

## Command reference

```bash
python main.py \
  --url https://example.com \
  --project ../optional-local-project \
  --output output/example-demo.mp4 \
  --model turbo \
  --music intro_music_gemini.mp3 \
  --screenshot-scale 0.78 \
  --duration 90 \
  --headed
```

| Option | Purpose |
| --- | --- |
| `--url` | Required website URL, or set `DEMO_URL` in `.env`. Supports local and live sites. |
| `--project` | Optional local source tree for richer product context. |
| `--output` | MP4 output path; defaults to `output/demo.mp4`. |
| `--model` | `turbo` or `nano`; Turbo is the default. |
| `--voice` | Authorized voice reference WAV for cloning. |
| `--music` | Background track, looped at low volume; defaults to `intro_music_gemini.mp3`. |
| `--screenshot-scale` | Browser zoom-out used to fit the complete screen; defaults to `0.78`. |
| `--duration` | Optional target guidance, never a hard cutoff. |
| `--headed` | Show the Chromium recording window. |

For a smaller screen capture:

```bash
python main.py --url http://localhost:3000 --screenshot-scale 0.65
```

## Docker

```bash
docker build -t suryodev .
docker run --rm \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -v "$PWD/output:/app/output" \
  suryodev --url https://example.com
```

For a host-local website on macOS/Windows, use `http://host.docker.internal:3000`.

## Voice references and music

Only use voice references you own or have permission to use. Chatterbox may embed its documented Perth watermark in generated audio. Background music is mixed quietly beneath narration and looped until narration ends.

## Troubleshooting

- **URL unavailable:** start the local server, verify the port, and check network access.
- **Chromium missing:** run `playwright install chromium`.
- **FFmpeg missing:** install it with `brew install ffmpeg` or your Linux package manager.
- **Generic fallback narration:** check `OPENAI_API_KEY`, network access, and the model name.
- **Screen clipped:** lower `--screenshot-scale`, such as `0.65`.

## Status

Suryodev is an experimental creator tool. Inspect generated narration and visuals before publishing.

## Roadmap

- Reusable branded templates and visual themes.
- Better interaction recording for forms, menus, and authenticated flows.
- Captions, chapter markers, cloud rendering, and batch generation.
- Additional voice providers and multilingual narration.

## License

Suryodev is released under the [MIT License](LICENSE).
