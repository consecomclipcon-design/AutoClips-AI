from pathlib import Path
import pytest
from autoclips import pipeline
from autoclips import database as db
from autoclips.transcript import save_transcript

def test_split_tool_rejects_path_traversal(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    db.init_db()
    tr=save_transcript('p',{'language':'pt','segments':[{'start':0,'end':2,'text':'Olá'}], 'words':[{'start':0,'end':2,'text':'Olá'}]},tmp_path)
    with db.conn() as c:
        c.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)',('p','file','source.mp4','Test',str(tmp_path/'source.mp4'),str(tr),3,'ready',None,db.now()))
    with pytest.raises(ValueError):
        pipeline.start_render_split('p',0,2,image_filename='../private.jpeg')

def test_split_tool_requires_valid_duration(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    db.init_db()
    tr=save_transcript('p',{'language':'pt','segments':[{'start':0,'end':2,'text':'Olá'}], 'words':[{'start':0,'end':2,'text':'Olá'}]},tmp_path)
    with db.conn() as c:
        c.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)',('p','file','source.mp4','Test',str(tmp_path/'source.mp4'),str(tr),200,'ready',None,db.now()))
    with pytest.raises(ValueError):
        pipeline.start_render_split('p',0,185)
