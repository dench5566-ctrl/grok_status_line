#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grok Build status line — port of dench5566-ctrl/claude-code-statusline.

Line 1: model, effort, cwd, git branch, live context, session output, cost,
duration, week allowance as "week: 68% (03 okt)" plus a bar of what is left.
Line 2: context bar, session tokens, cache hit, auto-compact, turn timer.

The allowance is not in the status JSON. It comes from the same credits
request the usage window uses, cached for a minute.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

# Label language: "en" or "ru".
LOCALE = "ru"

LABELS = {
    "en": {
        "hour": "h", "min": "m", "sec": "s", "day": "d",
        "ctx": "ctx", "in": "in", "out": "out", "cache": "cache",
        "compact": "compact", "turn": "turn",
        "no_ctx": "ctx: no data yet (arrives with the first response)",
    },
    "ru": {
        "hour": "\u0447", "min": "\u043c", "sec": "\u0441", "day": "\u0434",
        "ctx": "ctx", "in": "in", "out": "out", "cache": "cache",
        "compact": "compact", "turn": "turn",
        "no_ctx": "\u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 (\u043f\u043e\u044f\u0432\u044f\u0442\u0441\u044f \u043f\u043e\u0441\u043b\u0435 \u043f\u0435\u0440\u0432\u043e\u0433\u043e \u043e\u0442\u0432\u0435\u0442\u0430)",
    },
}
PERIOD_WORD = {
    "USAGE_PERIOD_TYPE_WEEKLY": "week",
    "USAGE_PERIOD_TYPE_MONTHLY": "month",
    "USAGE_PERIOD_TYPE_DAILY": "day",
}
MONTHS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
)
BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
BILLING_CACHE = os.path.expanduser("~/.grok/statusline-billing.json")
BILLING_TTL = 60
L = LABELS.get(LOCALE, LABELS["en"])

R = "\033[0m"


def c(code, s):
    return "\033[38;5;%dm%s%s" % (code, s, R)


GREY = 245
DIM = 249
BLUE = 32
TEAL = 37
PURPLE = 97
ORANGE = 172
RED = 160
INK = 240


def load():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def num(n):
    n = int(n or 0)
    for div, suf in ((1_000_000, "M"), (1_000, "k")):
        if n >= div:
            v = n / float(div)
            return ("%d%s" if v >= 100 or v == int(v) else "%.1f%s") % (v, suf)
    return str(n)


def heat(used_pct):
    """Color by pressure (how much has been spent), not by remaining fill."""
    if used_pct >= 90:
        return RED
    if used_pct >= 70:
        return ORANGE
    if used_pct >= 40:
        return TEAL
    return BLUE


def bar(remaining_pct, used_pct, width=10):
    remaining_pct = max(0.0, min(100.0, float(remaining_pct)))
    filled = int(round(remaining_pct / 100.0 * width))
    return c(heat(used_pct), "▰" * filled) + c(DIM, "▱" * (width - filled))


def dur_label(ms):
    if not ms:
        return None
    ms = int(ms)
    if ms >= 60000:
        return "%d%s" % (ms / 60000, L["min"])
    return "%d%s" % (max(ms / 1000, 1), L["sec"])


def parse_iso(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def read_billing_cache():
    try:
        with open(BILLING_CACHE, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("used") is None:
        return None
    return data


def write_billing_cache(data):
    try:
        tmp = BILLING_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, BILLING_CACHE)
    except Exception:
        pass


def billing_token():
    path = os.path.expanduser("~/.grok/auth.json")
    try:
        with open(path, encoding="utf-8") as handle:
            auth = json.load(handle)
    except Exception:
        return None
    if not isinstance(auth, dict):
        return None
    now = datetime.now(timezone.utc)
    for entry in auth.values():
        if not isinstance(entry, dict):
            continue
        token = entry.get("key")
        if not token:
            continue
        exp = parse_iso(entry.get("expires_at"))
        if exp is not None and exp <= now:
            continue
        return token
    return None


def fetch_billing():
    token = billing_token()
    if not token:
        return None
    req = urllib.request.Request(
        BILLING_URL,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "x-grok-client-identifier": "grok-shell",
        },
    )
    with urllib.request.urlopen(req, timeout=2.5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    cfg = body.get("config") if isinstance(body, dict) else None
    if not isinstance(cfg, dict):
        return None
    used = cfg.get("creditUsagePercent")
    if used is None:
        return None
    period = cfg.get("currentPeriod") if isinstance(cfg.get("currentPeriod"), dict) else {}
    return {
        "used": float(used),
        "period": period.get("type") or "",
        "end": period.get("end") or cfg.get("billingPeriodEnd") or "",
        "fetched_at": time.time(),
    }


def billing_info(trigger):
    cached = read_billing_cache()
    age = None
    if cached is not None:
        try:
            age = time.time() - float(cached.get("fetched_at") or 0)
        except Exception:
            age = None
    if age is not None and age < BILLING_TTL:
        return cached
    # A busy turn re-runs this script on every state change. Refresh the
    # network only from the timer, or once when there is nothing cached.
    if trigger == "state" and cached is not None:
        return cached
    fetched = None
    try:
        fetched = fetch_billing()
    except Exception:
        fetched = None
    if fetched:
        write_billing_cache(fetched)
        return fetched
    return cached


def until_label(end):
    moment = parse_iso(end)
    if moment is None:
        return None
    local = moment.astimezone()
    return "%02d %s" % (local.day, MONTHS[local.month - 1])


def limit_seg(info):
    """Remaining allowance. Filled blocks are what is left."""
    if not info or info.get("used") is None:
        return None
    try:
        used = max(0.0, min(100.0, float(info.get("used"))))
    except Exception:
        return None
    left = max(0.0, 100.0 - used)
    word = PERIOD_WORD.get(info.get("period") or "", "limit")
    text = "%s: %d%%" % (word, round(left))
    when = until_label(info.get("end"))
    if when:
        text += " (%s)" % when
    return c(heat(used), text) + " " + bar(left, used)


def branch(cwd):
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=0.4,
        )
        if out.returncode != 0:
            return None
        name = out.stdout.strip()
        if not name:
            return None
        dirty = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=0.4,
        )
        return name + ("*" if dirty.stdout.strip() else "")
    except Exception:
        return None


def main():
    d = load()
    cwd = (d.get("workspace") or {}).get("current_dir") or d.get("cwd") or os.getcwd()
    ctx = d.get("context_window") or {}
    usage = ctx.get("session_usage") or {}
    cost_d = d.get("cost") or {}

    # Grok live window is context_tokens; Claude ports used total_input_tokens.
    # Payload percentages are "how full" (spent). Display is remaining: 100% → 0%.
    used = ctx.get("context_tokens")
    if used is None:
        used = ctx.get("total_input_tokens") or 0
    size = ctx.get("context_window_size") or 0
    used_pct = None
    left_pct = None
    left = 0
    if size:
        if ctx.get("used_percentage") is not None:
            used_pct = float(ctx.get("used_percentage"))
        else:
            used_pct = used * 100.0 / size
        if ctx.get("remaining_percentage") is not None:
            left_pct = float(ctx.get("remaining_percentage"))
        else:
            left_pct = max(0.0, 100.0 - used_pct)
        left = max(int(size) - int(used), 0)

    out_tok = ctx.get("session_output_tokens")
    if out_tok is None:
        out_tok = ctx.get("total_output_tokens") or 0
    in_tok = ctx.get("session_input_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0

    # ---------- line 1 ----------
    row = []

    model = (d.get("model") or {}).get("display_name") or "?"
    eff = (d.get("effort") or {}).get("level")
    tag = model + ("·" + eff if eff else "")
    row.append(c(PURPLE, "◆ " + tag))

    home = os.path.expanduser("~")
    short = "~" + cwd[len(home):] if cwd.startswith(home) else cwd
    short = os.path.basename(short.rstrip("/")) or short
    wt = (d.get("worktree") or {}).get("name") or (d.get("workspace") or {}).get("git_worktree")
    if wt:
        short = short + "@" + wt
    br = (d.get("workspace") or {}).get("branch")
    git_br = branch(cwd)
    if git_br:
        br = git_br
    elif br:
        br = str(br)
    row.append(c(BLUE, short) + (c(GREY, " (" + br + ")") if br else ""))

    if size and left_pct is not None:
        row.append(
            c(GREY, L["ctx"] + " ")
            + c(heat(used_pct), "%s/%s" % (num(left), num(size)))
            + c(heat(used_pct), " %d%%" % round(left_pct))
        )
    if out_tok:
        row.append(c(GREY, L["out"] + " " + num(out_tok)))

    cost = cost_d.get("total_cost_usd")
    if cost:
        row.append(c(INK, "$%.2f" % cost))

    label = dur_label(cost_d.get("total_duration_ms"))
    if label:
        row.append(c(GREY, label))

    limit = limit_seg(billing_info(d.get("trigger")))
    if limit:
        row.append(limit)

    lines = [c(DIM, " │ ").join(row)]

    # ---------- line 2: context pressure + session stats ----------
    seg = []
    if left_pct is not None:
        seg.append(
            c(GREY, L["ctx"] + " ")
            + bar(left_pct, used_pct)
            + c(heat(used_pct), " %d%%" % round(left_pct))
        )
    if in_tok:
        seg.append(c(GREY, L["in"] + " " + num(in_tok)))
    if in_tok and cache_read:
        hit = cache_read * 100.0 / in_tok
        seg.append(c(GREY, L["cache"] + " %d%%" % round(hit)))
    compact = ctx.get("auto_compact_threshold_percent")
    if compact is not None:
        compact = float(compact)
        near = used_pct is not None and used_pct >= compact
        seg.append(
            c(ORANGE if near else GREY, L["compact"] + " %d%%" % round(compact))
        )
    started = (d.get("turn") or {}).get("started_at_ms")
    if started:
        elapsed = int(time.time() * 1000) - int(started)
        if elapsed > 0:
            tlabel = dur_label(elapsed)
            if tlabel:
                seg.append(c(TEAL, L["turn"] + " " + tlabel))

    if seg:
        lines.append(c(DIM, "  ").join(seg))
    else:
        lines.append(c(DIM, L["no_ctx"]))

    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
