#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--llama [model] | --xai [model]]" >&2
  exit 1
}

export LLM_BASE_URL="${LLM_BASE_URL:-}"
export LLM_MODEL="${LLM_MODEL:-}"

case "${1:-}" in
  --llama)
    export LLM_BASE_URL="http://host.docker.internal:11434/v1"
    export LLM_MODEL="${2:-llama3.2}"
    echo "Planner: Ollama ${LLM_MODEL} at ${LLM_BASE_URL}"
    echo "Need: ollama serve (and ollama pull ${LLM_MODEL})"
    ;;
  --xai)
    if [[ -z "${XAI_API_KEY:-}" ]]; then
      echo "Set XAI_API_KEY first." >&2
      exit 1
    fi
    export LLM_BASE_URL=""
    export LLM_MODEL="${2:-grok-4.5}"
    echo "Planner: xAI ${LLM_MODEL}"
    ;;
  "")
    export LLM_BASE_URL=""
    echo "Planner: stub (no LLM)"
    ;;
  *)
    usage
    ;;
esac

docker compose up --build
