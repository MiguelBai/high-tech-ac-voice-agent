# live-production/ — snapshot of what Railway actually runs

This folder is a **read-only snapshot** of the canonical production app that runs on
Railway (service `HVAC Retell Alfredo`). The real working copy is the separate `deploy/`
git repo on Miguel's machine (linked to Railway), which is **not** included in this
GitHub repo.

> ⚠️ This snapshot can drift from what's actually deployed. Treat it as reference for
> reading/reviewing the production code, **not** as the deploy source. Real deploys go
> through the `deploy/` repo using the clean-staging `railway up` recipe — see
> `../CLAUDE.md` ("Deploy model") and `../docs/RESUMO_PROJETO_PT.md` (section 7).

The root `../server.py` is the **dev-workspace** version and is behind this one
(it still uses the old Twilio notification path). `server.py` here is the feature-complete
live version (Telegram alerts, Message Center, web push, returning-caller HCP lookup,
transfer-contact manager, Retell signature verification).

To refresh this snapshot:

```bash
cp deploy/server.py deploy/Procfile deploy/requirements.txt deploy/logo.png live-production/
cp -r deploy/assets live-production/assets
```
</content>
