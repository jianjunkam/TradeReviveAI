# Requirements

Version 1: **The must-haves only**. The source of truth is `blueprint.json`; this file explains it.

## Roles
| Role | What they do |
|---|---|
| Trader (Account Owner) | Signs up, uploads CSV/trade files or logs manual trades, views performance metrics, runs AI diagnostics, reviews recovery plans, and manages subscription billing. |
| Guest / Anonymous Visitor | Lands on public marketing pages, views sample sanitized diagnostic reports, uses the free standalone Risk & Position Sizing Calculator without signing in. |
| System Administrator | Monitors platform health, manages broker CSV parser templates, views aggregate tenant statistics, and inspects failed AI diagnostic tasks or error logs. |

## Features
| Id | Feature | Priority | Used by | AI | What it does |
|---|---|---|---|---|---|
| F1 | User Authentication & Tenant Management | Must, version 1 | Trader (Account Owner) | yes | Allows traders to register, log in, manage profiles, select UI language (EN/BM), and secure their data. |
| F2 | Trade Data Import & Ingestion | Must, version 1 | Trader (Account Owner) |  | Upload broker CSV files or manually input trades with validation (ticker, side, entry/exit price, size, fees, dates). |
| F3 | Quantitative Performance Analytics Engine | Must, version 1 | Trader (Account Owner) | yes | Calculates deterministic metrics: Net P&L, Win Rate, Profit Factor, Risk-to-Reward (R:R), Max Drawdown, and fee drag. |
| F4 | Rule-Based Behavioral Mistake Detector | Must, version 1 | Trader (Account Owner) | yes | Scans trade history with deterministic heuristics to flag revenge trading, oversized positions, and holding losers. |
| F5 | AI Trading Diagnosis & Recovery Report | Must, version 1 | Trader (Account Owner) | yes | Analyzes quantitative metrics and mistake tags to generate an actionable, evidence-based diagnostic memo and structured improvement drills. |
| F6 | Interactive Performance Dashboard | Must, version 1 | Trader (Account Owner) | yes | Displays equity curves, P&L calendar heatmaps, drawdown charts, and mistake breakdowns across mobile and desktop. |
| F7 | Risk Management & Position Size Calculator | Should | Trader (Account Owner) | yes | Calculates exact unit sizing and monetary stop-loss risk based on account equity and risk percentage. |
| F8 | Multi-Language Support (EN & BM) | Should | Trader (Account Owner) | yes | Toggles all UI text, metric labels, and AI prompt outputs between English and Bahasa Melayu. |
| F9 | Interactive AI Trading Mentor (Chatbot) | Could | Trader (Account Owner) | yes | Interactive conversational coach for post-trade reflection and answering questions about past mistakes. |
| F10 | What-If Strategy Simulator | Could | Trader (Account Owner) | yes | Simulates revised equity curve if top 3 flagged behavioral mistakes were eliminated. |
| F11 | Direct Broker API Sync | Won’t | Trader (Account Owner) | yes | Automated real-time trade syncing directly from broker accounts (Moomoo, Interactive Brokers). |
| F12 | Live Buy/Sell Trading Signals | Should | System Administrator | yes | Generating direct automated trade entries or real-time signals. |

## Use cases (version 1)

### UC1 · User Authentication & Tenant Management (F1)
- Actor: Trader (Account Owner)
- Goal: Allow a retail trader to securely create an account, log in, manage multi-tenant profile settings, and toggle UI language preferences between English and Bahasa Melayu so their private trading data is isolated.

Main steps:
User navigates to the sign-up page and inputs email, password, and full name.
System verifies password requirements, generates a verification token, and establishes a secure tenant workspace.
User confirms their email and logs into the application.
User selects their default language preference (English or Bahasa Melayu) in account settings.
User logs out or securely refreshes session tokens upon subsequent visits.

Errors and edge cases:
- User attempts registration with an already registered email address.
- User inputs a password shorter than 8 characters or missing required security complexity.
- User submits expired or malformed session/JWT tokens.
- User attempts to access another user's tenant trade records directly via URL or API parameters.

Acceptance criteria (tests in `tests/acceptance/test_f1_user_authentication_tenant_management.py`):
- AC1.1 Given a new user provides an unused email and compliant password, when they submit the registration form, then the system creates a new user profile with a unique tenant_id and returns a 201 status with an email confirmation trigger.
- AC1.2 Given an existing registered user, when they attempt to register with the same email, then the system rejects the submission with a clear error message stating that the email is already in use.
- AC1.3 Given an authenticated user with active session, when they request data using another user's tenant_id, then the system blocks the request and returns a 403 Forbidden response.
- AC1.4 Given a logged-in user changes language preference to "Bahasa Melayu", when the dashboard reloads, then navigation headers and system labels update to Bahasa Melayu equivalents.

### UC2 · Trade Data Import & Ingestion (F2)
- Actor: Trader (Account Owner)
- Goal: Enable beginner traders to record trades either by submitting a quick 30-second manual log with emotion tags, uploading a trade screenshot, or importing historical broker CSV files.

Main steps:
User opens the "Log / Import Trades" interface on desktop or mobile.
User chooses an input method: Quick Form, Broker Screenshot upload, or CSV batch file.
User inputs/reviews trade details (ticker symbol, buy/sell action, quantity, entry/exit prices, fees, and emotional entry tag).
System validates price, date, and size numbers deterministically.
User clicks "Save Trade" or "Confirm Batch Import", and the trades are persisted under the user's account.

Errors and edge cases:
- CSV contains corrupted rows, blank mandatory columns, or letters inside numeric price fields.
- User uploads duplicate trades that already exist in their transaction journal.
- Screenshot image is blurry or unsupported in file format (non-PNG/JPEG).
- Exit timestamp occurs chronologically earlier than the entry timestamp.

Acceptance criteria (tests in `tests/acceptance/test_f2_trade_data_import_ingestion.py`):
- AC2.1 Given a trader enters a valid trade via the quick form (Symbol: "NVDA", Entry: 120, Exit: 126, Qty: 10, Emotion: "Breakout"), when they submit, then the trade record is created with Gross P&L calculated as +$60.00 and attached to their tenant_id.
- AC2.2 Given an uploaded broker CSV containing 20 valid rows and 2 rows with negative quantities, when import runs, then the system commits the 20 valid trades, skips the 2 faulty rows, and displays a row-level error banner.
- AC2.3 Given a trade record where the exit timestamp is earlier than the entry timestamp, when the form is submitted, then the system rejects the submission with "Exit date cannot precede entry date".
- AC2.4 Given an identical trade already exists (matching timestamp, symbol, action, quantity, price), when re-uploaded via CSV, then the system skips the duplicate row without throwing a fatal server error.

### UC3 · Quantitative Performance Analytics Engine (F3)
- Actor: Trader (Account Owner)
- Goal: Automatically compute exact, verifiable trading metrics (Net P&L, Win Rate, Profit Factor, Risk-to-Reward, Max Drawdown, and trading fee drag) across all closed trades without mathematical error.

Main steps:
User opens their trading portfolio summary or filters a specific date range.
System queries all closed trade records belonging to the user's tenant_id.
Engine calculates deterministic aggregate sums: Total Wins, Total Losses, Gross Profit, Gross Loss, and Brokerage Fees.
Engine derives Win Rate percentage, Profit Factor ratio, and computes historical high-water-mark equity drawdown.
Engine returns structured numeric analytics to the dashboard UI.

Errors and edge cases:
- User has zero closed trades (empty dataset).
- User has 100% winning trades (Gross Loss = 0, causing a division by zero in Profit Factor).
- Trades involve multiple currencies (e.g., USD and MYR) requiring separate account tracking.
- Brokerage fees exceed gross profits, flipping an ostensibly winning trade into a net loss.

Acceptance criteria (tests in `tests/acceptance/test_f3_quantitative_performance_analytics_engin.py`):
- AC3.1 Given a dataset of 10 closed trades containing 6 wins and 4 losses, when the metrics engine runs, then the reported Win Rate must equal exactly 60.0%.
- AC3.2 Given gross profits of $1,500 and gross losses of $500, when the engine calculates the Profit Factor, then the value must evaluate to exactly 3.00.
- AC3.3 Given a trading history where Gross Loss equals 0, when Profit Factor is calculated, then the system returns Infinity or N/A without throwing a zero-division runtime exception.
- AC3.4 Given an initial balance of $10,000 that drops to a trough of $7,500 before rising to $11,000, when Max Drawdown is calculated, then it records exactly 25.0%.

### UC4 · Rule-Based Behavioral Mistake Detector (F4)
- Actor: Trader (Account Owner)
- Goal: Scan trading logs against deterministic heuristics to systematically detect and tag recurring beginner pitfalls (revenge trading, oversized position risk, bag holding, and stop-loss moving).

Main steps:
System listens for new closed trade events or a user-initiated "Scan Mistakes" request.
Detection engine evaluates sequential trade timestamps, position sizes, and duration against predefined risk rules.
Engine flags trades matching destructive patterns and assigns normalized mistake tags (e.g., REVENGE_TRADING, OVERSIZED_RISK, BAG_HOLDING).
Engine calculates the cumulative monetary cost of each mistake category.
System presents flagged trades with explanatory indicators directly on the user's trade journal.

Errors and edge cases:
- Rapid scalping trades within seconds that trigger false-positive revenge trading flags.
- User changes account base balance, skewing percentage-based sizing calculations.
- Missing stop-loss price data in manual logs preventing theoretical R:R calculation.

Acceptance criteria (tests in `tests/acceptance/test_f4_rule_based_behavioral_mistake_detector.py`):
- AC4.1 Given a user closes a losing trade and opens a new trade in the same or correlated symbol within 10 minutes at $1.5\times$ or greater position size, when the detector runs, then the second trade is tagged with REVENGE_TRADING.
- AC4.2 Given an account with $5,000 balance and a 2% max-risk rule ($100), when a user takes a single trade loss exceeding $250, then the trade is automatically tagged with OVERSIZED_RISK.
- AC4.3 Given an open losing trade held for more than $3\times$ the user's average winning trade duration while passing predefined stop-loss levels, when closed, then it receives the BAG_HOLDING tag.
- AC4.4 Given a set of 5 trades flagged with REVENGE_TRADING summing to -$450 in net loss, when the mistake breakdown is viewed, then "Cost of Revenge Trading" displays -$450.

### UC5 · AI Trading Diagnosis & Recovery Report (F5)
- Actor: Trader (Account Owner)
- Goal: Ingest verified quantitative metrics and mistake tags into an LLM reasoning prompt to produce a constructive, jargon-free diagnostic memo and a weekly personalized recovery drill, without providing speculative financial advice or buy/sell signals.

Main steps:
(not written)

Errors and edge cases:
- LLM attempts to hallucinate stock price predictions or recommend specific tickers.
- LLM returns invalid or truncated JSON that fails schema validation.
- The user has fewer than 5 trades, providing insufficient data for a reliable diagnostic assessment.
- Model timeout or provider rate limit during generation.

Acceptance criteria (tests in `tests/acceptance/test_f5_ai_trading_diagnosis_recovery_report.py`):
- AC5.1 Given a verified metrics payload containing OVERSIZED_RISK and REVENGE_TRADING tags, when the AI report is triggered, then the generated output returns valid JSON containing primary_weakness, behavioral_analysis, and recovery_drills.
- AC5.2 Given the AI system prompt guardrails, when any report is produced, then the text contains zero ticker recommendations, zero target price forecasts, and includes an explicit financial coaching disclaimer.
- AC5.3 Given a user profile configured in Bahasa Melayu, when the report is requested, then the resulting diagnosis and action drills are returned completely in fluent Bahasa Melayu.
- AC5.4 Given the LLM provider fails or times out, when the user requests a report, then the system returns a graceful error message, does not deduct a user report credit, and allows retrying.

### UC6 · Interactive Performance Dashboard (F6)
- Actor: Trader (Account Owner)
- Goal: Provide a clear, mobile-responsive fintech dashboard that visualizes trading health, cumulative equity growth, calendar P&L heatmaps, and mistake impact so the user can quickly track behavioral progress.

Main steps:
User logs into the platform and lands on /dashboard.
System renders core performance metric cards (Net P&L, Win Rate, Profit Factor, Max Drawdown).
System renders the cumulative equity curve chart and cumulative fee drag line.
System displays a monthly calendar heatmap showing daily green/red P&L distribution.
User clicks on any mistake category to highlight the exact trades on the equity curve.

Errors and edge cases:
- Dashboard viewed on narrow mobile screens (under 375px width) causing chart clipping.
- Extremely large datasets (e.g., 2,000+ trades) causing browser rendering lag.
- A month with zero trades recorded displaying a broken or distorted calendar view.

Acceptance criteria (tests in `tests/acceptance/test_f6_interactive_performance_dashboard.py`):
- AC6.1 Given an active user with closed trade records, when navigating to /dashboard, then the Net P&L card, Win Rate card, and Equity Curve render within 1.5 seconds.
- AC6.2 Given a mobile screen viewport of 375px width, when the dashboard loads, then all metric cards stack vertically without horizontal overflow or clipped text.
- AC6.3 Given a user clicks on the "Revenge Trading" tag filter on the dashboard, when the chart updates, then data points corresponding to revenge trades are highlighted visually with red marker flags.
- AC6.4 Given a month with zero logged trades, when the calendar heatmap is displayed, then all day cells render in a neutral grey state without layout breakage.

## Integrations
- WhatsApp
- Email sending
- Google Sheets or Excel
- Accounting software

## Platforms
- A web app (works on phones too)
- A mobile app (iOS and Android)

## Out of scope for version 1
- Direct Broker API Sync
- Live broker OAuth API auto-synchronization
- Real-time streaming market tick data
- Direct automated trading bots or order execution
- Buy, sell, or direct financial advice/signals
- Multi-user social trading feed or public leaderboards
- Options contract Greeks and multi-leg derivatives analysis
- Native iOS and Android mobile app store builds
- Anything not listed above.

## Data
See docs/DATA_MODEL.md.
