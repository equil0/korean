from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')
old = """    const resumed = await findResumableBuildJob(uid, passageId, currentBankRevision(p));
    if (resumed)
      return json({
"""
new = """    const resumed = await findResumableBuildJob(uid, passageId, currentBankRevision(p));
    if (resumed && resumed.engineVersion === QUESTION_ENGINE_VERSION)
      return json({
"""
if s.count(old) != 1:
    raise SystemExit(f'v4 resume marker count={s.count(old)}')
s = s.replace(old, new, 1)
needle = """        targetCount: resumed.targets?.length || FROZEN_SET_QUESTION_COUNT,
      });

    if (p.status === 'published') p = await invalidatePassageBank(passageId, p);
"""
replacement = """        targetCount: resumed.targets?.length || FROZEN_SET_QUESTION_COUNT,
      });
    if (resumed && resumed.engineVersion !== QUESTION_ENGINE_VERSION)
      await clearBuildJobs(uid, passageId);

    if (p.status === 'published') p = await invalidatePassageBank(passageId, p);
"""
if s.count(needle) != 1:
    raise SystemExit(f'v4 stale cleanup marker count={s.count(needle)}')
s = s.replace(needle, replacement, 1)
path.write_text(s, encoding='utf-8')
print('Added v4 stale build resume guard')
