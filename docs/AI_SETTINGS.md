# AI settings

- Model: deepseek · deepseek-flash, with a second provider on timeout or 429. One model for every AI feature.
- Whose key pays: Your key (you bill the customer).
- Called from: Your server, keys in .env.
- Keys live only in .env on the server.
- AI budget per customer: RM5.00 a month.

## What each customer’s account controls
- A monthly AI budget per customer, with an alert at 80%
- AI usage and cost per customer on a dashboard
- Change the model or provider in settings, not in code
- A person reviews AI replies before they go out

## AI features and their models
- User Authentication & Tenant Management (act with tools): deepseek-flash, about 25 uses per customer a month
- Quantitative Performance Analytics Engine (act with tools): deepseek-flash, about 25 uses per customer a month
- Rule-Based Behavioral Mistake Detector (act with tools): deepseek-flash, about 25 uses per customer a month
- AI Trading Diagnosis & Recovery Report (summarise): deepseek-flash, about 25 uses per customer a month
- Interactive Performance Dashboard (act with tools): deepseek-flash, about 25 uses per customer a month
