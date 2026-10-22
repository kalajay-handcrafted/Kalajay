const fs=require('fs'),vm=require('vm'),assert=require('assert');
const read=p=>fs.readFileSync(p,'utf8').match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1];
class Logic{setState(x){Object.assign(this.state,typeof x==='function'?x(this.state):x)}}
const erp={DCLogic:Logic,setTimeout:()=>1,clearTimeout(){}};vm.createContext(erp);vm.runInContext(read('erp/index.html')+';this.Component=Component;',erp);
const e=new erp.Component();e.props={};e.state.loaded=true;
const item=(code,qty)=>({code,name:code,cat:'Holders',unit:'pcs',hsn:'NA',upd:'2026-10-22',open:qty,purch:0,made:0,sold:0,dmg:0,adjustment:0,reorder:0,cp:100,sp:250,mrp:300,gst:0,variants:[]});
e.state.products=[{...item('BASE',0),isVariantGroup:true,variants:[{code:'BASE-1',label:'Yellow',images:['/assets/y.jpg']},{code:'BASE-2',label:'Blue',images:['/assets/b.jpg']}]},{...item('BASE-1',5),parentCode:'BASE',variantLabel:'Yellow'},{...item('BASE-2',0),parentCode:'BASE',variantLabel:'Blue'},item('SINGLE',2)];e.state.screen='grid';const view=e.renderVals();assert.equal(view.skuCount,'3');assert.equal(view.rows.length,4);assert(!view.productOptions.some(p=>p.code==='BASE'));assert(view.editProductOptions.some(p=>p.code==='BASE'));assert.equal(view.totalValue,'₹700');e.state.entry={code:'BASE',qty:2};e.postTxn();assert.match(e.state.entryError,/individual/);
// Display masters are visible management rows; they never enter stock totals, alerts or selectors.
const master=view.rows.find(p=>p.code==='BASE');assert(master.isGroup);assert.equal(master.stockItem,false);assert.equal(master.editOptionsLabel,'Edit colours');
assert.equal(view.rowCount,'4');assert.equal(view.stockRowCount,'3');assert.equal(view.tStock,'7');assert.equal(view.tValue,'₹700');
assert(!view.lowRows.some(p=>p.code==='BASE'));
master.editOptions();assert.equal(e.state.screen,'add');assert.equal(e.state.draft.code,'BASE');
e.renderVals().addVariant();assert.equal(e.state.draft.variants.length,3);assert.equal(e.state.products[0].variants.length,2);
e.state.screen='grid';e.state.draft={};e.state.query='BASE';let filtered=e.renderVals();assert.equal(filtered.rows.length,3);assert.equal(filtered.stockRowCount,'2');assert.equal(filtered.tStock,'5');assert.equal(filtered.tValue,'₹500');
e.state.query='';e.state.stockFilter='out';assert(!e.renderVals().rows.some(p=>p.code==='BASE'));e.state.stockFilter='all';
// Even a stale nonzero master record cannot inflate figures.
e.state.products[0].open=99;e.state.products[0].sold=9;assert.equal(e.renderVals().tStock,'7');assert.equal(e.renderVals().tValue,'₹700');assert.equal(e.stock(e.state.products[0]),0);assert.equal(e.revenue(e.state.products[0]),0);
const data={collections:[['Holders','Holder','']],products:[['Holder','/assets/main.jpg','Holders','BASE']],soldOut:[],defaultPrice:250,prices:{BASE:250,'BASE-1':300,'BASE-2':350},variants:{BASE:[{code:'BASE-1',label:'Yellow',images:['/assets/y.jpg'],stock:5,soldOut:false,price:300},{code:'BASE-2',label:'Blue',images:['/assets/b.jpg'],stock:0,soldOut:true,price:350}]}};
let sent;const web={DCLogic:Logic,URLSearchParams,setTimeout:()=>1,clearTimeout(){},window:{location:{pathname:'/shop',search:'',hash:''},KALAJAY_DATA:data},fetch:async(url,args)=>{sent=JSON.parse(args.body);return {ok:true,json:async()=>({orderId:'fixture',total:300})}}};vm.createContext(web);vm.runInContext(read('index.html')+';this.Component=Component;',web);
const c=new web.Component();c.props={};c.state.active={code:'BASE',name:'Holder',cat:'Holders',price:250,soldOut:false};let v=c.renderVals();assert.equal(v.activePrice,'₹300');assert.equal(v.activeSoldOut,false);assert.match(v.activeColours[1].label,/Out of stock/);v.activeColours[1].pick();v=c.renderVals();assert.equal(v.activeSoldOut,true);v.addActive();assert.equal(Object.keys(c.state.cart).length,0);c.state.activeImage=0;c.renderVals().addActive();assert.equal(Object.values(c.state.cart)[0].variantCode,'BASE-1');
// Inline controls stay in sync across cards, chooser and cart; each colour keeps its own quantity.
assert(c.state.active, 'Chooser stays open after adding');
let controls=c.renderVals();assert.equal(controls.activeShowAdd,false);assert.equal(controls.activeQuantities[0].qty,1);
controls.activeQuantities[0].inc();assert.equal(c.renderVals().cartCount,2);
assert.equal(c.card(c.state.active).quantities[0].qty,2);
for(let i=0;i<6;i++) c.renderVals().activeQuantities[0].inc();
assert.equal(c.renderVals().activeQuantities[0].qty,5);assert.equal(c.renderVals().activeQuantities[0].atLimit,true);
for(let i=0;i<5;i++) c.renderVals().activeQuantities[0].dec();
assert.equal(c.renderVals().activeShowAdd,true);assert.equal(c.renderVals().cartCount,0);
c.bump('missing',-1);c.renderVals().addActive();
const single={code:'SINGLE',name:'Single',price:250,soldOut:false};
assert.equal(c.card(single).showAdd,true);c.card(single).add();assert.equal(c.card(single).showAdd,false);
assert.equal(c.card(single).quantities[0].qty,1);c.card(single).quantities[0].inc();assert.equal(c.card(single).quantities[0].qty,2);
c.card(single).quantities[0].dec();c.card(single).quantities[0].dec();assert.equal(c.card(single).showAdd,true);
assert.equal(c.renderVals().cartCount,1);assert.equal(c.renderVals().cartSubtotalLabel,'₹300');
c.saveOrder().then(()=>{assert.equal(sent.items[0].code,'BASE-1');assert.equal(sent.items[0].quantity,1);console.log('ERP totals, selectors and storefront variety availability, price and checkout passed.');}).catch(e=>{console.error(e);process.exitCode=1});
