# Sealed

Nothing injects until policy unseals it.

A small app on port 5174 can break on purpose.
A console on port 5173 is the only thing allowed to break it.
A planner may propose a draft. It never gets the key.

```
python start.py
```

Or `start.bat` / `start.sh`. Menu: **1 stub**, **2 llama** (Ollama), **3 xai**. Writes `.env.local`, then `docker compose --env-file .env.local up --build`. Optional: `pip install -e ".[cli]"` for rich prompts.

```
docker compose up --build
```

Then open:

- Console — http://localhost:5173
- App — http://localhost:5174

## Demo

Two windows. Console left, app right.

1. Game day → Start demo day
2. handler_latency → Approve + unseal → app feels slow → Abort this step
3. redis_down → Approve + unseal → login fail-closes → Abort this step
4. worker_drop → Approve + unseal → some jobs drop → Abort this step → End day

Skip Approve + unseal and the app does not break.

## Ports

- 5174 app (the thing you break)
- 5173 console (the clerk)
- 8080 target API
- 8081 control API

## Planner

Default is a stub. Optional:

    start.bat
    start.bat --llama
    start.bat --xai

`--llama` needs `ollama serve`. `--xai` needs `XAI_API_KEY`.
No flag still runs the demo.

## Token

UNSEAL_TOKEN is demo-only on control and target.
The UI never sees it.