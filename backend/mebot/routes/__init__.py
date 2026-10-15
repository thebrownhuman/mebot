from mebot.routes import admin, auth, chat, health, sessions, setup

routers = [
    health.router,
    setup.router,
    auth.router,
    sessions.router,
    chat.router,
    admin.router,
]
