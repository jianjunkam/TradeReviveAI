"""AI analysis of the journal: one model call over numbers the app already computed.

Design rules, from AGENTS.md and docs/AI_SETTINGS.md:

* The model never sees raw fills and never computes anything. It receives a small block of
  figures the journal produced and is told to use only those.
* It must not recommend buying or selling, predict prices, or promise outcomes — the product
  forbids that, and a coach that does it is worse than no coach.
* The key lives in .env on the server. The call is made server-side; the browser never sees
  a provider or a key.
* Every reply is labelled AI-generated in the UI, and it is checked by a human before use —
  which is why the journal's arithmetic section stays the source of truth.

Providers, in order: DeepSeek (a key), then Flowise (a chatflow id, no key). With neither,
the endpoint says so instead of inventing a paragraph.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

REQUEST_TIMEOUT = 30.0
CACHE_TTL = 600.0          # ten minutes: the numbers only change when a trade lands
MAX_TOKENS = 320

SYSTEM_PROMPT = (
    "You are a trading coach reviewing a retail trader's own journal. "
    "Use ONLY the figures provided. Never invent a number, a ticker or a date. "
    "Do not add, subtract or combine them: quote each figure exactly as written, because "
    "your arithmetic is not checked and a wrong total is worse than no total. "
    "Never recommend buying or selling any security, never predict prices, never promise or "
    "imply that losses will be recovered. No signals, no targets, no 'should buy'. "
    "Write at most 120 words in three short parts: what the numbers show, the single most "
    "expensive habit, and one concrete exercise for this week. Plain prose, no headings, no "
    "bullet lists. Finish with the sentence: Not financial advice."
)


@dataclass
class Analysis:
    available: bool
    text: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    cached: bool = False
    reason: str | None = None
    #: Dollar amounts the reply states that were never supplied — a model doing its own maths.
    unknown_figures: list[str] | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def build_prompt(summary: dict) -> str:
    """The model sees these lines and nothing else."""
    def money(value) -> str:
        return "n/a" if value is None else f"${value:,.2f}"

    habits = "\n".join(
        f"- {m['label']}: {m['count']} occurrence(s), costing {money(m['cost'])}"
        for m in summary.get("mistakes", [])
    )
    return f"""{SYSTEM_PROMPT}

The trader's figures (all simulated papertrading, not a real account):
- closed trades: {summary.get('closed_trades')}, of which won: {round((summary.get('win_rate') or 0) * summary.get('closed_trades', 0) / 100)}
- win rate: {summary.get('win_rate')}%
- profit factor: {summary.get('profit_factor')}
- average win: {money(summary.get('avg_win'))}, average loss: {money(summary.get('avg_loss'))}
- best trade: {money(summary.get('best'))}, worst trade: {money(summary.get('worst'))}
- net P&L: {money(summary.get('net_pl'))} — this is the total; do not add anything to it
- of which realised on closed trades: {money(summary.get('realised'))}
- of which unrealised on open positions: {money(summary.get('unrealised'))} (already included above)
- equity: {money(summary.get('equity'))} from a {money(summary.get('starting_cash'))} start
- max drawdown: {money(summary.get('max_drawdown'))} ({summary.get('max_drawdown_pct')}%)
- behaviour rules that fired:
{habits}

Write the review now."""


def allowed_amounts(summary: dict) -> set[float]:
    values = [
        summary.get(k)
        for k in ("avg_win", "avg_loss", "best", "worst", "net_pl", "realised",
                  "unrealised", "equity", "starting_cash", "max_drawdown")
    ]
    values += [m.get("cost") for m in summary.get("mistakes", [])]
    return {round(float(v), 2) for v in values if v is not None}


def unknown_figures(text: str, summary: dict) -> list[str]:
    """Dollar amounts in the reply that were not in the figures handed to the model."""
    import re

    allowed = allowed_amounts(summary)
    found = re.findall(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text)
    strays = []
    for raw in found:
        try:
            value = round(float(raw.replace(",", "")), 2)
        except ValueError:
            continue
        if value not in allowed:
            strays.append(f"${raw}")
    return sorted(set(strays))


_lock = threading.Lock()
_cache: dict[str, tuple[float, Analysis]] = {}


def _cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _call_deepseek(prompt: str, settings) -> tuple[str, str]:
    key = settings.deepseek_api_key
    if key is None or not key.get_secret_value():
        raise RuntimeError("no key")
    data = _post_json(
        f"{settings.ai_base_url.rstrip('/')}/chat/completions",
        {
            "model": settings.ai_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": MAX_TOKENS,
        },
        {"Authorization": f"Bearer {key.get_secret_value()}"},
    )
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("the model returned nothing")
    return text, settings.ai_model


def _call_flowise(prompt: str, settings) -> tuple[str, str]:
    if not settings.flowise_chatflow_id:
        raise RuntimeError("no chatflow")
    data = _post_json(
        f"https://{settings.flowise_host}/api/v1/prediction/{settings.flowise_chatflow_id}",
        {"question": prompt},
        {},
    )
    text = (data.get("text") or "").strip()
    if not text:
        raise RuntimeError("the chatflow returned nothing")
    return text, "flowise chatflow"


def analyse(summary: dict, settings) -> Analysis:
    """One call, cached. Returns unavailable with a reason rather than a fabricated review."""
    prompt = build_prompt(summary)
    key = _cache_key(prompt)

    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            cached = hit[1]
            return Analysis(**{**cached.as_dict(), "cached": True})

    providers = []
    if settings.deepseek_api_key is not None and settings.deepseek_api_key.get_secret_value():
        providers.append(("deepseek", _call_deepseek))
    if settings.flowise_chatflow_id:
        providers.append(("flowise", _call_flowise))

    if not providers:
        return Analysis(
            available=False,
            reason=(
                "No model is configured. Set DEEPSEEK_API_KEY (or FLOWISE_CHATFLOW_ID) in the "
                "server's .env and this section fills in."
            ),
        )

    errors: list[str] = []
    for name, caller in providers:
        started = time.monotonic()
        try:
            text, model = caller(prompt, settings)
        except urllib.error.HTTPError as exc:
            errors.append(f"{name}: HTTP {exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001 - any provider failure falls through
            errors.append(f"{name}: {exc}")
            continue

        result = Analysis(
            available=True,
            text=text,
            provider=name,
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            unknown_figures=unknown_figures(text, summary),
        )
        with _lock:
            _cache[key] = (time.time(), result)
        return result

    return Analysis(
        available=False,
        reason="The model could not be reached: " + "; ".join(errors),
    )
