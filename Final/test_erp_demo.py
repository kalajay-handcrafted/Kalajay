import base64
from http.cookiejar import CookieJar
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from openpyxl import load_workbook

import backend
import erp_demo


class DemoAccessTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.object(backend, 'DATA_DIR', root))
        self.enterContext(patch.object(backend, 'DB', root / 'kalajay.sqlite3'))
        self.enterContext(patch.object(backend, 'PRODUCTION', False))
        backend.initialize()
        live = backend.shared.state(backend.connect)
        live['products'] = [dict(backend.shared.record('TEST-LIVE', 'Live-only fixture', 'Bags'), open=10, sp=450)]
        backend.shared.update(backend.connect, live)
        with backend.connect() as db:
            db.execute("UPDATE products SET published=1 WHERE product_code='TEST-LIVE'")
        order = backend.shared.save_order(backend.connect, {
            'customer': {'name': 'Live-only fixture', 'phone': '0000000000', 'address': 'Example Street'},
            'items': [{'code': 'TEST-LIVE', 'quantity': 1}],
        })
        backend.shared.confirm(backend.connect, order['orderId'])
        self.live_order_id = order['orderId']
        backend.team.cities(backend.connect, {'count': 55})
        backend.team.add(backend.connect, {
            'id': 'e0646dda-6d2a-4f09-afbf-889e0ee41b77', 'name': 'Live-only fixture',
            'capacity': 'Production', 'member_code': 'TEST-LIVE', 'active': True, 'existing_member': False,
        })
        expense_state = backend.expenses.state(backend.connect)
        expense_state['book']['entries'] = [{
            'id': 'test-live', 'date': '2025-01-01', 'description': 'Live-only fixture', 'type': 'expense',
            'status': 'paid', 'amount': 654321, 'bills': [{
                'name': 'Live-only fixture.pdf',
                'data': 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-1.4\nLive-only fixture').decode(),
            }],
        }]
        saved = backend.expenses.update(backend.connect, root, expense_state, 'test-fixture')
        self.live_bill = saved['book']['entries'][0]['bills'][0]['url']
        self.live_product_image = backend.product_images.save(root, erp_demo.image('Live-only fixture'))['image']

        server = self.enterContext(backend.ThreadingHTTPServer(('127.0.0.1', 0), backend.Handler))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.origin = f'http://127.0.0.1:{server.server_port}'
        self.public, self.admin, self.manager = self.client(), self.client(), self.client()
        password = 'fixture-only-erp-demo'
        for role in ('admin', 'manager'):
            backend.auth.create(backend.connect, {'username': role, 'password': password, 'role': role})
        for role, send in [('admin', self.admin), ('manager', self.manager)]:
            self.assertEqual(send('/api/auth/login', {'username': role, 'password': password})[0], 200)

    def client(self):
        opener = build_opener(HTTPCookieProcessor(CookieJar()))

        def send(path, data=None):
            request = Request(self.origin + path, data=None if data is None else json.dumps(data).encode(),
                              headers={'Origin': self.origin, 'Content-Type': 'application/json',
                                       'X-ERP-Confirmed': 'yes'})
            try:
                with opener.open(request, timeout=5) as response:
                    return response.status, response.read(), response.headers
            except HTTPError as error:
                return error.code, error.read(), error.headers

        return send

    def test_demo_reads_are_separate_from_live_data(self):
        for path in ('/api/erp', '/api/erp/expenses', '/api/erp/team', '/api/erp/expenses/backup'):
            with self.subTest(path=path):
                status, sample, headers = self.manager(path + '?scope=live')
                self.assertEqual(status, 200)
                self.assertIn(b'Sample', sample)
                self.assertNotIn(b'Live-only fixture', sample)
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertIn(b'Live-only fixture', self.admin(path)[1])
                self.assertEqual(self.public(path)[0], 401)
        self.assertEqual(json.loads(self.manager('/api/erp/cities')[1]), {'count': 1})
        self.assertEqual(json.loads(self.admin('/api/erp/cities')[1]), {'count': 55})
        demo_stock = json.loads(self.manager('/api/erp')[1])
        self.assertTrue(all(row['id'].startswith('DEMO-ORDER-') for row in demo_stock['orders']))
        self.assertTrue(all(row['id'].startswith('demo-movement-') for row in demo_stock['txns']))
        self.assertIn(self.live_order_id.encode(), self.admin('/api/erp')[1])
        self.assertNotIn(b'GSTIN', self.manager('/erp/')[1])
        self.assertIn(b'GSTIN', self.admin('/erp/')[1])
        for path in ('/erp/', '/erp/expenses', '/erp/team', '/erp/support.js', '/erp/auth.js'):
            self.assertEqual(self.manager(path)[0], 200, path)

    def test_demo_downloads_and_upload_guards(self):
        for path in (self.live_bill, '/api/erp/team/images/live-team/live-photo.png'):
            self.assertEqual(self.manager(path)[0], 404)
        self.assertEqual(self.admin(self.live_bill)[1], b'%PDF-1.4\nLive-only fixture')
        self.assertEqual(self.public(self.live_bill)[0], 401)
        for path in ('/api/catalogue', '/api/catalogue.js', '/api/catalogue.pdf', self.live_product_image,
                     '/uploads/live.pdf', '/erp/uploads/live.pdf', '/erp/assets/live.png',
                     '/assets/story-team-event.jpg', '/api/erp/records', '/api/erp/history', '/api/auth/users'):
            self.assertEqual(self.manager(path)[0], 403, path)
        self.assertIn(b'Live-only fixture', self.public('/api/catalogue')[1])
        self.assertEqual(self.public(self.live_product_image)[0], 200)
        for path in (erp_demo.TEAM_IMAGE, erp_demo.PRODUCT_IMAGE):
            self.assertTrue(self.manager(path)[1].startswith(b'\x89PNG'))
            self.assertFalse(self.public(path)[1].startswith(b'\x89PNG'))
        self.assertEqual(self.manager(erp_demo.BILL_URL)[1], erp_demo.receipt())
        status, raw, headers = self.manager('/api/erp/catalogue.pdf')
        self.assertEqual(status, 200)
        self.assertTrue(raw.startswith(b'%PDF-'))
        self.assertIn(b'Kalajay Demo Catalogue', raw)
        self.assertIn('Demo', headers['Content-Disposition'])
        for client, expected in [(self.manager, 'DEMO-BAG-001-1'), (self.admin, 'TEST-LIVE')]:
            status, raw, _ = client('/api/catalogue.xlsx')
            self.assertEqual(status, 200)
            with BytesIO(raw) as stream:
                workbook = load_workbook(stream, read_only=True)
                try:
                    self.assertEqual(workbook['Catalogue']['A8'].value, expected)
                finally:
                    workbook.close()

    def test_demo_role_cannot_write(self):
        for path in ('/api/erp', '/api/erp/confirm', '/api/erp/expenses', '/api/erp/team',
                     '/api/erp/cities', '/api/erp/record-action', '/api/auth/users', '/api/auth/setup',
                     '/api/catalogue/import-preview', '/api/catalogue/import', '/api/orders'):
            self.assertEqual(self.manager(path, {})[0], 403, path)
        self.assertEqual(self.manager('/api/auth/logout', {})[0], 200)
        self.assertEqual(self.manager('/api/erp')[0], 401)
