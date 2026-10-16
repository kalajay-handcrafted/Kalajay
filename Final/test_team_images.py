import base64
import json
import sqlite3
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import team_store as team
import team_images

PIXEL = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfWQAAAAASUVORK5CYII=')

class TeamImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.path = self.directory/'kalajay.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE shared_meta (key TEXT PRIMARY KEY,value INTEGER)')
        team.initialize(self.connect)
        team_images.initialize(self.connect,self.directory)
        self.member_id = str(uuid.uuid4())
    def tearDown(self):
        self.temp.cleanup()
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db
    def data(self, **updates):
        return dict(id=self.member_id, name='Fixture Employee',capacity='Artisan',
                    member_code='FIXTURE-001',active=True,existing_member=False,
                    joined_on='',images=[],image_ids=[],**updates)
    def payload(self, raw=PIXEL):
        return {'name':'photo.png','data':'data:image/png;base64,'+base64.b64encode(raw).decode()}
    def save(self, data):
        return team.add(self.connect,data,self.directory)
    def test_additive_migration_and_counts_unchanged(self):
        self.assertTrue((self.directory/'before-team-images.sqlite3').exists())
        before=team.state(self.connect)['count']
        team_images.initialize(self.connect,self.directory)
        self.assertEqual(team.state(self.connect)['count'],before)
        data=self.data()
        data['images']=[self.payload()]
        first=self.save(data)
        self.assertEqual(first['count'],before+1)
        images=first['members'][0]['images']
        data['images']=images
        data['image_ids']=[x['id'] for x in images]
        updated=self.save(data)
        self.assertEqual(updated['count'],first['count'])
        self.assertEqual(updated['unregistered'],first['unregistered'])
    def test_disk_storage_read_reference_and_legacy_edit(self):
        data=self.data()
        data['images']=[self.payload()]
        result=self.save(data)
        image=result['members'][0]['images'][0]
        self.assertNotIn('data',image)
        self.assertTrue(image['url'].startswith('/api/erp/team/images/'))
        self.assertEqual(team_images.read(self.connect,self.directory,self.member_id,image['id']),(PIXEL,'image/png'))
        with self.connect() as db:
            details=db.execute('SELECT details FROM team_members WHERE id=?',(self.member_id,)).fetchone()[0]
        self.assertNotIn('base64',details)
        self.assertNotIn('images',json.loads(details))
        legacy=self.data()
        del legacy['images']
        del legacy['image_ids']
        legacy['notes']='An existing client can still edit fields.'
        changed=self.save(legacy)
        self.assertEqual(changed['members'][0]['images'][0]['id'],image['id'])
    def test_remove_and_reject_cross_member_reference(self):
        data=self.data()
        data['images']=[self.payload()]
        image=self.save(data)['members'][0]['images'][0]
        other=self.data()
        other.update(id=str(uuid.uuid4()),member_code='FIXTURE-002',images=[image])
        with self.assertRaises(ValueError):
            self.save(other)
        with self.assertRaises(ValueError):
            team_images.read(self.connect,self.directory,other['id'],image['id'])
        data['images']=[]
        data['image_ids']=[image['id']]
        self.assertEqual(self.save(data)['members'][0]['images'],[])
        with self.assertRaises(ValueError):
            team_images.read(self.connect,self.directory,self.member_id,image['id'])
        with self.assertRaises(ValueError):
            team_images.read(self.connect,self.directory,self.member_id,'../../kalajay.sqlite3')
    def test_validation_rolls_back_member_and_metadata(self):
        bad=self.data()
        bad['images']=[{'name':'bad.svg','data':'data:image/svg+xml;base64,PHN2Zz4='}]
        with self.assertRaises(ValueError):
            self.save(bad)
        self.assertEqual(team.state(self.connect)['members'],[])
        bad['images']=[self.payload() for _ in range(4)]
        with self.assertRaises(ValueError):
            self.save(bad)
        bad['images']=[self.payload(),self.payload()]
        with self.assertRaises(ValueError):
            self.save(bad)
        self.assertEqual(team.state(self.connect)['members'],[])
        self.assertEqual(list((self.directory/'team-images').iterdir()),[])
        bad['images']=[self.payload(b'not a png')]
        with self.assertRaises(ValueError):
            self.save(bad)
        bad['images']=[self.payload(b'\x89PNG\r\n\x1a\n'+b'a'*1000000)]
        with self.assertRaises(ValueError):
            self.save(bad)
    def test_stale_image_list_cannot_overwrite_new_attachment(self):
        data=self.data()
        data['images']=[self.payload()]
        saved=self.save(data)
        stale=self.data()
        stale['name']='Stale replacement'
        with self.assertRaises(ValueError):
            self.save(stale)
        current=team.state(self.connect)['members'][0]
        self.assertEqual(current['name'],'Fixture Employee')
        self.assertEqual(current['images'],saved['members'][0]['images'])
    def test_http_authorization_and_image_roundtrip(self):
        import backend
        class QuietHandler(backend.Handler):
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        user=lambda connect,cookie: {'username':'fixture','role':cookie} if cookie in ('admin','manager') else None
        with patch.object(backend,'connect',self.connect),patch.object(backend,'DATA_DIR',self.directory),patch.object(backend,'PRODUCTION',False),patch.object(backend.auth,'current',user):
            thread.start()
            origin='http://127.0.0.1:'+str(server.server_port)
            def request(path,role=None,data=None,request_origin=None):
                headers={}
                if role: headers['Cookie']=role
                if data is not None:
                    headers['Content-Type']='application/json'
                    headers['Origin']=request_origin or origin
                req=Request(origin+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
                try:
                    with urlopen(req) as response:
                        return response.status,response.read(),response.headers.get_content_type()
                except HTTPError as error:
                    return error.code,error.read(),error.headers.get_content_type()
            try:
                payload=self.data()
                payload['images']=[self.payload(PIXEL+b'\x00'*40000)]
                self.assertGreater(len(json.dumps(payload)),32768)
                self.assertEqual(request('/api/erp/team',data=payload)[0],401)
                self.assertEqual(request('/api/erp/team','manager',payload)[0],403)
                self.assertEqual(request('/api/erp/team','admin',payload,'https://untrusted.invalid')[0],403)
                code,body,_=request('/api/erp/team','admin',payload)
                self.assertEqual(code,200,body)
                image=json.loads(body)['members'][0]['images'][0]
                self.assertEqual(request(image['url'])[0],401)
                code,raw,mime=request(image['url'],'manager')
                self.assertEqual(code,200)
                self.assertEqual(raw,PIXEL+b'\x00'*40000)
                self.assertEqual(mime,'image/png')
                self.assertEqual(request('/api/erp/team/images/not/a-valid-image','admin')[0],404)
            finally:
                server.shutdown()
                thread.join()
        server.server_close()

if __name__=='__main__':
    unittest.main()
