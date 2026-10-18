import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import backend
import shared_store as shared
import expense_store as expenses

class VarietyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.patches=[patch.object(backend,'DATA_DIR',self.directory),patch.object(backend,'DB',self.directory/'kalajay.sqlite3')]
        for item in self.patches:item.start()
        backend.initialize()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def save(self, state):
        return shared.update(backend.connect,state)
    def test_numbering_grouping_identity_and_order_snapshot(self):
        state=shared.state(backend.connect)
        product=state['products'][0];code=product['code']
        product['variants']=[{'label':'Yellow','images':['/assets/yellow.jpg']},{'label':'Blue','images':['/assets/blue.jpg']}]
        product.update(open=20,sold=0,dmg=0)
        state=self.save(state)
        product=next(p for p in state['products'] if p['code']==code)
        self.assertEqual([v['code'] for v in product['variants']],[code+'-1',code+'-2'])
        before=len(state['products'])
        product['variants'].reverse()
        product['variants'][0]['label']='Navy blue'
        product['variants'].append({'label':'Pink','images':['/assets/pink.jpg']})
        state=self.save(state)
        product=next(p for p in state['products'] if p['code']==code)
        self.assertEqual([v['code'] for v in product['variants']],[code+'-2',code+'-1',code+'-3'])
        product['variants'].pop()
        state=self.save(state)
        product=next(p for p in state['products'] if p['code']==code)
        product['variants'].append({'label':'Green','images':['/assets/green.jpg']})
        state=self.save(state)
        self.assertEqual(len(state['products']),before)
        catalogue=shared.catalog(backend.connect)
        self.assertEqual([v['code'] for v in catalogue['variants'][code]],[code+'-2',code+'-1',code+'-4'])
        # Shared inventory and one catalogue product, with validated option snapshots.
        with backend.connect() as db:db.execute('UPDATE products SET sold_out=0 WHERE product_code=?',(code,))
        data={'customer':{'name':'Fixture','phone':'9876543210','address':'Test address'},'items':[{'code':code,'quantity':3,'varieties':[{'code':code+'-2','quantity':1},{'code':code+'-1','quantity':2}]}]}
        order=shared.save_order(backend.connect,data)
        stored=next(o for o in shared.state(backend.connect)['orders'] if o['id']==order['orderId'])
        self.assertEqual(stored['items'][0]['varieties'][0]['label'],'Navy blue')
        shared.confirm(backend.connect,order['orderId'])
        self.assertEqual(next(p for p in shared.state(backend.connect)['products'] if p['code']==code)['sold'],3)
        data['items'][0]['varieties'][0]['code']='unknown-1'
        with self.assertRaises(ValueError):shared.save_order(backend.connect,data)
        backend.initialize()
        self.assertEqual(shared.catalog(backend.connect)['variants'][code][0]['code'],code+'-2')
    def test_legacy_options_and_validation(self):
        state=shared.state(backend.connect);product=state['products'][0];code=product['code']
        with backend.connect() as db:
            old={**product,'variants':[{'label':'Original','images':['/assets/old.jpg']}]}
            db.execute('UPDATE inventory SET record=? WHERE product_code=?',(json.dumps(old),code))
        state=shared.state(backend.connect)
        product=next(p for p in state['products'] if p['code']==code)
        self.assertEqual(product['variants'][0]['code'],code+'-1')
        state=self.save(state)
        product=next(p for p in state['products'] if p['code']==code)
        product['variants'][0]['code']='OTHER-1'
        with self.assertRaises(ValueError):self.save(state)
        product['variants'][0]['code']=[]
        with self.assertRaises(ValueError):self.save(state)
    def test_income_kept_separate_from_expenses(self):
        book={'version':1,'entries':[{'id':'income-fixture','type':'income','status':'paid','amount':50000,'date':'2026-10-18','description':'Fixture sale','quantity':1,'bills':[]},{'id':'expense-fixture','type':'expense','status':'paid','amount':12000,'date':'2026-10-18','description':'Fixture materials','quantity':1,'bills':[]}],'budgets':{}}
        saved=expenses.update(backend.connect,self.directory,{'revision':0,'book':book},'fixture-admin')
        self.assertEqual([e['type'] for e in saved['book']['entries']],['income','expense'])
        self.assertEqual(sum(e['amount'] if e['type']=='income' else -e['amount'] for e in saved['book']['entries']),38000)

if __name__=='__main__':unittest.main()
