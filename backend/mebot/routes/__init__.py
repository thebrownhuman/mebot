from mebot.routes import admin, admin_llm, admin_profile, auth, chat, health, sessions, setup

routers = [
    health.router,
    setup.router,
    auth.router,
    sessions.router,
    chat.router,
    admin.router,
    admin_llm.router,
    admin_profile.router,
]
