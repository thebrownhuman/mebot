from mebot.routes import admin, admin_llm, auth, chat, health, sessions, setup

routers = [
    health.router,
    setup.router,
    auth.router,
    sessions.router,
    chat.router,
    admin.router,
    admin_llm.router,
]
