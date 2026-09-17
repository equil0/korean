from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

helper_start = s.index('function frozenBankGenerationPlan(')
bank_start = s.index('function bankQualityIssues(', helper_start)
segment = s[helper_start:bank_start]
old = 'const negativeCount = usable.filter(q => negativeStem(q.stem)).length;'
if segment.count(old) != 1:
    raise SystemExit(f'expected one helper negativeStem reference, got {segment.count(old)}')
new = "const negativeCount = usable.filter(q => /(?:적절하지|옳지|타당하지|일치하지|아닌 것은|않은 것은|없는 것은|부적절)/.test(q.stem)).length;"
segment = segment.replace(old, new, 1)
s = s[:helper_start] + segment + s[bank_start:]
path.write_text(s, encoding='utf-8')

check = path.read_text(encoding='utf-8')
helper_segment = check[check.index('function frozenBankGenerationPlan('):check.index('function bankQualityIssues(')]
if 'negativeStem(' in helper_segment:
    raise SystemExit('helper still references negativeStem')
if 'v10.11-frozen-adapter-v2' not in check:
    raise SystemExit('v2 engine marker missing')
print('FROZEN negative-stem helper hotfix applied')
