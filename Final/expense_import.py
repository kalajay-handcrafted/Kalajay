"""Read the supplied Expense Register workbook without adding dependencies."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import PurePosixPath
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'

def money(value):
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if not amount.is_finite() or amount < 0:
            raise ValueError('Amounts must be nonnegative.')
        return int(amount * 100)
    except (InvalidOperation, OverflowError):
        raise ValueError('Invalid amount in register.')

def read_workbook(raw):
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
        if len(archive.infolist()) > 1000 or sum(i.file_size for i in archive.infolist()) > 20000000:
            raise ValueError('Workbook is too large.')
        def xml(path):
            data = archive.read(path)
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
                raise ValueError('Unsupported workbook XML.')
            return ET.fromstring(data)
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(t.text or '' for t in n.findall('.//s:t', NS))
                       for n in xml('xl/sharedStrings.xml').findall('s:si', NS)]
        relationships = {n.attrib['Id']: n.attrib['Target'] for n in xml('xl/_rels/workbook.xml.rels')}
        workbook = xml('xl/workbook.xml')
        epoch = datetime(1904, 1, 1) if workbook.find('s:workbookPr', NS) is not None and workbook.find('s:workbookPr', NS).get('date1904') in ('1', 'true') else datetime(1899, 12, 30)
        sheets = {}
        for sheet in workbook.findall('s:sheets/s:sheet', NS):
            if sheet.get('name') not in ('Expense Register', 'Review Queue'):
                continue
            target = relationships[sheet.attrib[REL]]
            path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            if '..' in PurePosixPath(path).parts:
                raise ValueError('Invalid workbook path.')
            rows = []
            for row in xml(path).findall('s:sheetData/s:row', NS):
                values = {}
                for cell in row.findall('s:c', NS):
                    column = re.sub('[0-9]', '', cell.attrib['r'])
                    node = cell.find('s:v', NS)
                    value = node.text if node is not None else None
                    if cell.get('t') == 's' and value is not None:
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                    values[column] = value
                rows.append(values)
            sheets[sheet.attrib['name']] = rows
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, TypeError):
        raise ValueError('Select the original Expense Tracker XLSX workbook.')
    rows = sheets.get('Expense Register', [])
    if not rows:
        raise ValueError('Workbook must have an Expense Register sheet.')
    headers = {value: column for column, value in rows[0].items()}
    required = ('Source ID', 'Transaction Date', 'Description', 'Expense Group',
                'Expense Subcategory', 'Frequency (Original)', 'Accounting Treatment',
                'Quantity', 'Unit Price (INR)', 'Amount (INR)')
    if any(key not in headers for key in required):
        raise ValueError('Expense Register columns do not match the supplied workbook.')
    bad = set()
    for row in sheets.get('Review Queue', [])[1:]:
        if 'Originally marked Bad Investment' in (row.get('E') or ''):
            bad.add(str(row.get('A', '')))
    result = []
    seen = set()
    for index, row in enumerate(rows[1:], 2):
        value = lambda key: row.get(headers[key])
        if not value('Description'):
            continue
        source = str(value('Source ID') or index)
        if source in seen:
            raise ValueError('Duplicate source ID in workbook.')
        seen.add(source)
        original_date = value('Transaction Date')
        assumed = not original_date
        if assumed:
            date = '2026-09-30'
        else:
            try:
                date = (epoch + timedelta(days=float(original_date))).date().isoformat()
            except (ValueError, OverflowError):
                date = None
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d %H:%M:%S'):
                    try:
                        date = datetime.strptime(original_date, fmt).date().isoformat()
                        break
                    except ValueError:
                        pass
                if not date:
                    raise ValueError('Unrecognized date on row ' + str(index))
        treatment = value('Accounting Treatment') or 'Others'
        treatment = re.sub(r'Asset\s*/\s*Set\s*up\s+Review', 'Asset/Set Up', treatment, flags=re.I)
        treatment = re.sub(r'Inventory\s*/\s*Materials?\s+Review', 'Inventory/Material', treatment, flags=re.I)
        try:
            quantity = float(value('Quantity') or 1)
        except ValueError:
            raise ValueError('Invalid quantity on row ' + str(index))
        result.append({
            'id': 'xlsx-expense-register-' + source, 'sourceId': source,
            'sourceRow': index, 'date': date, 'dateAssumed': assumed,
            'description': value('Description'), 'category': value('Expense Group') or 'Others',
            'group': value('Expense Group') or 'Others',
            'subcategory': value('Expense Subcategory') or 'Others',
            'frequency': value('Frequency (Original)') or 'Others',
            'treatment': treatment, 'quantity': quantity,
            'unitPrice': money(value('Unit Price (INR)')) if value('Unit Price (INR)') is not None else None,
            'amount': money(value('Amount (INR)')), 'type': 'expense',
            'status': 'recorded', 'method': 'Not recorded', 'party': '', 'paidBy': '',
            'notes': '', 'reviewReason': '', 'reviewNote': '',
            'badInvestment': source in bad, 'bills': [],
        })
    if not result:
        raise ValueError('No transactions found in the register.')
    return result

def source_options(entries):
    return {key: sorted({str(e.get(key, '')) for e in entries if e.get(key)})
            for key in ('category', 'subcategory', 'frequency', 'treatment')}

def merge(book, entries):
    ids = {e['id'] for e in book['entries']}
    fresh = [e for e in entries if e['id'] not in ids]
    options = book.get('sourceOptions') or source_options(entries)
    return {**book, 'entries': book['entries'] + fresh, 'sourceOptions': options}, len(fresh)
