# Oracle Period-Close Orchestration Agent

An agentic AI that drives the complete Oracle Fusion Cloud month-end and quarter-end close sequence — from subledger transfer verification through GL reconciliation, intercompany elimination, trial balance tie-out, variance analysis, and controller sign-off routing.

Built with Claude (Anthropic) and GPT-4o (OpenAI) using a model-agnostic factory pattern. The same codebase and tool definitions work for both providers.

Related project: [oracle-gl-reconciliation-agent](https://github.com/karthikchundi-commits/oracle-gl-reconciliation-agent) — focused GL reconciliation agent for resolving unbalanced journals.

---

## The Problem

Period-close in Oracle Fusion Cloud is a multi-step sequence that spans four subledgers, GL journal resolution, intercompany elimination, and trial balance verification — all before a controller can sign off. At multi-ledger, multi-entity scale, this process is manual, error-prone, and consumes days near quarter-end.

Standard automation (RPA, batch jobs) can run the steps but cannot reason about what to do when a subledger transfer is pending, an intercompany pair won't net, or a variance flag requires judgment rather than a fix. That reasoning gap is where agentic AI fits.

---

## Architecture

```
Oracle Fusion Cloud REST API
         │
         ▼
   Agent Tool Layer (9 tools)
   ┌──────────────────────────────────────┐
   │ get_period_close_status              │
   │ get_subledger_status                 │
   │ trigger_subledger_transfer           │
   │ get_unbalanced_journals              │
   │ detect_intercompany_imbalances       │
   │ get_trial_balance                    │
   │ run_variance_analysis                │
   │ generate_close_report                │
   │ request_controller_signoff           │
   └──────────────────────────────────────┘
         │
         ▼
   LLM Reasoning Layer
   (Claude tool_use / GPT-4o function_calling)
         │
         ▼
   Close Package (HTML report + email)
         │
         ▼
   Human Approval
   (GL Controller → Oracle period close)
```

The agent reasons about sequencing: it will not attempt a trial balance until all subledgers are confirmed closed and transferred. It will not generate the close report until the trial balance is balanced. It cannot close the GL period directly — that requires controller sign-off.

---

## Close Sequence

The agent executes this sequence, reasoning at each step:

1. **Period status** — GL period open? Unbalanced journal count?
2. **Subledger status** — AP (200), AR (222), FA (140), Projects (275): Closed and Transferred?
   - If transfer is Pending → triggers ESS job: `Transfer Journal Entries to GL`
3. **Journal resolution** — if unbalanced journals exist, classifies each:
   - FX rounding → notes, flags for corrective entry
   - Timing difference → `REQUIRES_INVESTIGATION`, no correction
   - Manual coding error → `PENDING_APPROVAL`, urgency HIGH
4. **Intercompany elimination** — nets initiator vs. recipient amounts; flags pairs that don't zero out
5. **Trial balance** — verifies total DR = total CR across all accounts
6. **Variance analysis** — flags accounts with > threshold% movement vs. prior period
7. **Close report** — HTML package with KPIs, subledger table, variance flags, open items
8. **Controller sign-off** — emails controller the close package

---

## Model-Agnostic Design

Tool definitions are written once and exported in both wire formats:

```python
# src/agents/tools.py
CLAUDE_TOOLS: list[dict] = [_to_claude_tool(t) for t in _ALL_TOOLS]   # input_schema format
OPENAI_TOOLS: list[dict] = [_to_openai_tool(t) for t in _ALL_TOOLS]   # function.parameters + strict=True
```

Provider selection is a single config value:

```python
agent = AgentFactory.create(provider='claude', fusion_client=client,
                            oracle_settings=oracle_cfg,
                            agent_settings=agent_cfg,
                            notification_settings=notif_cfg)
# or:
agent = AgentFactory.create(provider='openai', ...)
```

---

## Quick Start

### Without an Oracle Instance (recommended for evaluation)

```bash
git clone https://github.com/karthikchundi-commits/oracle-period-close-agent.git
cd oracle-period-close-agent
pip install -r requirements.txt

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...

python examples/run_period_close.py --dry-run --provider claude
python examples/run_period_close.py --dry-run --provider openai
```

The `MockFusionClient` simulates a realistic Q1-2025 close scenario:
- AP: Closed and transferred
- AR: Closed, transfer pending (agent submits ESS job)
- FA: Closed and transferred
- Projects: Open (agent flags for escalation)
- 1 unbalanced manual journal: $3,750 entity segment mismatch
- 1 intercompany imbalance: $850 net (elimination required)
- 3 accounts flagged in variance analysis (>10% movement)

### With a Live Oracle Fusion Instance

```bash
cp .env.example .env
# Edit .env with ORACLE_HOST, CLIENT_ID, CLIENT_SECRET, TOKEN_URL, ORACLE_LEDGER_ID

python examples/run_period_close.py --provider claude --period Jan-25
```

Oracle Cloud Free Trial provides 30 days of access to a full Oracle Fusion Apps environment — enough to validate against live `fscmRestApi` endpoints and real GL data.

---

## Running Tests

```bash
pytest tests/ -v
```

The test suite covers:
- Period status queries and prior-period calculation
- Subledger transfer trigger with application ID validation
- Intercompany imbalance detection and netting logic
- Variance analysis with threshold boundary cases
- Tool schema correctness for both Claude and OpenAI wire formats
- Agent tool dispatcher routing

---

## Oracle API Reference

| Endpoint | Purpose |
|---|---|
| `/fscmRestApi/resources/{v}/ledgerPeriodStatuses` | GL period open/close status |
| `/fscmRestApi/resources/{v}/generalLedgerJournals` | Journal headers with debit/credit totals |
| `/fscmRestApi/resources/{v}/generalLedgerTrialBalances` | Period trial balance by account |
| `/fscmRestApi/resources/{v}/intercompanyTransactions` | IC initiator/recipient pairs |
| `/fscmRestApi/resources/{v}/erpintegrations` | ESS job submission (subledger transfer) |
| `/analytics/saw.dll` | OTBI for XLA subledger close status |

XLA Application IDs: AP=200, AR=222, FA=140, Projects=275

---

## Project Structure

```
oracle-period-close-agent/
├── src/
│   ├── oracle/
│   │   ├── fusion_client.py       # OAuth2 REST client with token cache + retry
│   │   ├── period_queries.py      # GL period status, subledger status, trial balance
│   │   ├── intercompany_queries.py # IC imbalance detection and netting
│   │   └── variance_analysis.py   # Period-over-period variance flagging
│   ├── agents/
│   │   ├── tools.py               # 9-tool definitions, CLAUDE_TOOLS + OPENAI_TOOLS
│   │   ├── base_agent.py          # Abstract base: tool dispatcher, agentic loop
│   │   ├── claude_agent.py        # Anthropic tool_use implementation
│   │   ├── openai_agent.py        # OpenAI function_calling implementation
│   │   └── factory.py             # AgentFactory.create(provider=...)
│   └── reporting/
│       └── close_report.py        # HTML close report + SMTP controller notification
├── examples/
│   └── run_period_close.py        # CLI with MockFusionClient and --dry-run flag
├── tests/                         # pytest suite
└── config/
    └── settings.py                # Pydantic settings (Oracle, Agent, Notification)
```

---

## What's Next

- **AP Invoice Agent** — OCR → PO matching → 3-way match → FBDI submission to AP subledger
- **OIC Integration Health Agent** — monitors Oracle Integration Cloud flows, classifies failures, self-heals

---

*Part of a series of open-source agentic AI tools for Oracle Fusion Cloud ERP.*
