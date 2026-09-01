# Apply-flow mock test cases (dev)

Captured 2026-08-31 from the `DEV TOOLS` panel on `www.dev.avant.com/apply` (`#autofill-dropdown`,
labelled "Select Mock Test Case"). Selecting a case shows its description; population then requires an
explicit click on **AUTOFILL WITH MOCK**. The panel also offers **AUTOFILL PERSONAL STAGE**, which
fills valid personal data without imposing a mock scenario.

These are *not* Confetti `basic.mock_scenarios` (those are keyed `default` / `high_fico` / `low_fico` /
`credit_freeze_soft`). Different mechanism, different catalogue.

| Case | Product | Description |
| --- | --- | --- |
| TST_0001 | - | Get an approved Credit Karma response |
| TST_0002 | Loan | Get an approved Loan |
| TST_0003 | Card | TU Level Four error 401 on soft report. Should decline |
| TST_0004 | Card | TU Level Four error 403 on soft report. Should decline |
| TST_0005 | Card | TU Level Four error 413 on soft report. Should decline |
| TST_0006 | Loan | Credit report name mismatch, soft report |
| TST_0007 | Loan | Credit report name mismatch, hard report |
| TST_0008 | Loan | Credit freeze |
| TST_0009 | Loan | Initial FCRA alert, soft + hard |
| TST_0010 | Loan | Extended FCRA alert, TU soft pull |
| TST_0011 | Card | Initial FCRA alert, soft report |
| TST_0012 | Card | Initial FCRA alert, hard report |
| TST_0013 | Card | Initial FCRA alert, soft + hard (combines 0011 and 0012) |
| TST_0014 | Card | Extended FCRA alert, soft + hard |
| TST_0015 | Loan | Fails Giact and OVT, too few bank transactions. Should decline |
| TST_0016 | Loan | Initial FCRA, soft TU report |
| TST_0017 | Loan | Initial FCRA both reports, clears one |
| TST_0018 | Loan | Extended FCRA both reports, clears one |
| TST_0019 | Loan | Credit freeze, TU hard report |
| TST_0020 | Card | Credit freeze, TU hard report |
| TST_0021 | - | Risky timezone from ThreatMetrix |
| TST_0022 | - | TU report with No Subject Found |
| TST_0023 | - | TU soft report throws on fetch |
| TST_0024 | - | Sanctions screening potential match, AlertState Open |
| TST_0025 | - | Sanctions screening potential match, AlertState Unassigned |
| TST_0026 | - | Cannot reach plaidypus |
| TST_0027 | - | Plaid Payroll happy path |
| TST_0028 | - | Customer refuses payroll income connection |
| TST_0029 | Loan | Approved Pagaya loan, `policy_path=pagaya_first_look` |
| TST_0030 | - | Plaidypus payroll payload, empty `account_id` |
| TST_0031 | - | Plaid OCR happy path |
| TST_0032 | - | Plaid CRA base happy path |
| TST_0033 | - | Plaid CRA failure path |
| TST_0034 | - | IP spoofing risk |
| TST_0035 | - | FCRA, soft and hard are different reports |
| TST_0036 | - | FCRA, soft and hard are same reports |
| TST_0037 | - | FCRA failure scenario |
| TST_0038 | - | TU primary report with Vantage3 fifth factor |
| TST_0039 | Loan | Extended FCRA alert, hard report |
| TST_0040 | Loan | Initial FCRA alert, hard report |
| TST_0041 | Loan | Factor Trust V3 report |
| TST_0042 | - | RD fraud risks, first response JSON null. Needs first_name `tst_0042_NNNNNNNNN`, Redis reset, `ENABLE_MOCK_SERVICES` |

## The gap that matters for this ticket

**There is no happy-path approved *Card* case.** Every case labelled `Card` (0003, 0004, 0005, 0011,
0012, 0013, 0014, 0020) is a decline or a risk scenario. The only clean approvals are `TST_0001`
(Credit Karma response) and `TST_0002` / `TST_0029` (loans).

Since these tickets need an **approved card** to produce a CMA, do not reach for a mock case by
default. Use **AUTOFILL PERSONAL STAGE** and let the standard dev TransUnion stub decide, which is the
happy path per FINDINGS #3. Keep `TST_0001` as the fallback if the default stub will not approve.
