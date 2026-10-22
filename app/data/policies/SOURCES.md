# Policy corpus sources

The corpus mixes **synthetic company policies** (authored for this project with AI assistance) and
**public-domain U.S. Government reference documents**. Ingestion skips this file (`SOURCES.md`).

| File | Format | Origin | License | Retrieved | Changes |
|---|---|---|---|---|---|
| `benefits_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | Eligibility rules for part-time/intern/401(k) added 2026-10-22 |
| `data_security_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | none |
| `equipment_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | none |
| `expense_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | Numeric reimbursement limits added 2026-10-22 |
| `holiday_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | none |
| `leave_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | none |
| `pto_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | Merged duplicated summary, added accrual/notice numbers 2026-10-22 |
| `remote_work_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | Resolved 2-week vs 30-day conflict, added tax/location section 2026-10-22 |
| `workplace_conduct_policy.md` | Markdown | Synthetic, AI-assisted | Project original | n/a | none |
| `onboarding_checklist.txt` | Plain text | Synthetic, AI-assisted | Project original | n/a | none |
| `nist_sp800_46r2_telework_security_excerpt.pdf` | PDF | NIST SP 800-46 Rev. 2, *Guide to Enterprise Telework, Remote Access, and BYOD Security* (Souppaya & Scarfone, 2016), https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-46r2.pdf | U.S. Government work, not subject to copyright in the U.S. (17 U.S.C. §105); NIST requests attribution | 2026-10-22 | Excerpted 10 of 53 pages (1, 3, 8–10, 21–22, 35–37); no text altered |
| `opm_annual_leave_fact_sheet.html` | HTML | U.S. Office of Personnel Management, *Fact Sheet: Annual Leave (General Information)*, https://www.opm.gov/policy-data-oversight/pay-leave/leave-administration/fact-sheets/annual-leave/ | U.S. Government work, public domain (17 U.S.C. §105) | 2026-10-22 | Kept main article content only; removed site navigation, scripts, and footer; added an "external reference" note |

**No endorsement:** Use of NIST and OPM material does not imply endorsement by NIST, OPM, or the U.S. Government.
The two government documents are tagged `source_type: external_reference`. They describe federal-sector rules,
and the assistant presents them as background, never as company policy.

Sources considered and **not used** because of their licenses: SANS policy templates (terms forbid
redistribution and AI use), SHRM sample policies (members only), the Basecamp employee handbook (no license),
and the Mattermost handbook (CC BY-NC-SA).
