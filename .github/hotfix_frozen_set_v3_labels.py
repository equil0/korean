from pathlib import Path
import re

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')
pattern = r"phase: 'solving-a',(?=\s*\n\s*jobId,\s*\n\s*targetCount: job\.candidates\.length,\s*\n\s*apiStage: 'qa-set',)"
s2, count = re.subn(pattern, "phase: 'auditing',", s)
if count != 2:
    raise SystemExit(f'expected 2 FROZEN QA phase markers, got {count}')
path.write_text(s2, encoding='utf-8')
print('Updated 2 FROZEN set QA progress labels to auditing')
