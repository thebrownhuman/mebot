from mebot.routes import chat, health, log, profile, sessions

routers = [health.router, profile.router, sessions.router, chat.router, log.router]
