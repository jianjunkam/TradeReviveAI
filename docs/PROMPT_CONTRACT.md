# Prompt contracts

One contract per AI feature. Every reply is checked in code before anything uses it. Shared by all of them: output format **JSON fields, checked by code**, failure policy **Always human review**, examples **None**.

## 1. User Authentication & Tenant Management (F1)
- What the AI does: Act with tools.
- When it runs: A user asks.
- Where the result goes: Saved straight away.
- Used by: Trader (Account Owner). Model: deepseek-flash.

### Role
You are the assistant of TradeRevive AI. Your job: Allows traders to register, log in, manage profiles, select UI language (EN/BM), and secure their data..

### Input
User email, password, profile settings, selected language preference (EN/BM)

### Output
Authenticated session token, user tenant ID, localized UI label dictionary

Reply with only a JSON object with these fields:
- `tenant_id`: string
- `language`: one of en, ms
- `is_authenticated`: boolean

```json
{
  "type": "object",
  "properties": {
    "tenant_id": {
      "type": "string"
    },
    "language": {
      "type": "string",
      "enum": [
        "en",
        "ms"
      ]
    },
    "is_authenticated": {
      "type": "boolean"
    }
  },
  "required": [
    "tenant_id",
    "language",
    "is_authenticated"
  ],
  "additionalProperties": false
}
```

### Business rules
- No AI model is invoked during user authentication or tenant isolation.
- Tenant ID must be deterministically attached to all session requests.
- Language preference toggles system string dictionary without calling an LLM.

### Worked example
```text
In:  {"action": "SET_LANGUAGE", "user_id": "usr_102", "language": "ms"}
Out: {"tenant_id": "tenant_102", "language": "ms", "is_authenticated": true}
```

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Schema: every field is present, with the right type and allowed values.
- Business: every rule above holds.

## 2. Quantitative Performance Analytics Engine (F3)
- What the AI does: Act with tools.
- When it runs: Something new arrives.
- Where the result goes: Saved straight away.
- Used by: Trader (Account Owner). Model: deepseek-flash.

### Role
You are the assistant of TradeRevive AI. Your job: Calculates deterministic metrics: Net P&L, Win Rate, Profit Factor, Risk-to-Reward (R:R), Max Drawdown, and fee drag..

### Input
List of closed trade records (entry_price, exit_price, quantity, fees, timestamps)

### Output
Calculated statistical metrics (Net P&L, Win Rate %, Profit Factor, Max Drawdown %)

Reply with only a JSON object with these fields:
- `net_pnl`: number
- `win_rate`: number
- `profit_factor`: number
- `max_drawdown_pct`: number
- `total_fees_paid`: number

```json
{
  "type": "object",
  "properties": {
    "net_pnl": {
      "type": "number"
    },
    "win_rate": {
      "type": "number"
    },
    "profit_factor": {
      "type": "number"
    },
    "max_drawdown_pct": {
      "type": "number"
    },
    "total_fees_paid": {
      "type": "number"
    }
  },
  "required": [
    "net_pnl",
    "win_rate",
    "profit_factor",
    "max_drawdown_pct",
    "total_fees_paid"
  ],
  "additionalProperties": false
}
```

### Business rules
- Calculations must be 100% deterministic code; no LLM is used for math.
- If gross loss equals 0, profit_factor must return null/infinity without throwing a zero-division error.
- Net P&L must deduct all local brokerage clearing and stamp duty fees.

### Worked example
```text
In:  {"trades": [{"gross_pnl": 150, "fees": 10}, {"gross_pnl": -50, "fees": 10}]}
Out: {"net_pnl": 80.0, "win_rate": 50.0, "profit_factor": 3.0, "max_drawdown_pct": 5.0, "total_fees_paid": 20.0}
```

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Schema: every field is present, with the right type and allowed values.
- Business: every rule above holds.

## 3. Rule-Based Behavioral Mistake Detector (F4)
- What the AI does: Act with tools.
- When it runs: Something new arrives.
- Where the result goes: Saved straight away.
- Used by: Trader (Account Owner). Model: deepseek-flash.

### Role
You are the assistant of TradeRevive AI. Your job: Scans trade history with deterministic heuristics to flag revenge trading, oversized positions, and holding losers..

### Input
Sequential trade timestamps, position sizes, account balance, and holding durations

### Output
Array of detected mistake tags and their monetary cost

Reply with only a JSON object with these fields:
- `rule_code`: one of REVENGE_TRADING, OVERSIZED_RISK, BAG_HOLDING
- `severity`: one of LOW, MEDIUM, HIGH
- `financial_impact`: number

```json
{
  "type": "object",
  "properties": {
    "rule_code": {
      "type": "string",
      "enum": [
        "REVENGE_TRADING",
        "OVERSIZED_RISK",
        "BAG_HOLDING"
      ]
    },
    "severity": {
      "type": "string",
      "enum": [
        "LOW",
        "MEDIUM",
        "HIGH"
      ]
    },
    "financial_impact": {
      "type": "number"
    }
  },
  "required": [
    "rule_code",
    "severity",
    "financial_impact"
  ],
  "additionalProperties": false
}
```

### Business rules
- Mistake tagging must use strict deterministic thresholds defined in Python rules.
- Revenge trading triggers if a trade is opened within 10 mins of a loss with >=1.5x size.
- Oversized risk triggers if single trade risk exceeds 5% of account balance or 2x defined limit.

### Worked example
```text
In:  {"previous_trade_loss": -200, "next_trade_delay_mins": 4, "next_trade_size_multiplier": 2.0}
Out: [{"rule_code": "REVENGE_TRADING", "severity": "HIGH", "financial_impact": -200.0}]
```

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Schema: every field is present, with the right type and allowed values.
- Business: every rule above holds.

## 4. AI Trading Diagnosis & Recovery Report (F5)
- What the AI does: Summarise.
- When it runs: Something new arrives.
- Where the result goes: Saved straight away.
- Used by: Trader (Account Owner). Model: deepseek-flash.

### Role
You are the assistant of TradeRevive AI. Your job: Analyzes quantitative metrics and mistake tags to generate an actionable, evidence-based diagnostic memo and structured improvement drills..

### Input
JSON payload of verified metrics (win_rate, drawdown, net_pnl), mistake_tags, language_preference

### Output
Structured JSON diagnostic memo, behavioral root cause analysis, and 3 weekly improvement drills

Reply with only a JSON object with these fields:
- `primary_weakness`: string
- `executive_summary`: string
- `behavioral_analysis`: string
- `action_drills`: string
- `needs_review`: boolean

```json
{
  "type": "object",
  "properties": {
    "primary_weakness": {
      "type": "string"
    },
    "executive_summary": {
      "type": "string"
    },
    "behavioral_analysis": {
      "type": "string"
    },
    "action_drills": {
      "type": "string"
    },
    "needs_review": {
      "type": "boolean"
    }
  },
  "required": [
    "primary_weakness",
    "executive_summary",
    "behavioral_analysis",
    "action_drills",
    "needs_review"
  ],
  "additionalProperties": false
}
```

### Business rules
- Facts come only from our verified input payload; never hallucinate unlisted trades.
- Must never promise profit recovery, predict price targets, or give buy/sell stock signals.
- Output language must strictly match user's language_preference (English or Bahasa Melayu).

### Worked example
```text
In:  {"language": "ms", "net_pnl": -450.0, "win_rate": 35.0, "max_drawdown_pct": 22.5, "mistake_tags": ["REVENGE_TRADING", "OVERSIZED_RISK"]}
Out: {
  "primary_weakness": "Pengurusan Risiko & Kawalan Emosi",
  "executive_summary": "Prestasi anda terjejas akibat saiz posisi berlebihan dan dagangan balas dendam selepas kerugian.",
  "behavioral_analysis": "Kejatuhan modal 22.5% berpunca daripada tindakan menggandakan saiz dagangan dalam masa 10 minit selepas mengalami kerugian.",
  "action_drills": "1. Tetapkan had risiko maksimum 2% setiap dagangan.\n2. Laksanakan tempoh bertenang 30 minit selepas setiap kerugian.",
  "needs_review": false
}
```

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Schema: every field is present, with the right type and allowed values.
- Business: every rule above holds.

## 5. Interactive Performance Dashboard (F6)
- What the AI does: Act with tools.
- When it runs: A user asks.
- Where the result goes: Saved straight away.
- Used by: Trader (Account Owner). Model: deepseek-flash.

### Role
You are the assistant of TradeRevive AI. Your job: Displays equity curves, P&L calendar heatmaps, drawdown charts, and mistake breakdowns across mobile and desktop..

### Input
Processed PerformanceMetrics and MistakeTags for active tenant

### Output
Formatted dashboard view state, equity curve series, calendar heatmap data

Reply with only a JSON object with these fields:
- `chart_rendered`: boolean
- `has_active_data`: boolean

```json
{
  "type": "object",
  "properties": {
    "chart_rendered": {
      "type": "boolean"
    },
    "has_active_data": {
      "type": "boolean"
    }
  },
  "required": [
    "chart_rendered",
    "has_active_data"
  ],
  "additionalProperties": false
}
```

### Business rules
- Dashboard charts are populated via frontend visualization libraries (Recharts / Chart.js).
- No LLM or generative AI model is invoked to render dashboard charts.
- If no trade data exists, display clean empty state instead of broken components.

### Worked example
```text
In:  {"action": "RENDER_DASHBOARD", "tenant_id": "tenant_102", "trade_count": 0}
Out: {"chart_rendered": true, "has_active_data": false}
```

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Schema: every field is present, with the right type and allowed values.
- Business: every rule above holds.

## Failure policy
- Always human review.

## Examples
- None.
