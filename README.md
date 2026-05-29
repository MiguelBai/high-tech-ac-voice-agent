# High Tech AC — Voice Agent ("Sarah v2")

Private production project for **High Tech Air Conditioning** (Orlando, FL): a **Retell AI**
voice agent named **Sarah v2** bridged by a Flask backend to **Housecall Pro** for real job
booking, with a live-call dashboard, Telegram alerts, and AI call-quality review.

The voice agent runs on Retell's platform; this repo is the webhook/tool backend + monitoring UI.

## Start here

| If you want… | Read |
|---|---|
| 🇧🇷 **Onboarding (Portuguese)** — full project walkthrough for new team members | [`docs/RESUMO_PROJETO_PT.md`](docs/RESUMO_PROJETO_PT.md) |
| 🇺🇸 **Technical guide (English)** — architecture, deploy model, Retell API workflow, gotchas | [`CLAUDE.md`](CLAUDE.md) |
| What actually runs in production | [`live-production/`](live-production/) |
| The voice agent's prompt | [`retell/planning/retell_agent_prompt_v2.md`](retell/planning/retell_agent_prompt_v2.md) |

## ⚠️ Two things to know before touching anything

1. **`deploy/` is the canonical live code, and it's ahead of root `server.py`.** Never blind-copy
   root → deploy. See `CLAUDE.md` → "Deploy model" and `docs/RESUMO_PROJETO_PT.md` → section 7.
2. **Secrets live only in `.env` (gitignored) and on Railway** — never commit credentials.
   Copy `.env.example` to `.env` and fill in real values to run locally.

## Layout

```
server.py            dev-workspace app (behind production — see live-production/)
live-production/     read-only snapshot of what Railway runs
CLAUDE.md            technical guide (English)
docs/                onboarding (PT), market research, deploy notes, test plans
retell/planning/     agent prompt v2, tool definitions, simulation suite
knowledge_base/      company knowledge base
proposals/           client-deliverable PDF generators
```

Run locally: `pip install -r requirements.txt && python3 server.py` (needs `.env`).
</content>
