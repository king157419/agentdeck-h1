"""Apply Gemini's page-by-page polish (titles + speaker notes) to the built BP.

Run after build_bp.js:  python apply_polish.py
Cover (page 1) keeps its title: the product name is not decided yet.
"""
import io
import re
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER


def title_shape(slide):
    for sh in slide.shapes:
        if sh.is_placeholder and sh.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
            return sh
    return None

HERE = Path(__file__).resolve().parent
POLISH = HERE.parent / "review" / "BP逐页打磨-gemini.md"
DECK = HERE / "AgentDeck-天使轮BP.pptx"
KEEP_TITLE = {1, 17}  # name and team size are the founders' call
# Claims the founders have not confirmed yet & latest test/model numbers: keep notes strictly factual.
NOTE_FIXES = [
    ("我们在做『点将台』，原暂定名 AgentDeck，下一步会完成商标核准改名", "我们在做 AgentDeck（暂名，路演前将完成改名与商标核查）"),
    ("二百五十二项单测", "二百六十四项单测"),
    ("一美元订金测试", "早鸟订金测试"),
    ("留住约一百五十万现金", "留住约一百五十到一百六十万现金"),
    ("三位创始人亲手", "创始团队亲手"),
    ("，并承诺盈利前锁定低薪", ""),
]

text = io.open(POLISH, encoding="utf-8").read()
pages = {}
for m in re.finditer(r"^### 第 (\d+) 页.*?(?=^### 第 \d+ 页|^## )", text, re.S | re.M):
    block, n = m.group(0), int(m.group(1))
    title = re.search(r"新标题\*\*：`([^`]+)`", block)
    speech = re.search(r"④ 演讲稿.*?\n\s*>\s*(.+?)(?:\n\s*\n|\n---|\Z)", block, re.S)
    pages[n] = (title.group(1).strip() if title else None,
                re.sub(r"\s*\n\s*>?\s*", "", speech.group(1)).strip() if speech else None)

prs = Presentation(DECK)
changed = []
for i, slide in enumerate(prs.slides, 1):
    title, speech = pages.get(i, (None, None))
    ts = title_shape(slide)
    if title and i not in KEEP_TITLE and ts is not None:
        tf = ts.text_frame
        runs = [r for p in tf.paragraphs for r in p.runs]
        if runs and "".join(r.text for r in runs) != title:
            runs[0].text = title
            for r in runs[1:]:
                r.text = ""
            changed.append((i, "title", title))
    if speech:
        for a, b in NOTE_FIXES:
            speech = speech.replace(a, b)
        notes = slide.notes_slide.notes_text_frame
        old = notes.text.strip()
        if old != speech:
            notes.text = speech
            changed.append((i, "notes", len(speech)))
prs.save(DECK)
for c in changed:
    print(c)
print("pages parsed:", len(pages), "slides:", len(prs.slides))
