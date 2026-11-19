"""Huginn AI: one AI service for the whole desktop, off until you turn it on (Settings › AI).

Where it runs:
    this computer   a model you choose runs here through llama.cpp (llama-server, from Ubuntu's archive; its Vulkan
                    backend uses any graphics card, else the processor). Nothing you ask leaves the computer.
    your accounts   Claude (Anthropic), OpenAI (ChatGPT's models), Gemini (Google), GitHub Models (the models behind
                    Copilot, with a GitHub token), Microsoft Azure OpenAI, OpenRouter (signing in once gives many
                    models on one account), and anything that speaks OpenAI's API (Ollama, LM Studio, a server of
                    your own). A chat subscription (ChatGPT Plus, Claude Pro, Gemini Advanced, Copilot Pro) doesn't
                    give other apps access: each service's key comes from its developer console and is billed there
                    (Gemini's and GitHub's have free tiers).

Where it shows (each can be turned off): Search everything (ask a question), Writer (rewrite, proofread,
summarise, continue), Mail (summarise, draft a reply, improve what you wrote), Code (explain, fix, write).

Nothing is sent anywhere until it's turned on and a place for it to run is chosen; then only what you ask it about
is sent, when you ask. The settings are ~/.config/huginn/ai.json (shared by every app, which follow changes at
once). Keys go in the Passwords vault (its "ai" drawer) when Passwords is set up and unlocked, else in a file only
you can read (~/.local/share/huginn/ai-keys.json, 0600).

    python3 huginn_ai.py serve MODEL     (internal) run the local model for everyone in this sign-in session, and
                                          stop it after a quarter of an hour unused
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "huginn" / "ai.json"
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "huginn"
KEYS = DATA / "ai-keys.json"
MODELS_DIR = DATA / "ai-models"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/huginn-{os.getuid()}") / "huginn"
SERVER_STATE = RUNTIME / "ai-server.json"
USED = RUNTIME / "ai-used"
IDLE_STOP = 15 * 60
SURFACES = ("search", "writer", "mail", "code")
HF = "https://huggingface.co"

# ------------------------------------------------------------------------------------------- where it can run
PROVIDERS = {
    "local": {"label": "On this computer", "kind": "openai", "base": "", "key": False,
              "about": "A model runs here. Nothing you ask leaves the computer. Downloads once, a few gigabytes."},
    "anthropic": {"label": "Claude", "maker": "Anthropic", "kind": "anthropic", "base": "https://api.anthropic.com/v1", "key": True,
                  "keys_at": "https://console.anthropic.com/settings/keys", "prefer": ["sonnet", "haiku", "opus"],
                  "about": "An API key from the Claude Console. Billed by Anthropic, separately from a Claude subscription."},
    "openai": {"label": "OpenAI", "maker": "ChatGPT's models", "kind": "openai", "base": "https://api.openai.com/v1", "key": True,
               "keys_at": "https://platform.openai.com/api-keys", "prefer": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini", "gpt-4"],
               "skip": ["embedding", "whisper", "tts", "dall-e", "image", "audio", "realtime", "moderation", "transcribe", "search"],
               "about": "ChatGPT's models, with an API key from the OpenAI Platform. Billed by OpenAI, separately from ChatGPT Plus."},
    "gemini": {"label": "Gemini", "maker": "Google", "kind": "openai", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "key": True,
               "keys_at": "https://aistudio.google.com/apikey", "prefer": ["flash", "pro"], "skip": ["embedding", "imagen", "veo", "tts", "aqa", "live", "image"],
               "about": "An API key from Google AI Studio (it has a free tier). Separate from a Gemini subscription."},
    "github": {"label": "GitHub Models", "maker": "GitHub · Copilot's models", "kind": "openai", "base": "https://models.github.ai/inference", "key": True,
               "keys_at": "https://github.com/settings/personal-access-tokens/new", "prefer": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
               "models_at": "https://models.github.ai/catalog/models",
               "about": "The models behind Copilot, with a GitHub token that may read models. Free, with daily limits."},
    "azure": {"label": "Azure OpenAI", "maker": "Microsoft", "kind": "openai", "base": "", "key": True, "header": "api-key",
              "keys_at": "https://ai.azure.com", "about": "Your Azure OpenAI (AI Foundry) resource: its address and key."},
    "openrouter": {"label": "OpenRouter", "maker": "Claude, GPT, Gemini and more", "kind": "openai", "base": "https://openrouter.ai/api/v1", "key": True,
                   "keys_at": "https://openrouter.ai/keys", "signin": True, "prefer": ["anthropic/claude-sonnet", "openai/gpt-5-mini", "google/gemini"],
                   "about": "Sign in once for many companies' models on one account, paid as you go."},
    "custom": {"label": "Another service", "maker": "Ollama, LM Studio, your own", "kind": "openai", "base": "", "key": False,
               "about": "Any server that speaks OpenAI's API: Ollama (http://127.0.0.1:11434/v1), LM Studio, or your own."},
}

# Models for this computer, run by llama.cpp, from Hugging Face (ggml-org is llama.cpp's own; Unsloth's where ggml-org
# has none). Each is found by its repository and quantisation; the exact file is looked up when it's fetched.
LOCAL_MODELS = [
    {"id": "gemma-4-e2b", "label": "Small", "name": "Gemma 4 E2B", "maker": "Google", "repo": "unsloth/gemma-4-E2B-it-GGUF", "quant": "Q4_K_M",
     "size": "about 3 GB", "fits": "Any computer with 8 GB of memory. Quick, for short jobs."},
    {"id": "gemma-4-e4b", "label": "Balanced", "name": "Gemma 4 E4B", "maker": "Google", "repo": "ggml-org/gemma-4-E4B-it-GGUF", "quant": "Q4_K_M",
     "size": "about 5 GB", "fits": "16 GB of memory, or a graphics card with 6 GB. Good at writing."},
    {"id": "gpt-oss-20b", "label": "Strong", "name": "gpt-oss 20B", "maker": "OpenAI", "repo": "ggml-org/gpt-oss-20b-GGUF", "quant": "mxfp4",
     "size": "about 12 GB", "fits": "A graphics card with 16 GB (or 32 GB of memory, slowly). Reasons well, good at code."},
    {"id": "gemma-4-26b", "label": "Large", "name": "Gemma 4 26B", "maker": "Google", "repo": "ggml-org/gemma-4-26B-A4B-it-GGUF", "quant": "Q4_0",
     "size": "about 15 GB", "fits": "A graphics card with 16 GB or more. The best answers here."},
]

DEFAULTS = {"enabled": False, "provider": "", "models": {}, "local": {"model": "gemma-4-e4b", "gpu": True},
            "azure": {"endpoint": ""}, "custom": {"url": ""}, "where": {s: True for s in SURFACES}, "kept": {}}

# ------------------------------------------------------------------------------------------- what it's asked to do
SYSTEM = ("You are Huginn AI, the assistant built into Huginn OS. Be accurate, plain and brief. Use the language the "
          "person writes in. When asked for a piece of text or code, give only that, with no preface and no closing remarks.")
STYLES = {"clearer": "clearer and easier to read", "shorter": "shorter, keeping everything that matters", "friendlier": "warmer and friendlier",
          "formal": "more formal and professional", "simpler": "simpler, for anyone to understand", "longer": "fuller, with a little more detail"}
TASKS = {
    "ask": "{text}",
    "rewrite": "Rewrite the text below so it is {style}. Keep its meaning, its language, and every name and number. "
               "Reply with only the rewritten text.\n\n{text}",
    "proofread": "Correct the spelling, grammar and punctuation of the text below. Change nothing else. Reply with only the "
                 "corrected text.\n\n{text}",
    "summarise": "Summarise the text below in a few short sentences, or in short points if it lists several things. Reply "
                 "with only the summary.\n\n{text}",
    "continue": "Continue the text below by one paragraph in the same voice and language. Reply with only the new "
                "paragraph.\n\n{text}",
    "reply": "Draft a reply to the email below{intent}. Write only the body of the reply, in the email's language, with a "
             "greeting and no signature.\n\n{text}",
    "improve": "Improve the email draft below: clearer, friendly, correct. Keep its meaning and language. Reply with only "
               "the improved draft.\n\n{text}",
    "explain-code": "Explain what this {lang} code does, briefly, for someone reading it for the first time.\n\n{text}",
    "fix-code": "This {lang} code has a problem{problem}. Reply with only the corrected code: no explanation, no code fences."
                "\n\n{text}",
    "write-code": "Write {lang} code that does this: {text}\nReply with only the code: no explanation, no code fences.",
    "edit-code": "Change this {lang} code as asked: {ask}\nReply with only the new code: no explanation, no code fences.\n\n{text}",
}
TITLES = {"ask": "Answer", "rewrite": "Rewritten", "proofread": "Proofread", "summarise": "Summary", "continue": "Continued",
          "reply": "Reply", "improve": "Improved", "explain-code": "What it does", "fix-code": "Fixed", "write-code": "Written",
          "edit-code": "Changed"}


def prompt(task: str, text: str, extra: dict) -> str:
    style = STYLES.get(extra.get("style", ""), STYLES["clearer"])
    intent = f", saying {extra['intent'].strip()}" if extra.get("intent", "").strip() else ""
    problem = f" ({extra['problem'].strip()})" if extra.get("problem", "").strip() else ""
    return TASKS.get(task, TASKS["ask"]).format(text=text.strip()[:60000], style=style, intent=intent, problem=problem,
                                                lang=extra.get("lang") or "the", ask=extra.get("ask", ""))


def strip_fences(text: str) -> str:
    """Models sometimes put code in ``` fences even when told not to."""
    m = re.match(r"^\s*```[\w+#.-]*\n(.*?)\n```\s*$", text, re.S)
    return m.group(1) if m else text


# ------------------------------------------------------------------------------------------- settings and keys
def _save_json(path: Path, data: dict, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(part, path)


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(cfg.get(k), dict) and isinstance(v, dict):
                cfg[k].update(v)
            elif k in cfg:
                cfg[k] = v
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    _save_json(CONFIG, cfg)


def _vault():
    """The Passwords vault, if it's there and open (or opens without asking, from another app's unlock)."""
    try:
        import huginn_vault as hv
        v = hv.VaultFile(hv.vault_path())
        if not v.exists():
            return None
        if v.locked() and not hv.Session(v).try_unlock():
            return None
        return v
    except Exception:                                             # noqa: BLE001  (no vault: the private file)
        return None


def all_keys(cfg: dict = None) -> dict:
    """Every key, read at once: {provider: {"key", "where", "locked"}}. "locked": it's in Passwords, which is locked."""
    cfg = cfg or load_config()
    kept = cfg.get("kept") or {}
    try:
        in_file = json.loads(KEYS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        in_file = {}
    v = _vault() if "Passwords" in kept.values() else None
    out = {}
    for prov in PROVIDERS:
        got = v.secret("ai", prov) if v is not None else None
        if got:
            out[prov] = {"key": str(got), "where": "Passwords", "locked": False}
        elif in_file.get(prov):
            out[prov] = {"key": str(in_file[prov]), "where": "a private file", "locked": False}
        elif kept.get(prov) == "Passwords":
            out[prov] = {"key": "", "where": "Passwords", "locked": v is None}
    return out


def get_key(provider: str, cfg: dict = None) -> str:
    got = all_keys(cfg).get(provider) or {}
    if got.get("locked"):
        raise Failed(f"Your {PROVIDERS[provider]['label']} key is in Passwords, which is locked. Unlock Passwords, then try again.")
    return got.get("key", "")


def set_key(provider: str, key: str) -> str:
    """Keep a key (or forget it, with ""): in Passwords if it's set up and open, else in the private file. Returns
    where, and notes it in the settings (only where, never the key) so a locked Passwords can be told apart."""
    key = key.strip()
    try:
        keys = json.loads(KEYS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        keys = {}
    v = _vault()
    where = ""
    if v is not None:
        try:
            v.set_secret("ai", provider, key or None)
            where = "Passwords" if key else ""
            keys.pop(provider, None)
        except Exception:                                         # noqa: BLE001
            v = None
    if v is None:
        if key:
            keys[provider] = key
            where = "a private file"
        else:
            keys.pop(provider, None)
    _save_json(KEYS, keys, private=True)
    cfg = load_config()
    cfg.setdefault("kept", {})
    if where:
        cfg["kept"][provider] = where
    else:
        cfg["kept"].pop(provider, None)
    save_config(cfg)
    return where


# ------------------------------------------------------------------------------------------- speaking to them
class Failed(Exception):
    pass


def _endpoint(provider: str, cfg: dict) -> tuple:
    """(base URL, headers) for a provider."""
    p = PROVIDERS[provider]
    if provider == "local":
        st = local_server(cfg, start=True)
        return f"http://127.0.0.1:{st['port']}/v1", {"Authorization": f"Bearer {st['token']}"}
    base = p["base"]
    if provider == "azure":
        base = (cfg.get("azure", {}).get("endpoint") or "").rstrip("/")
        if not base:
            raise Failed("Add your Azure OpenAI resource's address first.")
        if not base.endswith("/openai/v1"):
            base = base.split("/openai")[0] + "/openai/v1"
    if provider == "custom":
        base = (cfg.get("custom", {}).get("url") or "").rstrip("/")
        if not base:
            raise Failed("Add the service's address first.")
    key = get_key(provider, cfg)
    if p["key"] and not key:
        raise Failed(f"Add your {p['label']} key in Settings › AI.")
    headers = {}
    if key:
        if p["kind"] == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        elif p.get("header"):
            headers = {p["header"]: key}
        else:
            headers = {"Authorization": f"Bearer {key}"}
    if provider == "openrouter":
        headers.update({"X-Title": "Huginn OS"})
    if provider == "github":
        headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    return base, headers


def _open(url: str, body: dict | None, headers: dict, timeout: float = 120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "Huginn-OS", **headers})
    try:
        return urllib.request.urlopen(req, timeout=timeout)                 # noqa: S310  (https, or this computer)
    except urllib.error.HTTPError as err:
        try:
            detail = json.loads(err.read().decode("utf-8", "replace"))
            msg = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else detail.get("error") or detail.get("message")
        except (ValueError, AttributeError):
            msg = ""
        why = {401: "The key wasn't accepted", 403: "The key isn't allowed to do that", 404: "That model or address wasn't found",
               429: "Too many requests, or the account is out of credit", 400: "The service didn't understand the request"}.get(err.code, f"The service answered {err.code}")
        raise Failed(why + (f": {str(msg)[:200]}" if msg else ".")) from None
    except (urllib.error.URLError, socket.timeout, ConnectionError) as err:
        raise Failed(f"Couldn't reach it ({getattr(err, 'reason', err)}).") from None


def sse(resp):
    """Server-sent events: (event, data) pairs."""
    event, data = "", []
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, "\n".join(data)


def chat(provider: str, model: str, messages: list, on_text, stopped=lambda: False, cfg: dict = None, max_tokens: int = 2048) -> str:
    """Ask, handing each piece of the answer to on_text as it comes. Returns the whole answer."""
    cfg = cfg or load_config()
    if provider not in PROVIDERS:
        raise Failed("Choose where Huginn AI runs in Settings › AI.")
    base, headers = _endpoint(provider, cfg)
    kind = PROVIDERS[provider]["kind"]
    out = []
    if provider == "local":
        touch_used()
    if kind == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body = {"model": model, "max_tokens": max_tokens, "stream": True, "system": system,
                "messages": [m for m in messages if m["role"] != "system"]}
        with _open(f"{base}/messages", body, headers) as resp:
            for event, data in sse(resp):
                if stopped():
                    break
                try:
                    d = json.loads(data)
                except ValueError:
                    continue
                if d.get("type") == "content_block_delta" and (d.get("delta") or {}).get("type") == "text_delta":
                    piece = d["delta"].get("text", "")
                    out.append(piece)
                    on_text(piece)
                elif d.get("type") == "error" or event == "error":
                    raise Failed((d.get("error") or {}).get("message") or "The service stopped with an error.")
    else:
        body = {"model": model, "messages": messages, "stream": True}
        if provider == "local":                                     # the services' own limits are fine (and some of
            body["max_tokens"] = max_tokens                         # their models refuse max_tokens)
        with _open(f"{base}/chat/completions", body, headers, timeout=600 if provider == "local" else 120) as resp:
            for _event, data in sse(resp):
                if stopped():
                    break
                if data.strip() == "[DONE]":
                    break
                try:
                    d = json.loads(data)
                except ValueError:
                    continue
                if d.get("error"):
                    err = d["error"]
                    raise Failed(err.get("message") if isinstance(err, dict) else str(err))
                for choice in d.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if piece:
                        out.append(piece)
                        on_text(piece)
    if provider == "local":
        touch_used()
    return "".join(out)


def list_models(provider: str, cfg: dict = None) -> list:
    """The models a provider offers this key: [{id, name}], likeliest first."""
    cfg = cfg or load_config()
    p = PROVIDERS[provider]
    if provider == "local":
        return [{"id": m["id"], "name": m["name"]} for m in LOCAL_MODELS if local_file(m["id"])]
    base, headers = _endpoint(provider, cfg)
    url = p.get("models_at") or f"{base}/models"
    with _open(url, None, headers, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    rows = data.get("data") if isinstance(data, dict) else data
    if isinstance(data, dict) and "models" in data and not rows:
        rows = data["models"]
    out = []
    for r in rows or []:
        ident = (r.get("id") or r.get("name") or "") if isinstance(r, dict) else str(r)
        ident = ident.removeprefix("models/")
        if not ident or any(s in ident.lower() for s in p.get("skip", []) + ["embed"]):
            continue
        if isinstance(r, dict) and isinstance(r.get("supported_output_modalities"), list) and "text" not in r["supported_output_modalities"]:
            continue                                                # GitHub's catalogue: not a model that writes
        out.append({"id": ident, "name": (r.get("display_name") or r.get("friendly_name") or r.get("name") or ident) if isinstance(r, dict) else ident})
    return rank_models(out, p.get("prefer", []))


def rank_models(rows: list, prefs: list) -> list:
    """The likeliest model first: the kind each service suits best, then the newest, then the plain name over a dated one."""
    def key(m):
        low = m["id"].lower()
        hit = next((i for i, w in enumerate(prefs) if w in low), len(prefs))
        odd = any(w in low for w in ("preview", "-exp", "lite", "nano", "latest", "audio", "realtime", "search", "codex", "thinking"))
        bare = re.sub(r"(19|20)\d\d[-_]?\d\d[-_]?\d\d|\d{4,}", "", low)             # dates and snapshots aren't versions
        ver = [int(n) for n in re.findall(r"\d+", bare)][:2] + [0, 0]
        return (hit, odd, -ver[0], -ver[1], len(low))
    return sorted(rows, key=key)


# ------------------------------------------------------------------------------------------- the model on this computer
def local_entry(ident: str) -> dict:
    return next((m for m in LOCAL_MODELS if m["id"] == ident), {})


def local_file(ident: str) -> str:
    """The model's file, once it's all here."""
    folder = MODELS_DIR / ident
    done = folder / "ready.json"
    try:
        files = json.loads(done.read_text(encoding="utf-8")).get("files", [])
        first = folder / files[0]
        return str(first) if all((folder / f).is_file() for f in files) else ""
    except (OSError, ValueError, IndexError, AttributeError):
        return ""


def memory() -> tuple:
    """(graphics card memory, system memory) in GB: the card's from the AMD or Intel driver, or nvidia-smi."""
    vram = 0.0
    for f in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            vram = max(vram, int(f.read_text()) / 1e9)
        except (OSError, ValueError):
            pass
    if not vram and shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
            vram = max([int(x) / 1024 for x in out.split() if x.isdigit()] or [0])
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        ram = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1)) / 1e6
    except (OSError, AttributeError):
        ram = 8.0
    return vram, ram


def suggested_model() -> str:
    vram, ram = memory()
    if vram >= 15 or (not vram and ram >= 48):
        return "gpt-oss-20b"
    if vram >= 6 or ram >= 15:
        return "gemma-4-e4b"
    return "gemma-4-e2b"


def have_llama() -> str:
    return shutil.which("llama-server") or ""


def hf_files(repo: str, quant: str) -> list:
    """[(path, size)] of a model's GGUF file(s) at that quantisation (a big one comes in parts)."""
    try:
        with _open(f"{HF}/api/models/{repo}/tree/main?recursive=true", None, {}, timeout=30) as resp:
            tree = json.loads(resp.read().decode("utf-8"))
    except Failed as err:
        raise Failed(str(err).replace("Couldn't reach it", "Couldn't reach Hugging Face", 1)) from None
    want = re.compile(r"[-_.]" + re.escape(quant.lower()) + r"(-\d{5}-of-\d{5})?\.gguf$")
    files = [(t["path"], int(t.get("size") or (t.get("lfs") or {}).get("size") or 0)) for t in tree
             if t.get("type") == "file" and want.search(t["path"].lower()) and "ud-" not in t["path"].lower()
             and not re.search(r"mmproj|mtp|dflash|draft", t["path"], re.I)]
    if not files:
        raise Failed(f"{repo} has no {quant} file any more.")
    return sorted(files)


def download_local(ident: str, progress, stopped=lambda: False) -> str:
    """Fetch a model (it carries on where it left off if stopped). progress(done_bytes, total_bytes)."""
    m = local_entry(ident)
    if not m:
        raise Failed("Unknown model.")
    folder = MODELS_DIR / ident
    folder.mkdir(parents=True, exist_ok=True)
    files = hf_files(m["repo"], m["quant"])
    total = sum(s for _, s in files) or 1
    have = sum((folder / Path(p).name).stat().st_size for p, _ in files if (folder / Path(p).name).exists()) + \
        sum((folder / f"{Path(p).name}.part").stat().st_size for p, _ in files if (folder / f"{Path(p).name}.part").exists())
    free = shutil.disk_usage(folder).free
    if free < total - have + 1e9:
        raise Failed(f"Not enough room: it needs {(total - have) / 1e9 + 1:.0f} GB free, and there's {free / 1e9:.0f} GB.")
    done_before = 0
    for path, size in files:
        name = Path(path).name
        target, part = folder / name, folder / f"{name}.part"
        if target.is_file() and (not size or target.stat().st_size == size):
            done_before += size
            progress(done_before, total)
            continue
        have = part.stat().st_size if part.exists() else 0
        url = f"{HF}/{m['repo']}/resolve/main/{urllib.parse.quote(path)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Huginn-OS", **({"Range": f"bytes={have}-"} if have else {})})
        try:
            resp = urllib.request.urlopen(req, timeout=60)               # noqa: S310
        except (urllib.error.URLError, socket.timeout) as err:
            raise Failed(f"Couldn't fetch the model ({getattr(err, 'reason', err)}).") from None
        if have and resp.status != 206:                                  # no resuming: start the part again
            have = 0
        with resp, open(part, "ab" if have else "wb") as fh:
            got = have
            while True:
                if stopped():
                    raise Failed("Stopped. It carries on from here next time.")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                progress(done_before + got, total)
        if size and part.stat().st_size != size:
            raise Failed("The download was cut short. Try again: it carries on from where it got to.")
        os.replace(part, target)
        done_before += size
    _save_json(folder / "ready.json", {"files": [Path(p).name for p, _ in files], "repo": m["repo"], "quant": m["quant"]})
    return local_file(ident)


def remove_local(ident: str) -> None:
    stop_local()
    shutil.rmtree(MODELS_DIR / ident, ignore_errors=True)


def touch_used() -> None:
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        USED.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _alive(st: dict) -> bool:
    try:
        os.kill(int(st.get("pid", 0)), 0)
    except (OSError, ValueError):
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{st['port']}/health", timeout=2) as r:   # noqa: S310
            return r.status == 200
    except (urllib.error.URLError, OSError, KeyError):
        return False


def local_server(cfg: dict, start: bool = True) -> dict:
    """The running local model ({port, token, model, pid}), started (by `serve`, for every app at once) if asked."""
    ident = (cfg.get("local") or {}).get("model") or "gemma-4-e4b"
    try:
        st = json.loads(SERVER_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if st.get("model") == ident and st.get("gpu") == bool(cfg["local"].get("gpu", True)) and _alive(st):
        return st
    if not start:
        return {}
    import fcntl
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with open(RUNTIME / "ai-server.lock", "w") as lock:              # two apps asking at once start it once
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            st = json.loads(SERVER_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        if st.get("model") == ident and st.get("gpu") == bool(cfg["local"].get("gpu", True)) and _alive(st):
            return st
        return _start_local(cfg, ident)


def _start_local(cfg: dict, ident: str) -> dict:
    if not have_llama():
        raise Failed("The local model's engine (llama.cpp) isn't installed. Settings › AI puts it in.")
    if not local_file(ident):
        raise Failed(f"{local_entry(ident).get('name', 'The model')} isn't downloaded yet. Settings › AI fetches it.")
    stop_local()
    SERVER_STATE.unlink(missing_ok=True)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve", ident, "gpu" if cfg["local"].get("gpu", True) else "cpu"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    end = time.time() + 240                                           # a big model takes a while to load
    while time.time() < end:
        time.sleep(0.5)
        try:
            st = json.loads(SERVER_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if st.get("failed"):
            raise Failed(st["failed"])
        if st.get("model") == ident and _alive(st):
            return st
    raise Failed("The local model took too long to start.")


def stop_local() -> None:
    try:
        st = json.loads(SERVER_STATE.read_text(encoding="utf-8"))
        os.kill(int(st.get("supervisor", 0)), signal.SIGTERM)
    except (OSError, ValueError):
        pass


def serve(ident: str, gpu: bool) -> int:
    """Run llama-server for this sign-in session: on this computer only, with a token, until it's been unused for a
    quarter of an hour (or told to stop)."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    path = local_file(ident)
    if not path:
        _save_json(SERVER_STATE, {"failed": "The model isn't downloaded."})
        return 1
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = secrets.token_urlsafe(24)
    argv = [have_llama(), "-m", path, "--host", "127.0.0.1", "--port", str(port), "--api-key", token, "--alias", ident,
            "-c", "16384", "--jinja", "--no-webui", "-ngl", "all" if gpu else "0"]
    log = open(RUNTIME / "ai-server.log", "w", encoding="utf-8")       # noqa: SIM115
    proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    _save_json(SERVER_STATE, {"port": port, "token": token, "model": ident, "gpu": gpu, "pid": proc.pid, "supervisor": os.getpid()}, private=True)
    touch_used()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set() and proc.poll() is None:
        stop.wait(20)
        try:
            idle = time.time() - float(USED.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            idle = 0
        if idle > IDLE_STOP:
            break
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    elif proc.returncode:
        tail = (RUNTIME / "ai-server.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        _save_json(SERVER_STATE, {"failed": "The local model stopped: " + (tail[0][:160] if tail else f"code {proc.returncode}")})
        return 1
    try:
        st = json.loads(SERVER_STATE.read_text(encoding="utf-8"))
        if st.get("supervisor") == os.getpid():
            SERVER_STATE.unlink()
    except (OSError, ValueError):
        pass
    return 0


def install_engine() -> str:
    """llama.cpp from Ubuntu (it's in the image; this is for a system without it), through the system's password prompt."""
    pkgs = ["llama.cpp-tools", "libggml0-backend-vulkan"]
    argv = (["pkgcli", "install", "-y"] if shutil.which("pkgcli") else ["pkexec", "apt-get", "install", "-y"]) + pkgs
    done = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()
        raise Failed("llama.cpp wasn't installed" + (f" ({tail[-1][:120]})" if tail else "") + ".")
    return have_llama()


# ------------------------------------------------------------------------------------------- OpenRouter's sign-in
def openrouter_signin(open_url, timeout: float = 300) -> str:
    """Sign in to OpenRouter in the browser and get a key for Huginn (their OAuth with PKCE): a one-off page on this
    computer receives the answer. Returns the key."""
    import http.server
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    got = {}

    class Back(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                             # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = (q.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<html><body style='font-family:sans-serif;background:#15181c;color:#eee;text-align:center;padding-top:20vh'>"
                             "<h2>Huginn AI is connected to OpenRouter.</h2><p>You can close this tab.</p></body></html>".encode())

        def log_message(self, *_):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Back)
    srv.timeout = 1
    port = srv.server_address[1]
    open_url("https://openrouter.ai/auth?" + urllib.parse.urlencode({"callback_url": f"http://localhost:{port}/huginn",
                                                                     "code_challenge": challenge, "code_challenge_method": "S256"}))
    end = time.time() + timeout
    while not got.get("code") and time.time() < end:
        srv.handle_request()
    srv.server_close()
    if not got.get("code"):
        raise Failed("Signing in to OpenRouter didn't finish.")
    with _open("https://openrouter.ai/api/v1/auth/keys", {"code": got["code"], "code_verifier": verifier, "code_challenge_method": "S256"}, {}, 30) as resp:
        key = json.loads(resp.read().decode("utf-8")).get("key", "")
    if not key:
        raise Failed("OpenRouter didn't give a key.")
    return key


# ------------------------------------------------------------------------------------------- for the apps (Qt)
def _qt():
    from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QUrl, Signal, Slot
    from PySide6.QtGui import QDesktopServices

    class AI(QObject):
        """Huginn AI for QML: `AI.ask(task, text, extra)` streams the answer through chunk(id, text) and done(id, error)."""
        changed = Signal()
        chunk = Signal(int, str)
        done = Signal(int, str)
        said = Signal(str, bool)
        _back = Signal(str, object)

        def __init__(self, demo: bool = False, surface: str = ""):
            super().__init__()
            self._demo, self._surface = demo, surface
            self._cfg = load_config()
            self._next, self._stop = 0, set()
            self._models, self._loading = {}, set()
            self._download = {}                                      # {id, done, total, error}
            self._busy = {}
            self._keys = None                                        # read when first wanted
            self._suggest = None
            self._back.connect(self._take)
            self._watch = QFileSystemWatcher(self)
            try:
                CONFIG.parent.mkdir(parents=True, exist_ok=True)
                self._watch.addPath(str(CONFIG.parent))
                self._watch.directoryChanged.connect(self._reload)
            except OSError:
                pass

        def _reload(self, *_):
            cfg = load_config()
            if cfg != self._cfg:
                if cfg.get("kept") != self._cfg.get("kept"):
                    self._keys = None
                self._cfg = cfg
                self.changed.emit()

        def _save(self):
            if not self._demo:
                self._cfg["kept"] = load_config().get("kept", {})       # only set_key changes where keys are
                save_config(self._cfg)
            self.changed.emit()

        def _take(self, what: str, data):
            if what == "chunk":
                self.chunk.emit(*data)
            elif what == "done":
                self._busy.pop(data[0], None)
                self.done.emit(*data)
            elif what == "models":
                prov, rows, err = data
                self._loading.discard(prov)
                self._models[prov] = rows
                if rows and not self._cfg["models"].get(prov):
                    self._cfg["models"][prov] = rows[0]["id"]
                    self._save()
                if err:
                    self.said.emit(err, True)
                self.changed.emit()
            elif what == "download":
                self._download = data
                self.changed.emit()
            elif what == "said":
                self.said.emit(*data)
                self.changed.emit()
            elif what == "key":
                prov, key = data
                where = set_key(prov, key)
                self._cfg = load_config()
                self._keys = None
                self.said.emit(f"Connected to {PROVIDERS[prov]['label']}. The key is kept in {where}.", False)
                self.loadModels(prov)
                self.changed.emit()

        # ---- what Settings and the apps show
        def _keyinfo(self, prov: str) -> dict:
            if self._keys is None:
                self._keys = {} if self._demo else all_keys(self._cfg)
            return self._keys.get(prov) or {}

        @Slot()
        def refresh(self):
            """Read the keys again (Passwords may have been unlocked) and the settings."""
            self._keys = None
            self._cfg = load_config()
            self.changed.emit()

        def _state(self) -> dict:
            c = self._cfg
            prov = c.get("provider", "")
            keyed = prov in PROVIDERS and (not PROVIDERS[prov]["key"] or bool(self._keyinfo(prov).get("key")))
            ready = bool(c.get("enabled")) and prov in PROVIDERS and (
                (prov == "local" and bool(local_file(c["local"].get("model", ""))) and bool(have_llama())) or (prov != "local" and keyed))
            return {"enabled": bool(c.get("enabled")), "provider": prov, "ready": ready or (self._demo and bool(c.get("enabled"))),
                    "label": PROVIDERS.get(prov, {}).get("label", ""), "model": self._model(),
                    "where": c.get("where", {}), "local": c.get("local", {}), "azure": c.get("azure", {}), "custom": c.get("custom", {}),
                    "engine": bool(have_llama()) or self._demo, "download": self._download}
        state = Property("QVariantMap", lambda self: self._state(), notify=changed)

        @Property("QVariantList", notify=changed)
        def providers(self):
            out = []
            for pid, p in PROVIDERS.items():
                if pid == "local":
                    continue
                k = self._keyinfo(pid)
                key = k.get("key", "")
                address = (self._cfg.get(pid) or {}).get("endpoint" if pid == "azure" else "url", "") if pid in ("azure", "custom") else ""
                out.append({"id": pid, "label": p["label"], "maker": p.get("maker", ""), "about": p["about"], "needsKey": p["key"],
                            "signin": bool(p.get("signin")), "keysAt": p.get("keys_at", ""), "address": address,
                            "connected": (bool(key) or k.get("locked", False) or not p["key"]) and (pid not in ("azure", "custom") or bool(address)),
                            "locked": bool(k.get("locked")), "keyEnds": ("…" + key[-4:]) if len(key) > 8 else "", "where": k.get("where", ""),
                            "models": self._models.get(pid, []), "loading": pid in self._loading, "model": self._cfg["models"].get(pid, ""),
                            "typed": pid in ("azure", "custom")})
            return out

        @Property("QVariantList", notify=changed)
        def localModels(self):
            current = self._cfg["local"].get("model")
            if self._suggest is None:
                self._suggest = suggested_model()
            return [dict(m, here=bool(local_file(m["id"])) or (self._demo and m["id"] == "gemma-4-e4b"), current=m["id"] == current,
                         suggested=m["id"] == self._suggest) for m in LOCAL_MODELS]

        def _model(self) -> str:
            prov = self._cfg.get("provider", "")
            if prov == "local":
                return local_entry(self._cfg["local"].get("model", "")).get("name", "")
            return self._cfg["models"].get(prov, "")

        @Slot(str, result=bool)
        def available(self, surface: str) -> bool:
            """Should this app show its AI actions? (Turned on, somewhere to run, and not turned off for this app.)"""
            st = self._state()
            return st["enabled"] and st["provider"] != "" and st["where"].get(surface, True) is not False

        # ---- choosing
        @Slot(bool)
        def setEnabled(self, on: bool):
            self._cfg["enabled"] = bool(on)
            self._save()

        @Slot(str)
        def setProvider(self, prov: str):
            if prov in PROVIDERS:
                self._cfg["provider"] = prov
                self._save()
                if prov != "local" and (self._keyinfo(prov).get("key") or not PROVIDERS[prov]["key"]) and not self._models.get(prov):
                    self.loadModels(prov)

        @Slot(str, bool)
        def setWhere(self, surface: str, on: bool):
            self._cfg.setdefault("where", {})[surface] = bool(on)
            self._save()

        @Slot(str, str)
        def setModel(self, prov: str, model: str):
            self._cfg["models"][prov] = model
            self._save()

        @Slot(str)
        def setLocal(self, ident: str):
            if local_entry(ident):
                self._cfg["local"]["model"] = ident
                self._save()

        @Slot(bool)
        def setGpu(self, on: bool):
            self._cfg["local"]["gpu"] = bool(on)
            self._save()

        @Slot(str, str)
        def setAddress(self, prov: str, url: str):
            if prov in ("azure", "custom"):
                self._cfg[prov]["endpoint" if prov == "azure" else "url"] = url.strip()
                self._save()
                if url.strip():
                    self.loadModels(prov)

        @Slot(str, str)
        def setKey(self, prov: str, key: str):
            if prov not in PROVIDERS or self._demo:
                return
            if not key.strip():
                set_key(prov, "")
                self._cfg = load_config()
                self._keys = None
                self._models.pop(prov, None)
                self.said.emit(f"{PROVIDERS[prov]['label']}'s key is forgotten.", False)
                self.changed.emit()
                return
            self._back.emit("key", (prov, key.strip()))

        @Slot(str)
        def keysPage(self, prov: str):
            url = PROVIDERS.get(prov, {}).get("keys_at")
            if url:
                QDesktopServices.openUrl(QUrl(url))

        @Slot(str)
        def loadModels(self, prov: str):
            if prov not in PROVIDERS or self._demo:
                return
            self._loading.add(prov)
            self.changed.emit()
            cfg = json.loads(json.dumps(self._cfg))

            def work():
                try:
                    self._back.emit("models", (prov, list_models(prov, cfg), ""))
                except Failed as err:
                    self._back.emit("models", (prov, [], str(err)))
                except Exception as err:                             # noqa: BLE001
                    self._back.emit("models", (prov, [], f"Couldn't list the models ({err})."))
            threading.Thread(target=work, daemon=True).start()

        @Slot()
        def signIn(self):
            """OpenRouter: sign in in the browser, and its key comes back to Huginn."""
            def work():
                try:
                    key = openrouter_signin(lambda url: QDesktopServices.openUrl(QUrl(url)))
                    self._back.emit("key", ("openrouter", key))
                except Failed as err:
                    self._back.emit("said", (str(err), True))
            threading.Thread(target=work, daemon=True).start()

        # ---- the model on this computer
        @Slot(str)
        def download(self, ident: str):
            if self._download.get("id") and not self._download.get("error") and not self._download.get("finished"):
                return
            if self._demo:
                return
            self._stop.discard("download")
            self._download = {"id": ident, "done": 0, "total": 0}
            self.changed.emit()

            def work():
                try:
                    if not have_llama():
                        self._back.emit("download", {"id": ident, "done": 0, "total": 0, "step": "Installing llama.cpp…"})
                        install_engine()
                    download_local(ident, lambda d, t: self._back.emit("download", {"id": ident, "done": d, "total": t}),
                                   lambda: "download" in self._stop)
                    self._back.emit("download", {"id": ident, "done": 1, "total": 1, "finished": True})
                    self._back.emit("said", (f"{local_entry(ident)['name']} is ready. It runs here: nothing you ask leaves the computer.", False))
                except Failed as err:
                    self._back.emit("download", {"id": ident, "error": str(err)})
                except Exception as err:                             # noqa: BLE001
                    self._back.emit("download", {"id": ident, "error": f"The download failed ({err})."})
            threading.Thread(target=work, daemon=True).start()

        @Slot(str)
        def fetch(self, ident: str):
            """Choose a model for this computer and download it (one call: the list it's in changes under it)."""
            self.setLocal(ident)
            self.download(ident)

        @Slot()
        def stopDownload(self):
            self._stop.add("download")

        @Slot(str)
        def remove(self, ident: str):
            if not self._demo:
                remove_local(ident)
            self.changed.emit()

        # ---- asking
        @Slot(str, str, "QVariant", result=int)
        def ask(self, task: str, text: str, extra) -> int:
            """Start a job: chunk(id, piece) as the answer comes, then done(id, "" or why it failed)."""
            extra = dict(extra or {}) if not hasattr(extra, "toVariant") else dict(extra.toVariant() or {})
            self._next += 1
            ident = self._next
            cfg = json.loads(json.dumps(self._cfg))
            prov = cfg.get("provider", "")
            history = list(extra.get("history") or [])

            def work():
                try:
                    if self._demo:
                        for word in "This is what Huginn AI would answer here, a few words at a time.".split(" "):
                            time.sleep(0.05)
                            self._back.emit("chunk", (ident, word + " "))
                        self._back.emit("done", (ident, ""))
                        return
                    if not cfg.get("enabled"):
                        raise Failed("Huginn AI is off. Turn it on in Settings › AI.")
                    model = cfg["local"].get("model") if prov == "local" else cfg["models"].get(prov, "")
                    if prov != "local" and not model:
                        rows = list_models(prov, cfg)
                        if not rows:
                            raise Failed("No model to use there yet: pick one in Settings › AI.")
                        model = rows[0]["id"]
                    msgs = [{"role": "system", "content": SYSTEM}] + [m for m in history if m.get("role") in ("user", "assistant")]
                    msgs.append({"role": "user", "content": prompt(task, text, extra)})
                    chat(prov, model, msgs, lambda piece: self._back.emit("chunk", (ident, piece)), lambda: ident in self._stop, cfg)
                    self._back.emit("done", (ident, ""))
                except Failed as err:
                    self._back.emit("done", (ident, str(err)))
                except Exception as err:                             # noqa: BLE001
                    self._back.emit("done", (ident, f"Something went wrong ({err})."))
            self._busy[ident] = task
            threading.Thread(target=work, daemon=True).start()
            return ident

        @Slot(int)
        def stop(self, ident: int):
            self._stop.add(ident)

        @Slot(str, result=str)
        def title(self, task: str) -> str:
            return TITLES.get(task, "Answer")

        @Slot(str, result=str)
        def clean(self, text: str) -> str:
            return strip_fences(text)

    return AI


AI = None


def make(demo: bool = False, surface: str = ""):
    global AI
    if AI is None:
        AI = _qt()
    return AI(demo, surface)


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"] and len(sys.argv) >= 3:
        sys.exit(serve(sys.argv[2], (sys.argv[3:4] or ["gpu"])[0] != "cpu"))
    print(__doc__)
