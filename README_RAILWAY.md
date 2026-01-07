# Deploying to Railway

This repository contains a Telegram signal bot that can run on Railway as a long-running worker.

Quick steps to deploy on Railway:

1. Create a new Railway project and connect the repository.
2. In the Railway UI, create a new "Worker" service (not a static web service) and select the branch `railway-`.
3. Add the following environment variables in Railway's Settings > Variables:
   - `TELEGRAM_BOT_TOKEN` — your bot token
   - `ADMIN_TELEGRAM_ID` — your admin user id
   - `SIGNAL_CHANNEL_ID` — channel id for `/signal` posts (optional)
   - `ENCRYPTION_SECRET` — Fernet key for encrypting API keys
   - Any other env vars you use locally (e.g., `DEFAULT_TRADE_AMOUNT`)
4. Railway will detect the Python project (pyproject.toml). If needed, set the start command to use the `Procfile` or use the command:

```
python -m signal_bot.run --polling
```

Notes & recommendations
- Use a `Worker` process type (the bot uses long-polling). If you prefer webhooks, you'll need to implement webhook handling and expose a public HTTPS endpoint.
- Keep `main` protected and do not merge the `railway-` branch into main unless you want to deploy from main.
- Railway will provide logs; check them for network issues. Set sensible health checks (the bot is long-running and should not be killed on temporary network errors).

Security
- Store API secrets only in Railway environment variables or a secrets manager.
- Do not commit API keys to the repository.

If you want, I can also add a simple `Dockerfile` or `railway.toml` to further tune resource sizing and platform-specific settings. 
