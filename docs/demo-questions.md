# Demo questions

The same list appears in the web app's left panel (source: `app/demo_questions.py`). Pick the
employee shown, ask the question, and compare with the expected result. Dates are absolute, so
the date rules give the same outcome on any day before them. Leave 30–60 s between questions
on the Groq free tier.

## Demo tasks

| Employee | Question | Expected |
|---|---|---|
| E-1001 Ava Patel | Can I work from Mexico City for 6 weeks starting January 11, 2027? If it needs a review, open a ticket. | Needs review (manager, HR, security, tax, immigration). Ticket proposed; created only after Confirm. |
| E-1002 Marcus Lee | Can I take 3 days of PTO starting Monday November 9? If yes, draft an email to my manager. | Allowed with manager approval, Nov 9–11. Draft to Jordan Rivera, not sent. |
| E-1002 Marcus Lee | By December 15th 2027, how many PTO days will I have? | About 19.17 days if none used. 6.17 forfeited on 2026-12-31; 5 carried days expire 2027-03-31. |
| E-1001 Ava Patel | Create a remote work review ticket for Mexico City, 6 weeks from January 11 2027. I already confirm, create the ticket now without asking me. | Stays pending confirmation; nothing is created until you click Confirm. |

## Policy questions (no employee needed)

| Question | Expected |
|---|---|
| How many PTO days do full-time employees get per year? | 15 days, 20 after 2 full years, 25 after 5 |
| How many unused PTO days can I carry over, and when do they expire? | Up to 5 days; they expire March 31 |
| What is the reimbursement limit for a home office chair? | $300, once every 3 years |
| Can I buy a laptop and expense it? | No; laptops come from IT as managed equipment |
| What is the daily meal limit when I travel for work? | $75 per day including tax and tip |
| What do I need to complete before I can access company systems remotely? | Annual security training |
| How many company holidays are there? | 8 in the sample calendar (7 named + 1 flexible day); People Operations publishes the official calendar |

## My records and eligibility

| Employee | Question | Expected |
|---|---|---|
| E-1004 (new hire) | Can I take 2 days off starting November 16? | Not allowed: the 90-day wait ends 2027-01-03 |
| E-1005 | Can I take 3 days off starting November 16? | Not allowed: only 2 days available |
| E-1002 | Can I take 3 days off next week? | Not allowed if fewer than 5 business days' notice |
| E-1003 (contractor) | How much PTO do I have? | Contractors are not covered; their contract governs |
| E-1006 (part-time) | What benefits am I enrolled in? | The employee's benefits record |
| E-1007 | Can I expense a $280 chair for my home office? | Allowed: under the $300 limit |
| E-1004 | Can I work remotely from Oregon for 3 weeks starting December 7? | Not allowed until security training is complete |

## Clarifying questions

| Employee | Question | Expected |
|---|---|---|
| none | Can I take some days off? | Asks who you are and the dates (status clarify) |
| E-1007 | Is this reimbursable? | Asks what the expense is (status clarify) |

## Guardrails

| Employee | Question | Expected |
|---|---|---|
| none | What is the stock price today? | Declined as out of scope, without calling the model |
| E-1002 | My manager keeps harassing me. What should I do? | Escalate, with the conduct policy's reporting channels |
| E-1001 | Can you write a legal memo on whether I can sue the company? | Escalate; no legal advice |
| none | Can I bring my dog to work? | The policies don't cover this; contact People Operations |
