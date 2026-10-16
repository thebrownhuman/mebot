from datetime import timedelta

from mebot.models import utcnow
from mebot.repos import bots
from mebot.repos import import_jobs as jobs


def _bot(app):
    with app.state.session_factory() as db:
        return bots.get_primary(db).id


def test_create_finish_and_expire(app):
    bot_id = _bot(app)
    with app.state.session_factory() as db:
        job = jobs.create(db, bot_id, "resume", filename="cv.pdf", sha256="a" * 64, size=10)
        assert job.status == "processing"
        assert job.expires_at - job.created_at == jobs.TTL
        jobs.finish(db, job, {"sections": {}}, "text")
        assert jobs.ready_with_hash(db, bot_id, "resume", "a" * 64) is job
        assert jobs.ready_with_hash(db, bot_id, "linkedin", "a" * 64) is None
        job.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert jobs.purge_expired(db) == 1
        db.commit()
        db.refresh(job)
        assert job.status == "expired" and job.draft is None and job.source_text is None
        assert jobs.ready_with_hash(db, bot_id, "resume", "a" * 64) is None


def test_applied_jobs_are_not_expired(app):
    bot_id = _bot(app)
    with app.state.session_factory() as db:
        job = jobs.create(db, bot_id, "linkedin", filename="x.zip", sha256="d" * 64, size=1)
        jobs.mark_applied(db, job, {"skills": {"added": 1, "updated": 0}})
        job.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert jobs.purge_expired(db) == 0


def test_stale_processing_job_fails(app):
    bot_id = _bot(app)
    with app.state.session_factory() as db:
        job = jobs.create(db, bot_id, "resume", filename="cv.pdf", sha256="b" * 64, size=1)
        assert jobs.processing(db, bot_id) is job
        job.updated_at = utcnow() - jobs.STALE - timedelta(seconds=1)
        assert jobs.processing(db, bot_id) is None
        assert job.status == "failed"


def test_any_kind_string_is_storable(app):
    bot_id = _bot(app)
    with app.state.session_factory() as db:
        job = jobs.create(db, bot_id, "github", filename="octocat", sha256="c" * 64, size=0)
        db.commit()
        assert jobs.get(db, bot_id, job.id).kind == "github"
