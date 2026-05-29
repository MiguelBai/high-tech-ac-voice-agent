# High Tech AC — Voice Agent ("Sarah v2")

Private production project for **High Tech Air Conditioning** (Orlando, FL): a **Retell AI**
voice agent named **Sarah v2** bridged by a Flask backend to **Housecall Pro** for real job
booking, with a live-call dashboard, Telegram alerts, and AI call-quality review.

The voice agent runs on Retell's platform; this repo is the webhook/tool backend + monitoring UI.

## Start here

| If you want… | Read |
|---|---|
| 🇧🇷 **Onboarding (Portuguese)** — full project walkthrough for new team members | [`docs/RESUMO_PROJETO_PT.md`](docs/RESUMO_PROJETO_PT.md) |
| 🇺🇸 **Technical guide (English)** — architecture, deploy model, Retell API workflow | [`CLAUDE.md`](CLAUDE.md) |
| The voice agent's prompt | [`retell/planning/retell_agent_prompt_v2.md`](retell/planning/retell_agent_prompt_v2.md) |

## Two things to know before touching anything

1. **`server.py` is the single source of truth and is identical to production.** To deploy, copy
   it into the separate `deploy/` repo and run `railway up` — see `CLAUDE.md` → "Deploy model".
   Never edit `deploy/server.py` directly.
2. **Secrets live only in `.env` (gitignored) and on Railway** — never commit credentials.
   Copy `.env.example` to `.env` and fill in real values to run locally.

## Layout

```
server.py            THE app (single source of truth, identical to production)
CLAUDE.md            technical guide (English)
docs/                onboarding (PT), market research, deploy notes, test plans
retell/planning/     agent prompt v2, tool definitions, simulation suite
knowledge_base/      company knowledge base
proposals/           client-deliverable PDF generators
```

Run locally: `pip install -r requirements.txt && python3 server.py` (needs `.env`).
</content>
