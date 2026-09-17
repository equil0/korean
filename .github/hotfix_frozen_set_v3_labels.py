from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')
old = """          phase: 'solving-a',
          jobId,
          targetCount: job.candidates.length,
          apiStage: 'qa-set',
"""
count = s.count(old)
if count != 2:
    raise SystemExit(f'expected 2 FROZEN QA phase blocks, got {count}')
s = s.replace(old, """          phase: 'auditing',
          jobId,
          targetCount: job.candidates.length,
          apiStage: 'qa-set',
""")
path.write_text(s, encoding='utf-8')
print('Updated FROZEN set QA progress label to auditing')
