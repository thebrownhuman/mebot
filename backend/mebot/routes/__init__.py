from mebot.routes import (
    admin,
    admin_limits,
    admin_llm,
    admin_profile,
    admin_telegram,
    auth,
    chat,
    health,
    public,
    sessions,
    setup,
    telegram_webhook,
)

routers = [
    health.router,
    setup.router,
    auth.router,
    sessions.router,
    public.router,
    chat.router,
    admin.router,
    admin_llm.router,
    admin_limits.router,
    admin_telegram.router,
    telegram_webhook.router,
    admin_profile.router,
]
