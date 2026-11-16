"""Le migrazioni devono conservare i dati esistenti (in SQLite le tabelle vengono ricreate)."""
import sqlite3

from flask_migrate import downgrade, upgrade

from app import create_app


def test_migrations_preserve_data(tmp_path, monkeypatch):
    db_path = tmp_path / "migr.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SECRET_KEY", "x")
    from app import config

    monkeypatch.setattr(config.DevelopmentConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_path}")
    app = create_app("development")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    with app.app_context():
        upgrade(revision="3ad711de9972")
        con = sqlite3.connect(db_path)
        con.executescript("""
            INSERT INTO families (id, name, timezone, created_at, updated_at) VALUES (1, 'F', 'Europe/Rome', '2026-01-01', '2026-01-01');
            INSERT INTO users (id, email, password_hash, is_active, current_family_id, theme, failed_login_count, created_at, updated_at)
                VALUES (1, 'a@b.it', 'x', 1, 1, 'auto', 0, '2026-01-01', '2026-01-01');
            UPDATE families SET created_by_user_id = 1;
            INSERT INTO profiles (id, user_id, display_name, color, created_at, updated_at) VALUES (1, 1, 'A', '#000000', '2026-01-01', '2026-01-01');
            INSERT INTO family_members (id, family_id, profile_id, role, joined_at) VALUES (1, 1, 1, 'admin', '2026-01-01');
        """)
        con.commit()
        upgrade()
        downgrade(revision="3ad711de9972")
        upgrade()
        rows = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("users", "profiles", "family_members", "families")}
        assert rows == {"users": 1, "profiles": 1, "family_members": 1, "families": 1}
        assert con.execute("SELECT created_by_user_id FROM families").fetchone()[0] == 1
        assert con.execute("SELECT weekly_summary FROM users").fetchone()[0] == 1
        con.close()
