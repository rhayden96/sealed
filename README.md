Sealed

Nothing injects until policy unseals it.

A small app (:5174) can break on purpose. A console (:5173) is the only thing allowed to break it. Catalog and policy decide what’s legal. A planner may suggest the next draft. It never gets the key.

docker compose up --build

Then open http://localhost:5173 and http://localhost:5174.

That’s the product. Everything below is optional.



Two-minute demo

Two windows. Console left, app right.





Console → Game day → Start demo day.



Step 1 handler_latency → Approve + unseal. App feels slow. Abort this step.



Step 2 redis_down → Approve + unseal. App login fail-closes. Abort this step.



Step 3 worker_drop → Approve + unseal. Some jobs drop. Health may stay green — watch the job list, not the pill.



Abort this step → End day.

If you skip Approve + unseal, the app does not break. POST localhost:8080/_faults without the demo token returns 403 not_unsealed.



What you are looking at

















App :5174



Login, a slow action, jobs. This is the system under experiment.





Console :5173



Catalog, game day, tape. This is the clerk.





Target API :8080



Gated faults. Do not call this from the browser.





Control API :8081



Policy, drafts, seals, /agent/propose.

Three legal faults: Redis cut, handler delay, dropped jobs. No other ids.



Planner (optional)

Default planner is a stub: after an aborted redis_down seal it proposes a worker_drop draft. It does not unseal.

start.bat
start.bat --llama
start.bat --xai

./start.sh
./start.sh --llama
./start.sh --xai







Flag



Brain





none



stub





--llama



Ollama on the host (ollama serve, default llama3.2)





--xai



xAI — needs XAI_API_KEY in your environment

--llama mistral / --xai grok-4.5 override the model. LLM calls have a 20s timeout and fall back to stub. Same tools either way: list, explain, propose. No unseal tool. Demo works with neither Ollama nor a key.



Token

UNSEAL_TOKEN is a Compose demo secret on control and target only. The UI never sees it. Don’t reuse it outside this stack.



Docs





docs/WALKTHROUGH.md — click path



docs/SPEC.md — policy and objects



docs/RESEARCH.md — why this exists (if present)