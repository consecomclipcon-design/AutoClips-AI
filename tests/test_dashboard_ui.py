"""AutoClips Studio layout and interaction regression checks."""
from pathlib import Path
from html.parser import HTMLParser
import re

HTML = (Path(__file__).resolve().parents[1] / "dashboard.html").read_text(encoding="utf-8")


class ElementIDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id":
                self.ids.add(value)


def test_no_dangling_javascript_element_ids():
    parser = ElementIDs()
    parser.feed(HTML)
    referenced = set(re.findall(r"\$\('([^']+)'\)", HTML))
    assert referenced <= parser.ids, sorted(referenced - parser.ids)


def test_three_panels_start_at_same_grid_row():
    assert "grid-template-columns:235px minmax(0,1fr) 260px" in HTML
    assert ".wrap{max-width:1620px" in HTML
    assert ".feed-zone{align-self:start;min-height:0;align-items:flex-start" in HTML
    assert '<main class="feed-zone">' in HTML
    assert 'class="sidebar" id="sidebar"' in HTML
    assert 'class="rightbar" id="rightbar"' in HTML


def test_only_compact_controls_remain_in_side_panels():
    left = HTML.split('<aside class="sidebar" id="sidebar">', 1)[1].split("</aside>", 1)[0]
    right = HTML.split('<aside class="rightbar" id="rightbar">', 1)[1].split("</aside>", 1)[0]
    assert "Painel de controle" in left
    assert "Feed de cortes" in left
    assert "Publicações" in left and 'id="used"' in left
    assert "Atalhos" not in left and "Importar links" not in left
    assert "Adicionar vídeo" in right
    assert right.count("<input") == 1
    assert 'id="links"' in right and 'id="addLinks"' in right
    assert "Enviar para edição" in right
    assert "<textarea" not in right
    assert "Short pronto" not in right and "Fila de processamento" not in right


def test_remake_requires_feedback_modal_and_sends_it_to_backend():
    assert 'id="remakeModal"' in HTML and 'role="dialog"' in HTML
    assert 'id="remakeReason"' in HTML and "required maxlength=\"1400\"" in HTML
    assert "clip_id:id,decision:'dislike',comment,rights_confirmed:false" in HTML
    assert "advanceAfterAction(id)" in HTML
    assert "toggleRemakeModal(false)" in HTML


def test_private_publish_confirms_rights_and_advances():
    assert "window.confirm(" in HTML
    assert "clip_id:item.id,decision:'like',rights_confirmed:true" in HTML
    assert "advanceAfterAction(item.id)" in HTML
    assert "submitting=true" in HTML


def test_swipe_navigation_and_periodic_refresh_dont_pause_video():
    assert "'wheel'" in HTML and "'touchstart'" in HTML and "'touchend'" in HTML
    assert "v.getAttribute('src')!==item.mediaUrl" in HTML
    assert "v.pause();v.src=item.mediaUrl;v.load();" in HTML
