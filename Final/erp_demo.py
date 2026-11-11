"""Fictional Manager records, generated independently of the live ERP database."""

import base64
from datetime import datetime, timedelta
from functools import lru_cache
from io import BytesIO
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.platypus import Image as PDFImage

import catalogue_excel
import catalogue_pdf
import inventory_costing
import shared_store


PRODUCT_IMAGE = '/erp/demo/product.png'
TEAM_IMAGE = '/api/erp/team/images/demo-member-01/demo-photo.png'
BILL_ID = 'demo-receipt.pdf'
BILL_URL = '/api/erp/expenses/bills/' + BILL_ID
PLACEHOLDER_PHONE = '+91 00000 00000'


def day(days_ago=0):
    return (datetime.now(ZoneInfo('Asia/Kolkata')).date() - timedelta(days=days_ago)).isoformat()


def products():
    def stock_item(code, name, category, price, **fields):
        product = shared_store.record(code, name, category)
        product.update(image=PRODUCT_IMAGE, upd=day(), sp=price, mrp=price + 100,
                       hsn='7117', gst=3, reorder=3, beadsUsed='Sample acrylic beads',
                       beadKg=0.25, beadCostKg=320, laborHours=2, otherMaterialCost=20,
                       notes='Fictional costing example.', **fields)
        return inventory_costing.normalize(product)

    parent = shared_store.record('DEMO-BAG-001', 'Sample Beaded Tote', 'Bags')
    parent.update(image=PRODUCT_IMAGE, upd=day(), isVariantGroup=True, variantSequence=2,
                  variants=[{'code': 'DEMO-BAG-001-1', 'label': 'Sky Blue', 'images': [PRODUCT_IMAGE]},
                            {'code': 'DEMO-BAG-001-2', 'label': 'Soft Peach', 'images': [PRODUCT_IMAGE]}])
    blue = stock_item('DEMO-BAG-001-1', 'Sample Beaded Tote / Sky Blue', 'Bags', 900,
                      parentCode=parent['code'], variantLabel='Sky Blue', open=6, purch=3,
                      made=8, sold=4, dmg=1, marketing=1, adjustment=-1)
    peach = stock_item('DEMO-BAG-001-2', 'Sample Beaded Tote / Soft Peach', 'Bags', 950,
                       parentCode=parent['code'], variantLabel='Soft Peach', open=2, sold=2)
    coaster = stock_item('DEMO-MAT-002', 'Sample Beaded Coaster', 'Coasters & Mats', 350,
                         open=4, sold=2)
    return [dict(product, sno=index) for index, product in enumerate([parent, blue, peach, coaster], 1)]


def inventory():
    catalogue = products()
    _, blue, peach, coaster = catalogue
    movements = [
        ('Adjustment', blue, -1, 'Sample stock count', 0),
        ('Damage', blue, 1, 'Sample damaged piece', blue['cp']),
        ('Marketing', blue, 1, 'Sample creator', 0),
        ('Sale', blue, 2, 'DEMO-ORDER-001', blue['sp']),
        ('Sale', blue, 2, 'Sample in-person sale', blue['sp']),
        ('Sale', peach, 2, 'Sample in-person sale', peach['sp']),
        ('Sale', coaster, 2, 'Sample in-person sale', coaster['sp']),
        ('Purchase', blue, 3, 'DEMO-PO-001', 180),
        ('Production', blue, 8, 'Sample workshop batch', blue['cp']),
    ]
    txns = []
    for index, (kind, product, quantity, reference, rate) in enumerate(movements, 1):
        txn = dict(id=f'demo-movement-{index}', type=kind, code=product['code'],
                   qty=quantity, ref=reference, rate=rate, date=day((index - 1) // 2))
        if kind == 'Marketing':
            txn.update(purpose='UGC', unitCost=product['cp'])
        txns.append(txn)

    def order(index, product, quantity, status):
        return dict(id=f'DEMO-ORDER-{index:03}', date=day(index - 1), status=status,
                    customer=dict(name=f'Sample Customer {index}', phone=PLACEHOLDER_PHONE,
                                  address='Sample Lane, Example City'),
                    items=[dict(product_code=product['code'], name_snapshot=product['name'],
                                quantity=quantity, unit_price=product['sp'], varieties=[])],
                    total=quantity * product['sp'], note='Example order for the Manager demo.')

    return dict(products=catalogue, txns=txns, revision=0, browserImported=False,
                orders=[order(2, coaster, 1, 'new'), order(1, blue, 2, 'confirmed')])


def expense_state():
    receipt = dict(id=BILL_ID, name='Demo-Receipt.pdf', mime='application/pdf', url=BILL_URL)
    entries = [
        dict(id='demo-expense-01', serial=1, code='DEMO-EXP-001', type='expense', date=day(),
             description='Sample bead supplies', category='Materials', subcategory='Beads',
             quantity=3, unitPrice=20000, amount=60000, party='Sample Supplies Co.',
             paidBy='Demo Finance', method='UPI', status='paid', treatment='Inventory',
             frequency='One-time', badInvestment=False, bills=[receipt], notes='Sample paid bill.'),
        dict(id='demo-expense-02', serial=2, code='DEMO-EXP-002', type='expense', date=day(),
             description='Sample packaging quote', category='Packaging', subcategory='Boxes',
             quantity=2, unitPrice=14000, amount=28000, party='Sample Supplies Co.',
             paidBy='', method='Not recorded', status='pending', treatment='Review',
             frequency='One-time', badInvestment=False, bills=[], notes='Example awaiting review.'),
        dict(id='demo-income-01', serial=3, code='DEMO-INC-003', type='income', date=day(),
             description='Sample order payment', amount=180000, party='Sample Customer 1',
             paidBy='Demo Finance', method='Bank Transfer', status='paid', frequency='One-time',
             bills=[], notes='Example of income received.'),
    ]
    vendors = [dict(id='demo-vendor-01', name='Sample Supplies Co.', gst='DEMO-GST-001',
                    contact=PLACEHOLDER_PHONE, email='vendor@example.invalid',
                    contracts='Sample supply agreement for demonstration.', knownSince='2025-01')]
    options = dict(category=['Materials', 'Packaging'], subcategory=['Beads', 'Boxes'],
                   treatment=['Inventory', 'Review'], frequency=['One-time'])
    return dict(revision=0, book=dict(version=1, entries=entries, vendors=vendors,
                                     budgets={'Materials': 150000, 'Packaging': 50000},
                                     sourceOptions=options, entrySequence=len(entries)))


def expense_backup():
    book = expense_state()['book']
    book['entries'][0]['bills'][0]['data'] = 'data:application/pdf;base64,' + base64.b64encode(receipt()).decode('ascii')
    return book


def team():
    member = dict(id='demo-member-01', name='Sample Maker', member_code='DEMO-MEM-001',
                  capacity='Production artisan', membership_type='Employee', phone=PLACEHOLDER_PHONE,
                  email='maker@example.invalid', joined_on='2025-01-06', date_of_birth='1990-01-01',
                  address='Sample Lane, Example City', emergency_name='Sample Emergency Contact',
                  emergency_phone=PLACEHOLDER_PHONE, active=True, existing_member=False,
                  notes='Fictional directory entry with a sample attachment.',
                  images=[dict(id='demo-photo.png', name='Sample profile attachment', url=TEAM_IMAGE)])
    return dict(count=1, baseline=0, unregistered=0, members=[member])


@lru_cache(maxsize=2)
def image(label):
    output = BytesIO()
    image = Image.new('RGB', (300, 220), '#f8efdf')
    drawing = ImageDraw.Draw(image)
    drawing.rounded_rectangle((12, 12, 288, 208), radius=18, outline='#9e5430', width=3)
    drawing.text((150, 110), label, fill='#40291c', anchor='mm', font_size=22)
    image.save(output, format='PNG')
    return output.getvalue()


@lru_cache(maxsize=1)
def receipt():
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(440, 260), invariant=True)
    pdf.setTitle('Demo receipt')
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(35, 218, 'Demo receipt - fictional example')
    pdf.setFont('Helvetica', 12)
    pdf.drawString(35, 180, 'Sample Supplies Co. | DEMO-EXP-001')
    pdf.drawString(35, 155, 'Sample bead supplies: 3 x INR 200.00')
    pdf.drawString(35, 130, 'Total INR 600.00 | Paid by UPI')
    pdf.save()
    return output.getvalue()


def export_pdf():
    rows = [dict(product_code=p['code'], name=p['name'], category=p['cat'], price=p['sp'],
                 image=PRODUCT_IMAGE, sold_out=shared_store.stock(p) <= 0, details=p)
            for p in products()]
    def photo_for(_path):
        return PDFImage(BytesIO(image('Sample product')), width=110, height=81)
    return catalogue_pdf.render_pdf(rows, photo_for, demo=True)


def export_excel():
    rows = [[p['code'], p['name'], p['cat'], shared_store.stock(p), None, p['sp'], None]
            for p in products() if not p.get('isVariantGroup')]
    return catalogue_excel.render_workbook(dict(rows=rows, revision=0), demo=True)
