from pathlib import Path
import json
import fitz
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
out = root / 'tmp' / 'pdfs' / 'keymap-v9-render'
out.mkdir(parents=True, exist_ok=True)
document = fitz.open(root / 'agentdeck' / '使用说明书.pdf')
pages = []
issues = []
for index, page in enumerate(document):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
    path = out / f'page-{index + 1:02d}.png'
    pixmap.save(path)
    im = Image.open(path).convert('RGB')
    im.thumbnail((290, 500))
    tile = Image.new('RGB', (310, 530), '#d2d2d2')
    tile.paste(im, ((310-im.width)//2, 22))
    ImageDraw.Draw(tile).text((12, 5), str(index + 1), fill='#111')
    pages.append(tile)
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            for span in line.get('spans', []):
                x0, y0, x1, y1 = span['bbox']
                if x0 < 8 or y0 < 8 or x1 > page.rect.width - 8 or y1 > page.rect.height - 8:
                    issues.append({'page': index + 1, 'text': span['text'], 'bbox': span['bbox']})
sheet = Image.new('RGB', (310 * 4, 530 * 4), '#b0b0b0')
for index, tile in enumerate(pages):
    sheet.paste(tile, ((index % 4) * 310, (index // 4) * 530))
sheet.save(out / 'contact-sheet.png')
print(json.dumps({'pages': len(document), 'page_size_pt': list(document[0].rect),
                  'boundary_issues': issues, 'render_dir': str(out)}, ensure_ascii=False, indent=2))
