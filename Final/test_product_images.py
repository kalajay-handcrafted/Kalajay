import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from PIL import Image
import backend
import product_images
import shared_store

def photo(kind='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (32, 24), 'gold').save(output, format=kind)
    return output.getvalue()

class ProductImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.patches = [patch.object(backend, 'DATA_DIR', cls.directory),
                       patch.object(backend, 'DB', cls.directory/'kalajay.sqlite3')]
        for item in cls.patches: item.start()
        backend.initialize()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), backend.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = 'http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        for item in reversed(cls.patches): item.stop()
        cls.temp.cleanup()
    def request(self, path, data=None, origin=True, mime='image/png'):
        headers = {'Content-Type':mime}
        if origin: headers['Origin'] = self.origin if origin is True else origin
        try:
            response = urlopen(Request(self.origin+path, data=data, headers=headers))
        except HTTPError as error:
            response = error
        return response.status, response.read(), response.headers
    def test_upload_save_shared_reference_and_public_image(self):
        with patch.object(backend.auth, 'current', return_value={'role':'admin'}):
            status, raw, _ = self.request('/api/erp/product-image', photo())
            self.assertEqual(status, 201)
            image = json.loads(raw)['image']
            state = shared_store.state(backend.connect)
            code = state['products'][0]['code']
            state['products'][0]['image'] = image
            status, raw, _ = self.request('/api/erp', json.dumps(state).encode(), mime='application/json')
            self.assertEqual(status, 200, raw)
            self.assertEqual(json.loads(raw)['products'][0]['image'], image)
            status, page, _ = self.request('/erp/')
            self.assertEqual(status, 200)
            self.assertIn(b'uploadProductImage', page)
        catalogue = shared_store.catalog(backend.connect)
        self.assertEqual(next(p[1] for p in catalogue['products'] if p[3] == code), image)
        with backend.connect() as db:
            self.assertEqual(db.execute('SELECT image FROM products WHERE product_code=?',(code,)).fetchone()[0], image)
        # A server initialization must keep the uploaded photo and database references.
        backend.initialize()
        self.assertEqual(next(p['image'] for p in shared_store.state(backend.connect)['products'] if p['code']==code), image)
        status, raw, headers = self.request(image)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/webp')
        with Image.open(io.BytesIO(raw)) as decoded:
            self.assertEqual(decoded.size, (32,24))
        self.assertEqual(self.request('/media/products/../../kalajay.sqlite3')[0],404)
    def test_permissions_and_origin(self):
        for user, origin, expected in [(None,True,401),({'role':'manager'},True,403),
                                      ({'role':'admin'},False,403),({'role':'admin'},'https://other.test',403)]:
            with patch.object(backend.auth, 'current', return_value=user):
                self.assertEqual(self.request('/api/erp/product-image',photo(),origin)[0],expected)
    def test_image_validation_and_immutable_files(self):
        for kind in ('JPEG','PNG','WEBP'):
            image = product_images.save(self.directory, photo(kind))['image']
            self.assertTrue(product_images.read(self.directory,image.rsplit('/',1)[1]))
        with self.assertRaises(ValueError): product_images.save(self.directory,b'<svg/>')
        with self.assertRaises(ValueError): product_images.save(self.directory,b'\x89PNG\r\n\x1a\ninvalid')
        with self.assertRaises(ValueError): product_images.save(self.directory,b'x'*(product_images.MAX_BYTES+1))
        with patch.object(product_images,'MAX_PIXELS',10):
            with self.assertRaises(ValueError): product_images.save(self.directory,photo())
        with patch.object(backend.auth, 'current', return_value={'role':'admin'}):
            self.assertEqual(self.request('/api/erp/product-image',b'<html>bad</html>')[0],400)
            self.assertEqual(self.request('/api/erp/product-image',photo(),mime='text/html')[0],415)
        self.assertFalse(list((self.directory/'product-images').glob('tmp*')))

if __name__ == '__main__': unittest.main()
