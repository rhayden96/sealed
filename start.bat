@echo off
setlocal EnableExtensions

set "LLM_BASE_URL="
set "LLM_MODEL="

if "%~1"=="" goto stub
if /I "%~1"=="--llama" goto llama
if /I "%~1"=="--xai" goto xai
echo Usage: start.bat [--llama [model] ^| --xai [model]]
exit /b 1

:llama
set "LLM_BASE_URL=http://host.docker.internal:11434/v1"
if "%~2"=="" (set "LLM_MODEL=llama3.2") else (set "LLM_MODEL=%~2")
echo Planner: Ollama %LLM_MODEL% at %LLM_BASE_URL%
echo Need: ollama serve (and ollama pull %LLM_MODEL%)
goto up

:xai
if "%XAI_API_KEY%"=="" (
  echo Set XAI_API_KEY first.
  exit /b 1
)
set "LLM_BASE_URL="
if "%~2"=="" (set "LLM_MODEL=grok-4.5") else (set "LLM_MODEL=%~2")
echo Planner: xAI %LLM_MODEL%
goto up

:stub
echo Planner: stub (no LLM)
goto up

:up
docker compose up --build
