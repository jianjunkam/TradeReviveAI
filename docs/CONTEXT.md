# Context

What the model sees on a call is all it knows. Each call is built in this order, stable parts first so the provider can cache them:

1. Role and rules (docs/PROMPT_CONTRACT.md)
2. Knowledge: None
3. Memory: Structured state + last 2 turns
4. The request

## Sources
- None.

## Memory
- Code keeps the facts as fields (amounts, dates, choices), updated after each turn, plus the last 2 turns.

## Caching
- No caching.

## Budget per call (estimate)
| AI feature | Input tokens | Of which knowledge | Output tokens | Calls per use | Model window |
|---|---|---|---|---|---|
| User Authentication & Tenant Management | 720 | 0 | 200 | 1 | 1,000,000 |
| Quantitative Performance Analytics Engine | 750 | 0 | 200 | 1 | 1,000,000 |
| Rule-Based Behavioral Mistake Detector | 720 | 0 | 200 | 1 | 1,000,000 |
| AI Trading Diagnosis & Recovery Report | 1,070 | 0 | 250 | 1 | 1,000,000 |
| Interactive Performance Dashboard | 705 | 0 | 200 | 1 | 1,000,000 |
