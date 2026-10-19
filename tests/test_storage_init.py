from autoclips import pipeline
from autoclips.settings import home
from autoclips import database as db


def test_new_workspace_initializes_own_sqlite_file(tmp_path,monkeypatch):
    a=tmp_path/'one';b=tmp_path/'two'
    monkeypatch.setenv('AUTOCLIPS_HOME',str(a))
    pipeline.init()
    monkeypatch.setenv('AUTOCLIPS_HOME',str(b))
    pipeline.init()
    assert (b/'autoclips.sqlite3').is_file()
    with db.conn() as c:
        assert c.execute("select name from sqlite_master where name='projects'").fetchone() is not None
