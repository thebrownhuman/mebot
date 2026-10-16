import json

from mebot.imports import techmap


def det(files=None, paths=(), languages=None):
    return techmap.detect(files or {}, list(paths), languages or {})


def test_table_size_and_layers():
    assert len(techmap.TECH) >= 80
    assert all(layer in techmap.LAYERS for _, layer in techmap.TECH.values())


def test_package_json_with_scopes_and_evidence():
    pkg = json.dumps(
        {
            "dependencies": {
                "react": "18",
                "@angular/forms": "17",
                "@nestjs/common": "10",
                "@prisma/client": "5",
                "openai": "4",
            },  # fmt: skip
            "devDependencies": {"vite": "5", "@types/node": "20", "left-pad": "1"},
        }
    )
    d = det({"web/package.json": pkg})
    assert d.by_layer["frontend"] == ["React", "Angular"]
    assert d.by_layer["backend"] == ["NestJS", "Prisma"]
    assert d.by_layer["data_ai"] == ["OpenAI API"] and d.by_layer["tooling"] == ["Vite"]
    assert {"tech": "Angular", "file": "web/package.json", "key": "@angular/forms"} in d.evidence
    assert not any("types" in e["key"] for e in d.evidence)


def test_python_ecosystems():
    req = "FastAPI>=0.110\nSQLAlchemy[asyncio]==2.0\n-r base.txt\n# x\npsycopg2_binary\n"
    pyproject = (
        '[project]\ndependencies = ["django>=5", "celery"]\n'
        '[project.optional-dependencies]\nml = ["torch", "scikit-learn"]\n'
        "[tool.poetry.dependencies]\npython = '^3.12'\npandas = '*'\n"
    )
    pipfile = '[packages]\nflask = "*"\n[dev-packages]\npytest = "*"\n'
    d = det({"requirements.txt": req, "pyproject.toml": pyproject, "Pipfile": pipfile})
    assert set(d.by_layer["backend"]) >= {
        "FastAPI",
        "SQLAlchemy",
        "PostgreSQL",
        "Django",
        "Celery",
        "Flask",
    }
    assert set(d.by_layer["data_ai"]) >= {"PyTorch", "scikit-learn", "pandas"}
    assert "pytest" in d.by_layer["tooling"]


def test_go_rust_jvm_php_ruby_dart():
    gomod = "module x\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgithub.com/labstack/echo/v4 v4.1\n\tgorm.io/gorm v1.25\n)\nrequire github.com/lib/pq v1.10\n"  # noqa: E501
    cargo = '[dependencies]\naxum = "0.7"\ntokio = { version = "1" }\n'
    pom = "<project><dependencies><dependency><artifactId>spring-boot-starter-web</artifactId></dependency></dependencies></project>"  # noqa: E501
    gradle = 'plugins { id("org.springframework.boot") version "3" }\ndependencies { implementation("org.postgresql:postgresql:42") }\n'  # noqa: E501
    composer = json.dumps({"require": {"laravel/framework": "^11"}})
    gemfile = "source 'x'\ngem 'rails', '~> 7'\ngem \"pg\"\n"
    pubspec = "name: app\ndependencies:\n  flutter:\n    sdk: flutter\n  firebase_core: ^2.0\n"
    d = det({"go.mod": gomod, "Cargo.toml": cargo, "pom.xml": pom, "build.gradle.kts": gradle,
             "composer.json": composer, "Gemfile": gemfile, "pubspec.yaml": pubspec})  # fmt: skip
    be = set(d.by_layer["backend"])
    assert {"Gin", "Echo", "GORM", "PostgreSQL", "Axum", "Tokio", "Spring Boot", "Laravel",
            "Ruby on Rails", "Firebase"} <= be  # fmt: skip
    assert "Flutter" in d.by_layer["frontend"]


def test_docker_compose_and_file_names():
    compose = "services:\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7-alpine\n  web:\n    build: .\n"  # noqa: E501
    d = det(
        {"docker-compose.yml": compose, "Dockerfile": "FROM nginx:alpine\n"},
        paths=[
            "Dockerfile",
            "docker-compose.yml",
            "vercel.json",
            "infra/main.tf",
            ".github/workflows/ci.yml",
            "next.config.mjs",
            "tailwind.config.js",
        ],  # fmt: skip
    )
    assert {"PostgreSQL", "Redis"} <= set(d.by_layer["backend"])
    assert {"Docker", "Docker Compose", "Vercel", "Terraform", "GitHub Actions", "Nginx"} <= set(
        d.by_layer["infra"]
    )
    assert {"Next.js", "Tailwind CSS"} <= set(d.by_layer["frontend"])


def test_languages_over_five_percent_first_in_tech():
    d = det(
        {"requirements.txt": "fastapi\n"}, languages={"Python": 900, "TypeScript": 60, "Shell": 40}
    )
    assert d.languages == ["Python", "TypeScript"]
    assert d.tech[:3] == ["Python", "TypeScript", "FastAPI"]
    assert {"tech": "Python", "file": "GitHub languages", "key": "90%"} in d.evidence


def test_malformed_manifests_are_noted_not_fatal():
    d = det({"package.json": "{not json", "pyproject.toml": "[[[", "pubspec.yaml": ":\n  - : [",
             "requirements.txt": "flask\n"})  # fmt: skip
    assert d.by_layer["backend"] == ["Flask"]
    assert len(d.notes) == 3 and all("couldn't be parsed" in n for n in d.notes)


def test_lookup_case_insensitive():
    assert techmap.lookup("React") == ("React", "frontend")
    assert techmap.lookup("@types/react") is None
    assert techmap.lookup("unknown-thing") is None
