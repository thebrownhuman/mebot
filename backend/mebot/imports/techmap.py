"""Deterministic tech detection from manifests, file names and GitHub's language stats.

Every hit carries evidence (file + key) so the owner can see why a tech was proposed.
Malformed manifests are skipped with a note, never fatal. No network, no LLM.
"""

import json
import re
import tomllib
from dataclasses import dataclass, field

import yaml

LAYERS = ("frontend", "backend", "infra", "data_ai", "tooling")
LANGUAGE_MIN_SHARE = 0.05

F, B, N, D, T = "frontend", "backend", "infra", "data_ai", "tooling"

# lower-cased dependency / module / image name -> (display name, layer)
TECH: dict[str, tuple[str, str]] = {
    # JS frontend
    "react": ("React", F), "react-dom": ("React", F), "next": ("Next.js", F),
    "vue": ("Vue", F), "nuxt": ("Nuxt", F), "svelte": ("Svelte", F),
    "@sveltejs/kit": ("SvelteKit", F), "@angular/core": ("Angular", F),
    "solid-js": ("SolidJS", F), "preact": ("Preact", F), "astro": ("Astro", F),
    "tailwindcss": ("Tailwind CSS", F), "three": ("three.js", F),
    "@react-three/fiber": ("React Three Fiber", F), "redux": ("Redux", F),
    "@reduxjs/toolkit": ("Redux", F), "@tanstack/react-query": ("React Query", F),
    "react-router-dom": ("React Router", F), "react-router": ("React Router", F),
    "zustand": ("Zustand", F), "styled-components": ("styled-components", F),
    "@mui/material": ("Material UI", F), "@chakra-ui/react": ("Chakra UI", F),
    "bootstrap": ("Bootstrap", F), "d3": ("D3", F), "framer-motion": ("Framer Motion", F),
    "react-native": ("React Native", F), "expo": ("Expo", F), "electron": ("Electron", F),
    "jquery": ("jQuery", F),
    # JS backend
    "express": ("Express", B), "fastify": ("Fastify", B), "koa": ("Koa", B),
    "@nestjs/core": ("NestJS", B), "hono": ("Hono", B), "socket.io": ("Socket.IO", B),
    "graphql": ("GraphQL", B), "@apollo/server": ("Apollo", B), "apollo-server": ("Apollo", B),
    "prisma": ("Prisma", B), "@prisma/client": ("Prisma", B), "drizzle-orm": ("Drizzle", B),
    "typeorm": ("TypeORM", B), "sequelize": ("Sequelize", B), "mongoose": ("MongoDB", B),
    "mongodb": ("MongoDB", B), "pg": ("PostgreSQL", B), "mysql2": ("MySQL", B),
    "redis": ("Redis", B), "ioredis": ("Redis", B), "@supabase/supabase-js": ("Supabase", B),
    "firebase": ("Firebase", B), "stripe": ("Stripe", B), "trpc": ("tRPC", B),
    "@trpc/server": ("tRPC", B),
    # JS data/AI
    "openai": ("OpenAI API", D), "@anthropic-ai/sdk": ("Anthropic API", D),
    "langchain": ("LangChain", D), "@langchain/core": ("LangChain", D),
    "@tensorflow/tfjs": ("TensorFlow", D), "ai": ("Vercel AI SDK", D),
    # JS tooling
    "vite": ("Vite", T), "webpack": ("webpack", T), "typescript": ("TypeScript", T),
    "eslint": ("ESLint", T), "prettier": ("Prettier", T), "jest": ("Jest", T),
    "vitest": ("Vitest", T), "playwright": ("Playwright", T), "@playwright/test": ("Playwright", T),
    "cypress": ("Cypress", T), "storybook": ("Storybook", T),
    # Python
    "fastapi": ("FastAPI", B), "django": ("Django", B), "flask": ("Flask", B),
    "djangorestframework": ("Django REST Framework", B), "starlette": ("Starlette", B),
    "sqlalchemy": ("SQLAlchemy", B), "alembic": ("Alembic", B), "pydantic": ("Pydantic", B),
    "celery": ("Celery", B), "psycopg2": ("PostgreSQL", B), "psycopg2-binary": ("PostgreSQL", B),
    "psycopg": ("PostgreSQL", B), "asyncpg": ("PostgreSQL", B), "pymongo": ("MongoDB", B),
    "redis-py": ("Redis", B), "uvicorn": ("Uvicorn", B), "gunicorn": ("Gunicorn", B),
    "streamlit": ("Streamlit", F), "gradio": ("Gradio", F),
    "torch": ("PyTorch", D), "pytorch": ("PyTorch", D), "tensorflow": ("TensorFlow", D),
    "keras": ("Keras", D), "scikit-learn": ("scikit-learn", D), "sklearn": ("scikit-learn", D),
    "pandas": ("pandas", D), "numpy": ("NumPy", D), "polars": ("Polars", D),
    "transformers": ("Hugging Face Transformers", D), "anthropic": ("Anthropic API", D),
    "langgraph": ("LangGraph", D), "llama-index": ("LlamaIndex", D),
    "xgboost": ("XGBoost", D), "matplotlib": ("Matplotlib", D), "spacy": ("spaCy", D),
    "opencv-python": ("OpenCV", D), "pytest": ("pytest", T), "ruff": ("Ruff", T),
    "black": ("Black", T), "mypy": ("mypy", T), "poetry": ("Poetry", T),
    # Go
    "github.com/gin-gonic/gin": ("Gin", B), "github.com/labstack/echo": ("Echo", B),
    "github.com/gofiber/fiber": ("Fiber", B), "github.com/go-chi/chi": ("chi", B),
    "gorm.io/gorm": ("GORM", B), "github.com/jackc/pgx": ("PostgreSQL", B),
    "github.com/lib/pq": ("PostgreSQL", B), "github.com/redis/go-redis": ("Redis", B),
    "go.mongodb.org/mongo-driver": ("MongoDB", B), "github.com/spf13/cobra": ("Cobra", T),
    "google.golang.org/grpc": ("gRPC", B),
    # Rust
    "actix-web": ("Actix Web", B), "axum": ("Axum", B), "rocket": ("Rocket", B),
    "tokio": ("Tokio", B), "diesel": ("Diesel", B), "sqlx": ("SQLx", B), "serde": ("Serde", B),
    "tauri": ("Tauri", F), "bevy": ("Bevy", F), "leptos": ("Leptos", F), "yew": ("Yew", F),
    # JVM
    "spring-boot": ("Spring Boot", B), "spring-boot-starter-web": ("Spring Boot", B),
    "org.springframework.boot": ("Spring Boot", B), "hibernate-core": ("Hibernate", B),
    "postgresql": ("PostgreSQL", B), "mysql-connector-java": ("MySQL", B),
    "mysql-connector-j": ("MySQL", B), "junit-jupiter": ("JUnit", T), "junit": ("JUnit", T),
    "ktor-server-core": ("Ktor", B), "micronaut-core": ("Micronaut", B),
    "kotlinx-coroutines-core": ("Kotlin Coroutines", B),
    # PHP / Ruby / Dart
    "laravel/framework": ("Laravel", B), "symfony/framework-bundle": ("Symfony", B),
    "rails": ("Ruby on Rails", B), "sinatra": ("Sinatra", B), "pg-gem": ("PostgreSQL", B),
    "sidekiq": ("Sidekiq", B), "rspec": ("RSpec", T), "flutter": ("Flutter", F),
    "firebase_core": ("Firebase", B), "provider": ("Provider", F), "riverpod": ("Riverpod", F),
    # Docker images (compose / FROM)
    "image:postgres": ("PostgreSQL", B), "image:mysql": ("MySQL", B), "image:mariadb": ("MariaDB", B),  # noqa: E501
    "image:mongo": ("MongoDB", B), "image:redis": ("Redis", B), "image:nginx": ("Nginx", N),
    "image:rabbitmq": ("RabbitMQ", B), "image:elasticsearch": ("Elasticsearch", B),
    "image:ollama/ollama": ("Ollama", D), "image:traefik": ("Traefik", N),
    "image:minio/minio": ("MinIO", N), "image:confluentinc/cp-kafka": ("Kafka", B),
    "image:bitnami/kafka": ("Kafka", B),
}  # fmt: skip

# Scoped packages: any package in the scope means the tech.
SCOPES: dict[str, tuple[str, str]] = {
    "@angular/": ("Angular", F),
    "@nestjs/": ("NestJS", B),
    "@mui/": ("Material UI", F),
    "@chakra-ui/": ("Chakra UI", F),
    "@radix-ui/": ("Radix UI", F),
    "@aws-sdk/": ("AWS SDK", N),
    "@supabase/": ("Supabase", B),
    "@sveltejs/": ("SvelteKit", F),
    "@vue/": ("Vue", F),
    "@trpc/": ("tRPC", B),
    "@langchain/": ("LangChain", D),
    "@tensorflow/": ("TensorFlow", D),
    "@storybook/": ("Storybook", T),
}
IGNORED_SCOPES = ("@types/",)

# Detected from a file name alone.
FILE_TECH: list[tuple[re.Pattern, tuple[str, str]]] = [
    (re.compile(r"(^|/)Dockerfile$"), ("Docker", N)),
    (re.compile(r"(^|/)docker-compose[\w.-]*\.ya?ml$"), ("Docker Compose", N)),
    (re.compile(r"(^|/)vercel\.json$"), ("Vercel", N)),
    (re.compile(r"(^|/)netlify\.toml$"), ("Netlify", N)),
    (re.compile(r"(^|/)fly\.toml$"), ("Fly.io", N)),
    (re.compile(r"(^|/)railway\.toml$"), ("Railway", N)),
    (re.compile(r"\.tf$"), ("Terraform", N)),
    (re.compile(r"^\.github/workflows/[\w.-]+\.ya?ml$"), ("GitHub Actions", N)),
    (re.compile(r"(^|/)angular\.json$"), ("Angular", F)),
    (re.compile(r"(^|/)next\.config\.\w+$"), ("Next.js", F)),
    (re.compile(r"(^|/)vite\.config\.\w+$"), ("Vite", T)),
    (re.compile(r"(^|/)tailwind\.config\.\w+$"), ("Tailwind CSS", F)),
    (re.compile(r"(^|/)schema\.prisma$"), ("Prisma", B)),
]

GO_PREFIXES = sorted(
    (k for k in TECH if "/" in k and "." in k.split("/")[0]), key=len, reverse=True
)


@dataclass
class Detection:
    by_layer: dict[str, list[str]] = field(default_factory=lambda: {k: [] for k in LAYERS})
    languages: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, name: str, layer: str, file: str, key: str) -> None:
        if name not in self.by_layer[layer]:
            self.by_layer[layer].append(name)
        if not any(e["tech"] == name and e["file"] == file for e in self.evidence):
            self.evidence.append({"tech": name, "file": file, "key": key})

    @property
    def tech(self) -> list[str]:
        out: list[str] = []
        for name in [*self.languages, *(t for layer in ("backend", "frontend", "data_ai", "infra", "tooling")  # noqa: E501
                                       for t in self.by_layer[layer])]:  # fmt: skip
            if name not in out:
                out.append(name)
        return out


def lookup(key: str) -> tuple[str, str] | None:
    k = key.strip().lower()
    if not k or any(k.startswith(s) for s in IGNORED_SCOPES):
        return None
    if k in TECH:
        return TECH[k]
    for scope, hit in SCOPES.items():
        if k.startswith(scope):
            return hit
    for prefix in GO_PREFIXES:  # github.com/labstack/echo/v4 -> echo
        if k.startswith(prefix + "/") or k == prefix:
            return TECH[prefix]
    return None


def _py_name(spec: str) -> str:
    name = re.split(r"[\s<>=!~;\[(@]", spec.strip(), maxsplit=1)[0]
    return name.lower().replace("_", "-")


# --- parsers: text -> dependency keys ------------------------------------------------------


def _package_json(text: str) -> list[str]:
    data = json.loads(text)
    keys: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(section) if isinstance(data, dict) else None
        if isinstance(deps, dict):
            keys += list(deps)
    return keys


def _requirements(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.append(_py_name(line))
    return out


def _pyproject(text: str) -> list[str]:
    data = tomllib.loads(text)
    project = data.get("project") or {}
    specs = list(project.get("dependencies") or [])
    for group in (project.get("optional-dependencies") or {}).values():
        specs += list(group or [])
    keys = [_py_name(s) for s in specs if isinstance(s, str)]
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for section in ("dependencies", "dev-dependencies"):
        keys += [k.lower() for k in (poetry.get(section) or {}) if k.lower() != "python"]
    for group in (poetry.get("group") or {}).values():
        keys += [k.lower() for k in ((group or {}).get("dependencies") or {})]
    return keys


def _pipfile(text: str) -> list[str]:
    data = tomllib.loads(text)
    return [k.lower() for s in ("packages", "dev-packages") for k in (data.get(s) or {})]


def _go_mod(text: str) -> list[str]:
    keys = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("require "):
            line = line[len("require ") :].strip()
        m = re.match(r"^([\w.-]+\.[\w.-]+/[\w./-]+)\s+v", line)
        if m:
            keys.append(m.group(1))
    return keys


def _cargo(text: str) -> list[str]:
    data = tomllib.loads(text)
    keys = []
    for section in ("dependencies", "dev-dependencies"):
        keys += list(data.get(section) or {})
    for ws in ((data.get("workspace") or {}).get("dependencies") or {},):
        keys += list(ws)
    return keys


def _pom(text: str) -> list[str]:
    return re.findall(r"<artifactId>\s*([\w.-]+)\s*</artifactId>", text)


def _gradle(text: str) -> list[str]:
    keys = re.findall(r"""['"][\w.-]+:([\w.-]+)(?::[^'"]*)?['"]""", text)
    keys += re.findall(r"""id\s*\(?\s*['"]([\w.-]+)['"]""", text)
    if re.search(r"kotlin\(|org\.jetbrains\.kotlin", text):
        keys.append("kotlin")
    return keys


def _composer(text: str) -> list[str]:
    data = json.loads(text)
    return [k.lower() for s in ("require", "require-dev") for k in ((data or {}).get(s) or {})]


def _gemfile(text: str) -> list[str]:
    keys = re.findall(r"""^\s*gem\s+['"]([\w.-]+)['"]""", text, re.MULTILINE)
    return ["pg-gem" if k == "pg" else k for k in keys]


def _pubspec(text: str) -> list[str]:
    data = yaml.safe_load(text) or {}
    keys = []
    for section in ("dependencies", "dev_dependencies"):
        keys += list((data.get(section) or {}) if isinstance(data, dict) else {})
    return [str(k) for k in keys]


def _images(text: str, compose: bool) -> list[str]:
    if compose:
        data = yaml.safe_load(text) or {}
        services = data.get("services") if isinstance(data, dict) else None
        names = [s.get("image", "") for s in (services or {}).values() if isinstance(s, dict)]
    else:
        names = re.findall(
            r"^\s*FROM\s+(?:--\S+\s+)?([\w./-]+)", text, re.MULTILINE | re.IGNORECASE
        )
    out = []
    for n in names:
        base = str(n).split("@")[0].split(":")[0].lower()
        base = base.removeprefix("docker.io/").removeprefix("library/")
        out.append("image:" + base)
    return out


def _prisma(text: str) -> list[str]:
    m = re.search(r'provider\s*=\s*"(postgresql|mysql|mongodb|sqlite)"', text)
    return {"postgresql": ["pg"], "mysql": ["mysql2"], "mongodb": ["mongodb"]}.get(
        m.group(1) if m else "", []
    )


PARSERS: list[tuple[re.Pattern, callable]] = [
    (re.compile(r"(^|/)package\.json$"), _package_json),
    (re.compile(r"(^|/)requirements[\w.-]*\.txt$"), _requirements),
    (re.compile(r"(^|/)pyproject\.toml$"), _pyproject),
    (re.compile(r"(^|/)Pipfile$"), _pipfile),
    (re.compile(r"(^|/)go\.mod$"), _go_mod),
    (re.compile(r"(^|/)Cargo\.toml$"), _cargo),
    (re.compile(r"(^|/)pom\.xml$"), _pom),
    (re.compile(r"(^|/)build\.gradle(\.kts)?$"), _gradle),
    (re.compile(r"(^|/)composer\.json$"), _composer),
    (re.compile(r"(^|/)Gemfile$"), _gemfile),
    (re.compile(r"(^|/)pubspec\.yaml$"), _pubspec),
    (re.compile(r"(^|/)Dockerfile$"), lambda t: _images(t, compose=False)),
    (re.compile(r"(^|/)docker-compose[\w.-]*\.ya?ml$"), lambda t: _images(t, compose=True)),
    (re.compile(r"(^|/)schema\.prisma$"), _prisma),
]


def detect(files: dict[str, str], paths: list[str], languages: dict[str, int]) -> Detection:
    d = Detection()
    total = sum(languages.values()) or 0
    for lang, size in sorted(languages.items(), key=lambda kv: -kv[1]):
        if total and size / total >= LANGUAGE_MIN_SHARE:
            d.languages.append(lang)
            d.evidence.append(
                {"tech": lang, "file": "GitHub languages", "key": f"{size * 100 // total}%"}
            )
    for path in paths:
        for rx, (name, layer) in FILE_TECH:
            if rx.search(path):
                d.add(name, layer, path, path.rsplit("/", 1)[-1])
    for path, text in files.items():
        parser = next((p for rx, p in PARSERS if rx.search(path)), None)
        if parser is None:
            continue
        try:
            keys = parser(text)
        except (ValueError, tomllib.TOMLDecodeError, yaml.YAMLError, AttributeError, TypeError):
            d.notes.append(f"{path}: couldn't be parsed, skipped")
            continue
        for key in keys:
            if str(key).lower() == "kotlin" and "Kotlin" not in d.languages:
                d.languages.append("Kotlin")
                d.evidence.append({"tech": "Kotlin", "file": path, "key": "kotlin"})
                continue
            hit = lookup(str(key))
            if hit:
                d.add(hit[0], hit[1], path, str(key))
    return d
