# Blind spot-check workbook: 30 audit items, AI labels hidden on a separate sheet.
import csv, random, re
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

def blocks(path):
    out = {}
    for b in open(path).read().split('######## ')[1:]:
        head, body = b.split('\n', 1)
        q, _, resp = body.partition('\n---\n')
        out[head.split(' |')[0].strip()] = (q.removeprefix('Q: ').strip(), resp.strip())
    return out

A = list(csv.DictReader(open('audit_labels_a.csv')))
B = list(csv.DictReader(open('audit_labels_b.csv')))
txt = {**blocks('blind_dump_a.txt'), **blocks('blind_dump_b.txt')}
rng = random.Random(1024)
pick = [r for r in A if r['label'] != 'GENUINE']
pick += rng.sample([r for r in A if r['label'] == 'GENUINE'], 20 - len(pick))
pick += rng.sample(B, 10)
rng.shuffle(pick)

def ai_credit(r):
    return {'GENUINE': 'Y', 'CREDIT': 'Y', 'COINCIDENTAL': 'N', 'NO_CREDIT': 'N'}.get(r['label'], '?')

wb = Workbook(); ws = wb.active; ws.title = 'Spot-check'
hdr = ['#', 'Question', 'Gold answer', 'Model response', 'YOUR CALL: credit? (Y / N / ?)', 'Your note']
ws.append(hdr)
key = wb.create_sheet('AI labels (open after)')
key.append(['#', 'audit_id', 'AI label', 'AI credit', 'AI rationale', 'v1', 'v2', 'gt', 'v2 rule'])
for i, r in enumerate(pick, 1):
    q, resp = txt[r['audit_id']]
    ws.append([i, q, r['gold'], resp, '', ''])
    key.append([i, r['audit_id'], r['label'], ai_credit(r), r['rationale'], r['v1'], r['v2'], r['gt'], r['v2_rule']])
for col, w in zip('ABCDEF', [4, 45, 10, 90, 14, 30]):
    ws.column_dimensions[col].width = w
for row in ws.iter_rows():
    for c in row: c.alignment = Alignment(wrap_text=True, vertical='top')
for c in ws[1]: c.font = Font(bold=True, name='Arial')
ws.freeze_panes = 'B2'
wb.save('spot-check.xlsx')
print(len(pick), sum(ai_credit(r) == 'N' for r in pick))
