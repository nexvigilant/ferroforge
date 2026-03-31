#!/usr/bin/env python3
"""
Local Inference Proxy — routes to Ollama on localhost:11434.

Models:
  - qwen2.5:3b — structured classification, summarization, extraction
  - nomic-embed-text — 768-dim embeddings

Zero API cost. CPU-only. ~2-5s for generation, ~100ms for embeddings.
"""

import json
import sys
import urllib.request
import urllib.error


import json

def ensure_str(val) -> str:
    """Coerce any input to string safely to prevent AttributeError."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        try:
            return json.dumps(val)
        except Exception:
            return str(val)
    return str(val)

def get_int_param(args: dict, key: str, default: int, min_val: int = None, max_val: int = None) -> int:
    """Safely parse integer parameter with optional clamping."""
    val = args.get(key)
    if val is None:
        return default
    try:
        res = int(val)
    except (ValueError, TypeError):
        return default
    if min_val is not None:
        res = max(res, min_val)
    if max_val is not None:
        res = min(res, max_val)
    return res



OLLAMA_URL = "http://localhost:11434"
GEN_MODEL = "qwen2.5:3b"
EMBED_MODEL = "nomic-embed-text"
TIMEOUT = 30


def _ollama_generate(prompt: str, system: str = "") -> str:
    payload = json.dumps({
        "model": GEN_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return data.get("response", "")


def _ollama_embed(text: str) -> list[float]:
    payload = json.dumps({
        "model": EMBED_MODEL,
        "prompt": text,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return data.get("embedding", [])


# ─── Tools ───────────────────────────────────────────────────────────────────

def classify(args: dict) -> dict:
    text = str(args.get("text", ""))
    categories = str(args.get("categories", ""))
    context = str(args.get("context", ""))

    if not text or not categories:
        return {"error": "text and categories required"}

    system = f"You are a classifier. Context: {context}" if context else "You are a classifier."
    prompt = (
        f"Classify the following text into exactly one of these categories: {categories}\n\n"
        f"Text: {text}\n\n"
        f"Reply with JSON only: {{\"category\": \"...\", \"confidence\": \"high/medium/low\", \"reasoning\": \"one sentence\"}}"
    )

    raw = _ollama_generate(prompt, system)
    try:
        # Try to parse JSON from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            result["model"] = GEN_MODEL
            result["local"] = True
            return result
    except json.JSONDecodeError:
        pass

    return {"category": raw.strip(), "confidence": "low", "reasoning": "Could not parse structured output", "model": GEN_MODEL, "local": True}


def embed(args: dict) -> dict:
    text = str(args.get("text", ""))
    if not text:
        return {"error": "text required"}

    embedding = _ollama_embed(text)
    return {
        "embedding": embedding,
        "dimensions": len(embedding),
        "model": EMBED_MODEL,
        "local": True,
    }


def summarize(args: dict) -> dict:
    text = str(args.get("text", ""))
    max_sentences = get_int_param(args, "max_sentences", 3)

    if not text:
        return {"error": "text required"}

    prompt = f"Summarize the following in {max_sentences} sentences:\n\n{text[:2000]}"
    raw = _ollama_generate(prompt, "You are a concise summarizer. Output only the summary, no preamble.")
    words = len(raw.split())

    return {"summary": raw.strip(), "word_count": words, "model": GEN_MODEL, "local": True}


def extract_json(args: dict) -> dict:
    text = str(args.get("text", ""))
    schema = str(args.get("schema", ""))

    if not text or not schema:
        return {"error": "text and schema required"}

    fields = [f.strip() for f in schema.split(",")]
    field_json = ", ".join(f'"{f}": "..."' for f in fields)

    prompt = (
        f"Extract the following fields from the text: {schema}\n\n"
        f"Text: {text[:2000]}\n\n"
        f"Reply with JSON only: {{{field_json}}}"
    )

    raw = _ollama_generate(prompt, "You are a data extractor. Output only valid JSON.")
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            extracted = json.loads(raw[start:end])
            return {"extracted": extracted, "model": GEN_MODEL, "local": True}
    except json.JSONDecodeError:
        pass

    return {"extracted": {"raw": raw.strip()}, "model": GEN_MODEL, "local": True, "parse_failed": True}


def status(_args: dict) -> dict:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        models = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 2)} for m in data.get("models", [])]
        total_gb = sum(m["size_gb"] for m in models)
        return {
            "status": "online",
            "endpoint": OLLAMA_URL,
            "models": models,
            "total_model_size_gb": round(total_gb, 2),
            "inference": "CPU-only (i9-13900H, 20 threads)",
        }
    except Exception as e:
        return {"status": "offline", "error": str(e)}


# ─── Dispatch ─────────────────────────────────────────────────────────────────

HANDLERS = {
    "classify": classify,
    "embed": embed,
    "summarize": summarize,
    "extract-json": extract_json,
    "status": status,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        json.dump({"error": "No input"}, sys.stdout)
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("args") or envelope.get("arguments") or {}

    for prefix in ("local_nexvigilant_com_",):
        if tool.startswith(prefix):
            tool = tool[len(prefix):]
            break

    tool_normalized = tool.replace("_", "-")
    handler = HANDLERS.get(tool_normalized) or HANDLERS.get(tool)
    if not handler:
        json.dump({"error": f"Unknown tool: {tool}", "available": list(HANDLERS.keys())}, sys.stdout)
        return

    try:
        json.dump(handler(args), sys.stdout, default=str)
    except urllib.error.URLError as e:
        json.dump({"error": f"Ollama not reachable: {e}", "hint": "Run: ollama serve"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
