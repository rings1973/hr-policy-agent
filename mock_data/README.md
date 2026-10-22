# Mock structured data

All files here are **synthetic**. They describe no real person; emails use the reserved `example.com` domain.
They are exposed to the agent only through MCP tools in `hr_mcp/` (never read directly by the agent).

| File | Contents | Used by tools |
|---|---|---|
| `employees.json` | 8 employee profiles (type, hire date, home state/country, manager, remote eligibility, training) | `lookup_employee_profile`, `check_policy_compliance` |
| `managers.json` | 3 managers referenced by `manager_id` | `lookup_employee_profile`, `draft_hr_email` |
| `pto_balances.json` | PTO entitlement, used, pending, available | `check_pto_balance`, `check_policy_compliance` |
| `benefits.json` | Benefits status and elections | `lookup_benefits_status` |
| `tickets.json` | Seed HR tickets; new mock tickets are held in memory only | `create_mock_hr_ticket` |

Deliberate edge cases for testing workflows:
- **E-1003 Sofia Romero**: contractor, so not remote-eligible, no PTO, and no benefits.
- **E-1004 Priya Nair**: new hire. Training is incomplete, PTO can't be used for 90 days, and benefits are pending with a 2026-12-01 deadline.
- **E-1005 Daniel Okafor**: low PTO balance (2 days) and handles restricted data.
- **E-1006 Mei Chen**: part-time, so PTO is prorated and there is no 401(k) match.
- **E-1008 Hannah Becker**: intern, no PTO or benefits.
