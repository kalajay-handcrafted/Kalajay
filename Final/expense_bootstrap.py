"""One-time private transfer of the existing local expense app's register."""
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
import expense_import
import expense_store
from expense_library_transfer import LibraryFileMaterializer, LibraryFileTransfer

def run(connect, data_dir):
    encoded = os.environ.get('KALAJAY_EXPENSE_LIBRARY_TRANSFER', '').strip()
    current = expense_store.state(connect)
    if encoded:
        transfer = json.loads(encoded)
        key = transfer['file_id']
        if key not in current['book'].get('libraryImports', []):
            # Use the current Library transfer helper to preserve source identity.
            with tempfile.TemporaryDirectory(dir=data_dir) as temp:
                destination = (Path(temp)/'expense-book.zip').resolve()
                LibraryFileMaterializer().materialize(LibraryFileTransfer.parse(transfer), destination)
                with zipfile.ZipFile(destination) as archive:
                    if sum(i.file_size for i in archive.infolist()) > 25000000:
                        raise ValueError('Expense package is too large.')
                    names = [n for n in archive.namelist() if n.endswith('/index.html')]
                    if len(names) != 1:
                        raise ValueError('Expense package has no unique app source.')
                    html = archive.read(names[0]).decode('utf-8')
                match = re.search(r'const IMPORTED_ENTRIES=(.*?);\s*function mergeImported', html, re.S)
                if not match:
                    raise ValueError('Expense package does not contain the imported register.')
                entries = json.loads(match[1])
                merged, count = expense_import.merge(current['book'], entries)
                merged['libraryImports'] = current['book'].get('libraryImports', []) + [key]
                current = expense_store.update(connect, data_dir, {'revision':current['revision'],'book':merged}, 'expense-import')
                print('Expense import completed: '+str(count)+' new entries.', flush=True)
    entries = current['book']['entries']
    total = sum(e['amount'] for e in entries if e['type']=='expense')
    print('Expense book ready: '+str(len(entries))+' entries; expense_total_paise='+str(total), flush=True)
