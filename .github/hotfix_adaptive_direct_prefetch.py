from pathlib import Path
p=Path('v66-backend/backend/index.ts')
s=p.read_text(encoding='utf-8')

old="""type AdaptivePrefetchMarker = {
  sourceQuestionId: string;
  jobId: string;
  bankRevision: number;
  createdAt: string;
};"""
new="""type AdaptivePrefetchMarker = {
  sourceQuestionId: string;
  bankRevision: number;
  status: 'generating' | 'completed' | 'failed';
  successQuestionId?: string;
  recoveryQuestionId?: string;
  lastError?: string;
  createdAt: string;
  updatedAt: string;
};"""
if s.count(old)!=1: raise SystemExit(f'marker type count={s.count(old)}')
s=s.replace(old,new,1)

start=s.find('async function ensureAdaptivePrefetch(')
end=s.find('async function readyAdaptiveQuestion(', start)
if start<0 or end<0: raise SystemExit('ensure block not found')
ensure=r'''async function ensureAdaptivePrefetch(
  uid: string,
  passageId: string,
  revision: number,
  q: Q & { id: string },
  p: Progress
) {
  const table = adaptivePrefetchTable(uid, passageId, revision);
  try {
    const existing = await latestAdaptivePrefetchMarker(
      uid,
      passageId,
      revision,
      q.id
    );
    if (existing?.status === 'completed') return existing.id;
    if (
      existing?.status === 'generating' &&
      Date.now() - Date.parse(existing.updatedAt || existing.createdAt) < 3 * 60 * 1000
    ) return existing.id;

    const now = new Date().toISOString();
    const marker: AdaptivePrefetchMarker = {
      sourceQuestionId: q.id,
      bankRevision: revision,
      status: 'generating',
      createdAt: now,
      updatedAt: now,
    };
    const [markerId] = await db.add(table, [marker]);
    if (!markerId) return '';

    try {
      const targets = adaptiveTargetsForCurrent(q, p);
      const result = await generateAdaptivePrefetch(
        uid,
        passageId,
        revision,
        q.id,
        targets
      );
      const completed: AdaptivePrefetchMarker = {
        ...marker,
        status: 'completed',
        successQuestionId: result.successQuestionId,
        recoveryQuestionId: result.recoveryQuestionId,
        updatedAt: new Date().toISOString(),
      };
      const [saved] = await db.update(table, [{ id: markerId, record: completed }]);
      if (!saved) throw new Error('적응형 prefetch 완료 상태 저장 실패');
      return markerId;
    } catch (e) {
      const failed: AdaptivePrefetchMarker = {
        ...marker,
        status: 'failed',
        lastError: (e instanceof Error ? e.message : String(e)).slice(0, 1000),
        updatedAt: new Date().toISOString(),
      };
      try { await db.update(table, [{ id: markerId, record: failed }]); } catch {}
      console.warn('[adaptive-prefetch-generate]', {
        uid,
        passageId,
        questionId: q.id,
        message: failed.lastError,
      });
      return '';
    }
  } catch (e) {
    console.warn('[adaptive-prefetch-enqueue]', {
      uid,
      passageId,
      questionId: q.id,
      message: e instanceof Error ? e.message : String(e),
    });
    return '';
  }
}
'''
s=s[:start]+ensure+s[end:]

start=s.find('async function readyAdaptiveQuestion(')
end=s.find('function adaptiveGeneratedIssues(', start)
if start<0 or end<0: raise SystemExit('ready block not found')
ready=r'''async function readyAdaptiveQuestion(
  uid: string,
  passageId: string,
  revision: number,
  sourceQuestionId: string,
  branch: AdaptiveBranch
) {
  const marker = await latestAdaptivePrefetchMarker(
    uid,
    passageId,
    revision,
    sourceQuestionId
  );
  if (!marker || marker.status !== 'completed') return undefined;
  const id = branch === 'success'
    ? marker.successQuestionId || ''
    : marker.recoveryQuestionId || '';
  if (!id) return undefined;
  const [q] = await db.get<Q>(adaptiveQuestionTable(uid, passageId, revision), [id]);
  if (!q || q.adaptiveOwnerUid !== uid || q.qualityVersion !== QUALITY_VERSION)
    return undefined;
  return { ...q, id } as Q & { id: string };
}
'''
s=s[:start]+ready+s[end:]

# No adaptive job should be enqueued through the legacy ai-worker.
block=s[s.find('async function ensureAdaptivePrefetch('):s.find('function adaptiveGeneratedIssues(')]
if "enqueueAiJob" in block or "kind: 'adaptive-prefetch'" in block:
    raise SystemExit('legacy adaptive queue dependency remains')
if "status: 'generating'" not in block or "generateAdaptivePrefetch(" not in block:
    raise SystemExit('direct prefetch markers missing')

p.write_text(s,encoding='utf-8')
print('Switched adaptive generation to direct EdgeRuntime waitUntil prefetch')
