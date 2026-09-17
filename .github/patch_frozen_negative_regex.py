from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')
old = "const negativeStem = (stem: string) => /적절하지|옳지|않은|아닌|추론할 수 없는|뒷받침되지 않는|알 수 없는/.test(stem.split(/\\n\\s*<보기>|\\n\\s*〈보기〉/)[0]);"
new = "const negativeStem = (stem: string) => /적절하지|옳지|타당하지|부합하지|일치하지|맞지|않은|않는|아닌|틀린|잘못된|추론할 수 없는|뒷받침되지 않는|알 수 없는/.test(stem.split(/\\n\\s*<보기>|\\n\\s*〈보기〉/)[0]);"
if s.count(old) != 1:
    raise SystemExit(f'negativeStem marker count={s.count(old)}')
s = s.replace(old, new, 1)
path.write_text(s, encoding='utf-8')
print('Patched negative-stem classifier')
