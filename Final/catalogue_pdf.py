"""Customer-safe catalogues from a single current shared-database snapshot."""
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

from PIL import Image as PILImage, ImageOps
import reportlab
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

for name, filename in [('KJ', 'Vera.ttf'), ('KJB', 'VeraBd.ttf')]:
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(Path(reportlab.__file__).parent / 'fonts' / filename)))

RUST = colors.HexColor('#9e5430')
INK = colors.HexColor('#40291c')
STYLE = ParagraphStyle('body', fontName='KJ', fontSize=9, leading=14, textColor=INK)
TITLE = ParagraphStyle('title', parent=STYLE, fontName='KJB', fontSize=12, leading=17, spaceAfter=6)
HEADING = ParagraphStyle('category', parent=TITLE, fontSize=17, leading=22, spaceBefore=20, spaceAfter=12)


def photo(path, root, data_dir):
    """Read local assets only; catalogue fields cannot fetch URLs or escape roots."""
    if not isinstance(path, str) or not path or '..' in Path(path).parts:
        return Paragraph('Photo unavailable', STYLE)
    if path.startswith('/media/products/'):
        base = Path(data_dir) / 'product-images'
        file = base / path.rsplit('/', 1)[-1]
    else:
        base = Path(root)
        relative = path.lstrip('/')
        if not relative.startswith(('assets/', 'v2/', 'uploads/')):
            relative = 'v2/' + relative
        if not Path(relative).suffix:
            relative += '.jpg'
        file = base / relative
    if not file.resolve().is_relative_to(base.resolve()):
        return Paragraph('Photo unavailable', STYLE)
    try:
        with PILImage.open(file) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((500, 500))
            raw = io.BytesIO()
            image.save(raw, 'JPEG', quality=85)
            width, height = image.size
        raw.seek(0)
        scale = min(110 / width, 110 / height)
        return Image(raw, width=width * scale, height=height * scale)
    except (OSError, ValueError):
        return Paragraph('Photo unavailable', STYLE)


def export_pdf(connect, root, data_dir, include_unpublished=False):
    with connect() as db:
        rows = db.execute('SELECT p.*,i.record FROM products p JOIN inventory i USING(product_code) '
                          'WHERE p.active=1 ' + ('' if include_unpublished else 'AND p.published=1 ') +
                          'ORDER BY p.category,p.name COLLATE NOCASE').fetchall()
        products = [{**dict(r), 'details': json.loads(r['record'])} for r in rows]
    by_code = {p['product_code']: p for p in products}
    parents = [p for p in products if not p['details'].get('parentCode')]
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=36, leftMargin=36,
                            topMargin=38, bottomMargin=40, title='Kalajay Product Catalogue', author='Kalajay')
    story = [Paragraph('KALAJAY', ParagraphStyle('brand', parent=HEADING, fontSize=26, leading=32, textColor=RUST)),
             Paragraph('Handcrafted with Love, One at a Time', TITLE),
             Paragraph('Product catalogue | ' + datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %B %Y, %I:%M %p IST'), STYLE),
             Spacer(1, 8), Paragraph('Browse our handcrafted pieces for everyday moments, thoughtful gifts and special celebrations. '
                                    'For corporate gifting, bulk orders and custom colours, talk to our team at www.kalajay.in/gifting-enquiry.', STYLE),
             Spacer(1, 8), Paragraph('Prices in INR. Availability, customisation, delivery and bulk pricing are confirmed when you enquire.', STYLE)]
    category = None
    if not parents:
        story.extend([Spacer(1, 24), Paragraph('Our current collection is being updated. Please contact our team for gifting options.', STYLE)])
    for p in parents:
        d = p['details']
        if p['category'] != category:
            category = p['category']
            heading = Paragraph(escape(category), HEADING)
            heading.keepWithNext = True
            story.append(heading)
        text = [Paragraph(escape(p['name']), TITLE), Paragraph('Code: ' + escape(p['product_code']), STYLE)]
        if d.get('description'):
            text.append(Paragraph(escape(str(d['description'])).replace('\n', '<br/>'), STYLE))
        options = [by_code[v['code']] for v in d.get('variants', []) if v.get('code') in by_code]
        if not options:
            text.extend([Paragraph(('INR ' + format(p['price'], ',.2f') + ' / ' + escape(d.get('unit') or 'piece')) if p['price'] > 0 else 'Price on request', STYLE),
                         Paragraph('Made to order / enquire for availability' if p['sold_out'] else 'Available to enquire', STYLE)])
        else:
            text.append(Paragraph(str(len(options)) + ' colour / variety options below', STYLE))
        table = Table([[photo(p['image'], root, data_dir), text]], colWidths=[130, A4[0] - 202], splitInRow=1)
        table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
                                   ('TOPPADDING', (0, 0), (-1, -1), 10), ('LINEBELOW', (0, 0), (-1, -1), .5, colors.HexColor('#e7dcc2'))]))
        story.append(table)
        for child in options:
            cd = child['details']
            available = cd.get('open', 0) + cd.get('purch', 0) + cd.get('made', 0) - cd.get('sold', 0) - cd.get('dmg', 0) - cd.get('marketing', 0) + cd.get('adjustment', 0)
            detail = [Paragraph(escape(p['name'] + ' / ' + (cd.get('variantLabel') or child['name'])), TITLE),
                      Paragraph(escape(child['product_code']) + ' | ' + ('INR ' + format(child['price'], ',.2f') if child['price'] > 0 else 'Price on request'), STYLE),
                      Paragraph('Available to enquire' if available > 0 else 'Made to order / enquire for availability', STYLE)]
            story.append(Table([[photo(child['image'], root, data_dir), detail]], colWidths=[130, A4[0] - 202],
                               style=[('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 14)]))

    def footer(canvas, _doc):
        canvas.setFont('KJ', 8)
        canvas.setFillColor(RUST)
        canvas.drawString(36, 22, 'www.kalajay.in | +91 97405 40847')
        canvas.drawRightString(A4[0] - 36, 22, str(_doc.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
