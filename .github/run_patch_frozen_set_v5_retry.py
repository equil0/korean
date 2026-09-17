from pathlib import Path

patch_path = Path('.github/patch_frozen_set_v5.py')
code = patch_path.read_text(encoding='utf-8')
start = code.index('# Do not let legacy quality versions suppress')
end = code.index("start = s.find('async function frozenSetBuildStep(')", start)
code = code[:start] + code[end:]
code = code.replace('    "question.qualityVersion === saved.qualityVersion",\n', '')
exec(compile(code, str(patch_path), 'exec'))
