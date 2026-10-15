import base64
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from xml.sax.saxutils import escape
import expense_store as expenses
import expense_import

def sample(key='one', amount=12550):
    return {'id':key,'date':'2026-09-30','type':'expense','status':'recorded',
            'amount':amount,'description':'Test material','category':'Raw Material',
            'quantity':1,'unitPrice':amount,'party':'','method':'Not recorded',
            'notes':'','bills':[]}

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'private').mkdir()
        self.path = self.root/'private/kalajay.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE products (code TEXT PRIMARY KEY)')
            db.execute("INSERT INTO products VALUES ('unchanged')")
        expenses.initialize(self.connect, self.root/'private')
    def tearDown(self):
        self.temp.cleanup()
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db
    def save(self, book, revision=0):
        return expenses.update(self.connect,self.root/'private',{'revision':revision,'book':book},'test-admin')
    def test_migration_backup_and_existing_table(self):
        self.assertTrue((self.root/'private/before-expenses.sqlite3').exists())
        expenses.initialize(self.connect,self.root/'private')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT code FROM products').fetchone()[0],'unchanged')
        self.assertEqual(expenses.state(self.connect)['revision'],0)
    def test_update_conflict_does_not_overwrite(self):
        book={'version':1,'entries':[sample()],'budgets':{}}
        self.save(book)
        with self.assertRaises(expenses.Conflict):
            self.save({**book,'entries':[sample(amount=99)]})
        current=expenses.state(self.connect)
        self.assertEqual(current['revision'],1)
        self.assertEqual(current['book']['entries'][0]['amount'],12550)
    def test_zero_amount_and_duplicate_rejection(self):
        self.save({'version':1,'entries':[sample(amount=0)],'budgets':{}})
        with self.assertRaises(ValueError):
            self.save({'version':1,'entries':[sample(),sample()],'budgets':{}},1)
        self.assertEqual(expenses.state(self.connect)['book']['entries'][0]['amount'],0)
    def test_private_bill_backup_and_traversal(self):
        entry=sample()
        entry['bills']=[{'name':'receipt.pdf','data':'data:application/pdf;base64,'+base64.b64encode(b'%PDF-1.4\nfixture').decode()}]
        current=self.save({'version':1,'entries':[entry],'budgets':{}})
        bill=current['book']['entries'][0]['bills'][0]
        self.assertNotIn('data',bill)
        raw,mime=expenses.bill(self.connect,self.root/'private',bill['id'])
        self.assertEqual(mime,'application/pdf')
        self.assertTrue(raw.startswith(b'%PDF-'))
        backup=expenses.backup(self.connect,self.root/'private')
        self.assertIn('data',backup['entries'][0]['bills'][0])
        with self.assertRaises(ValueError):
            expenses.bill(self.connect,self.root,'../../kalajay.sqlite3')
        with self.assertRaises(ValueError):
            expenses.bill(self.connect,self.root,'a'*64+'.pdf')
        broken={**entry,'bills':[{'name':'bad.pdf','data':'data:application/pdf;base64,YWJj'}]}
        with self.assertRaises(ValueError):
            self.save({'version':1,'entries':[broken],'budgets':{}},1)
    def test_xlsx_blank_and_original_dates_idempotence(self):
        headers=['Source ID','Transaction Date','Description','Expense Group','Expense Subcategory','Frequency (Original)','Accounting Treatment','Quantity','Unit Price (INR)','Amount (INR)','Original Notes']
        rows=[headers,[1,None,'Fixture','Raw Material','Beads','Recurring','Inventory / Materials Review',2,95,190,'clear original comment'],[2,'2025-05-31','Fixture zero','Office','Miscellaneous','One-Time','Asset / Setup Review',1,None,0,None]]
        body=''
        for n,row in enumerate(rows,1):
            cells=''
            for index,value in enumerate(row):
                if value is None: continue
                address=chr(65+index)+str(n)
                if isinstance(value,(float,int)):
                    cells+='<c r="'+address+'"><v>'+str(value)+'</v></c>'
                else:
                    cells+='<c r="'+address+'" t="inlineStr"><is><t>'+escape(value)+'</t></is></c>'
            body+='<row r="'+str(n)+'">'+cells+'</row>'
        output=BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            archive.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Expense Register" sheetId="1" r:id="rId1"/></sheets></workbook>')
            archive.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            archive.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+body+'</sheetData></worksheet>')
        entries=expense_import.read_workbook(output.getvalue())
        self.assertEqual(entries[0]['date'],'2026-09-30')
        self.assertTrue(entries[0]['dateAssumed'])
        self.assertEqual(entries[0]['notes'],'')
        self.assertEqual(entries[0]['amount'],19000)
        self.assertEqual(entries[1]['date'],'2025-05-31')
        self.assertEqual(entries[1]['amount'],0)
        self.assertEqual(entries[1]['treatment'],'Asset/Set Up')
        book={'version':1,'entries':[],'budgets':{}}
        merged,count=expense_import.merge(book,entries)
        self.assertEqual(count,2)
        self.assertEqual(expense_import.merge(merged,entries)[1],0)
        self.save(merged)

    def test_private_initial_import_is_idempotent(self):
        import expense_bootstrap
        payload={'file_id':'fixture-source','download_url':'https://example.invalid/file.zip','library_file_id':'fixture-library','xattrs':[]}
        def materialize(_self, transfer, destination):
            with zipfile.ZipFile(destination,'w') as archive:
                archive.writestr('Kalajay-Expenses/index.html','const IMPORTED_ENTRIES='+json.dumps([sample()])+';\nfunction mergeImported(){}')
        with patch.dict('os.environ',{'KALAJAY_EXPENSE_LIBRARY_TRANSFER':json.dumps(payload)}):
            with patch.object(expense_bootstrap.LibraryFileMaterializer,'materialize',materialize):
                expense_bootstrap.run(self.connect,self.root/'private')
            # The next startup must work without downloading an expired URL.
            with patch.object(expense_bootstrap.LibraryFileMaterializer,'materialize',side_effect=AssertionError('Repeated transfer')):
                expense_bootstrap.run(self.connect,self.root/'private')
        current=expenses.state(self.connect)
        self.assertEqual(len(current['book']['entries']),1)
        self.assertEqual(current['revision'],1)

class AuthorizationTests(StoreTests):
    def test_http_guards_and_database_writes(self):
        import backend
        cookie_user=lambda connect,cookie: {'username':'fixture','role':cookie} if cookie in ('admin','manager') else None
        class QuietHandler(backend.Handler):
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        with patch.object(backend,'connect',self.connect),patch.object(backend,'ROOT',self.root),patch.object(backend,'DATA_DIR',self.root/'private'),patch.object(backend,'PRODUCTION',False),patch.object(backend.auth,'current',cookie_user):
            thread.start()
            host='127.0.0.1:'+str(server.server_port)
            base='http://'+host
            def code(path,role=None,data=None,origin=None):
                headers={}
                if role:headers['Cookie']=role
                if origin:headers['Origin']=origin
                if data is not None:headers['Content-Type']='application/json'
                req=Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
                try:
                    with urlopen(req) as response:return response.status
                except HTTPError as error:return error.code
            request={'revision':0,'book':{'version':1,'entries':[sample()],'budgets':{}}}
            try:
                self.assertEqual(code('/api/erp/expenses'),401)
                self.assertEqual(code('/api/erp/expenses','manager'),200)
                self.assertEqual(code('/api/erp/expenses','manager',request,base),403)
                self.assertEqual(code('/api/erp/expenses','admin',request,'https://untrusted.example'),403)
                self.assertEqual(code('/api/erp/expenses','admin',request,base),200)
                self.assertEqual(code('/api/erp/expenses','admin',request,base),409)
                self.assertEqual(code('/api/erp/expenses/bills/nope','manager'),404)
            finally:
                server.shutdown()
                thread.join()
        server.server_close()

if __name__=='__main__':
    unittest.main()
