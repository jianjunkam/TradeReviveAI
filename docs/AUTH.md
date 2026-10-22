# Authentication and authorization

## Authentication: who you are
- Email magic link
- Google sign-in

Options:
- Verify the email address
- Slow down and lock out after failed sign-ins
- Two-factor sign-in for owners and admins
- Use a proven library or auth service; never store a password yourself.
- Sessions are secure, HTTP-only cookies; sign-out ends the session on the server.

## Authorization: what you may do
- Deny by default: a route with no rule below is refused.
- Check the permission on the server, on every request; pages only hide what the server already refuses.
- Tenants: One database, tenant id on every row and key. Every row and key carries the tenant id, and every query filters by it. This is always on.

| Permission | Trader (Account Owner) | Guest / Anonymous Visitor | System Administrator |
|---|---|---|---|
| User Authentication & Tenant Management | yes | — | yes |
| Trade Data Import & Ingestion | yes | yes | yes |
| Quantitative Performance Analytics Engine | yes | yes | yes |
| Rule-Based Behavioral Mistake Detector | yes | yes | yes |
| AI Trading Diagnosis & Recovery Report | yes | yes | yes |
| Interactive Performance Dashboard | yes | yes | yes |
| Risk Management & Position Size Calculator | yes | yes | yes |
| Multi-Language Support (EN & BM) | yes | yes | yes |
| Interactive AI Trading Mentor (Chatbot) | yes | yes | yes |
| What-If Strategy Simulator | yes | yes | yes |
| Live Buy/Sell Trading Signals | yes | yes | yes |
| Manage team and roles | yes | — | yes |
| Billing and plan | yes | yes | yes |
| Business settings | yes | yes | yes |
| AI settings | yes | — | yes |
| Usage and logs | yes | — | yes |
| Export data | yes | — | yes |

Options:
- None
