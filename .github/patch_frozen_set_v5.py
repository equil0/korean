from pathlib import Path
import re

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

repls = [
    ("const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v4';", "const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v5';"),
    ("const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v4';", "const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v5';"),
    ("const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v4';", "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v5';"),
    ("schemaName: 'frozen_set_questions_v4',", "schemaName: 'frozen_set_questions_v5',"),
    ("QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v4'", "QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v5'"),
]
for old, new in repls:
    if s.count(old) != 1:
        raise SystemExit(f'marker mismatch {old!r}: {s.count(old)}')
    s = s.replace(old, new, 1)

# Do not let legacy quality versions suppress a freshly generated current-version item.
old = """    const matches = all.filter(
      question =>
        questionFingerprint(question) === fingerprint
    );"""
new = """    const matches = all.filter(
      question =>
        question.qualityVersion === saved.qualityVersion &&
        questionFingerprint(question) === fingerprint
    );"""
if s.count(old) != 1:
    raise SystemExit(f'canonical duplicate marker count={s.count(old)}')
s = s.replace(old, new, 1)

start = s.find('async function frozenSetBuildStep(')
end = s.find('function bankQualityIssues(', start)
if start < 0 or end < 0 or end <= start:
    raise SystemExit('could not locate frozenSetBuildStep block')

one_shot = r'''async function frozenSetBuildStep(
  uid: string,
  passageId: string,
  initialPassage: Passage,
  body: {
    sourceChunk?: unknown;
    phase?: unknown;
    jobId?: unknown;
  }
) {
  let p = initialPassage;
  const sourceChunk =
    typeof body.sourceChunk === 'number' && Number.isInteger(body.sourceChunk)
      ? body.sourceChunk
      : 0;

  if (typeof body.jobId !== 'string' || !body.jobId) {
    const existing = await listQuestions(passageId);
    if (complete(existing)) {
      const result = await makeBuildResult(passageId, 0, 0, 0, 0);
      return json({
        ...result,
        complete: true,
        bankComplete: true,
        pipelineComplete: true,
        apiCallsMaximum: 0,
      });
    }

    const resumed = await findResumableBuildJob(
      uid,
      passageId,
      currentBankRevision(p)
    );
    if (resumed && resumed.engineVersion === QUESTION_ENGINE_VERSION)
      return json({
        phase: resumed.pendingGenerationResponseId ? 'generating' : 'generation-ready',
        jobId: resumed.id,
        resumed: true,
        generatedCount: resumed.generatedCount,
        targetCount: resumed.targets?.length || FROZEN_SET_QUESTION_COUNT,
        apiPlan: 'one-call-frozen-set',
      });
    if (resumed) await clearBuildJobs(uid, passageId);

    if (p.status === 'published') p = await invalidatePassageBank(passageId, p);
    await frozenSetAssets(p, existing, sourceChunk);
    await clearBuildJobs(uid, passageId);
    const targets = frozenSetTargets();
    const job: BuildJob = {
      passageId,
      bankRevision: currentBankRevision(p),
      sourceChunk,
      focusPageNumbers: [],
      engineVersion: QUESTION_ENGINE_VERSION,
      trial: false,
      auditIndex: 0,
      candidates: [],
      generatedCount: 0,
      targets,
      generationIndex: 0,
      generationRetryCount: 0,
      repairRound: 0,
      createdAt: new Date().toISOString(),
    };
    const [jobId] = await db.add(buildJobTable(uid, passageId), [job]);
    if (!jobId) return error('FROZEN 세트 구축 작업을 만들지 못했습니다.', 500);
    return json({
      phase: 'generation-ready',
      jobId,
      targetCount: targets.length,
      apiPlan: 'one-call-frozen-set',
    });
  }

  const jobId = body.jobId;
  const job = await loadBuildJob(uid, passageId, jobId);
  if (job.engineVersion !== QUESTION_ENGINE_VERSION)
    return error('이전 출제 엔진 작업입니다. 새 자동 구축을 시작해 주세요.', 409);
  if (job.bankRevision !== currentBankRevision(p))
    return error('문제은행 revision이 변경되었습니다. 새 구축을 시작해 주세요.', 409);

  const existing = await listQuestions(passageId);
  const assets = await frozenSetAssets(p, existing, job.sourceChunk || sourceChunk);
  const targets = job.targets || frozenSetTargets();

  if (!job.pendingGenerationResponseId) {
    job.pendingGenerationResponseId = await startFrozenSetGeneration(assets, targets);
    await saveBuildJob(uid, passageId, jobId, job);
    return json({
      phase: 'generating',
      jobId,
      targetCount: targets.length,
      apiStage: 'frozen-generate-self-review',
      apiCallsMaximum: 1,
    });
  }

  const pending = await pollBuildStage<{ questions: unknown[] }>(
    uid,
    passageId,
    jobId,
    job,
    'generation',
    GPT_MODELS.generator
  );
  if (pending.state === 'waiting')
    return json({
      phase: 'generating',
      jobId,
      targetCount: targets.length,
      generatedCount: job.generatedCount,
      apiStage: 'frozen-generate-self-review',
      apiCallsMaximum: 1,
    });

  const raw = Array.isArray(pending.data.questions)
    ? pending.data.questions
    : [];
  const candidates = targets
    .map((target, index) => frozenRawToQuestion(raw[index], target))
    .filter((q): q is Q => !!q);
  delete job.pendingGenerationResponseId;
  job.generatedCount += raw.length;
  job.generationIndex = targets.length;

  // FROZEN already performs design, QA and revision internally.  The server only
  // rejects malformed transport objects here; it does not run another subjective
  // difficulty/skill audit over the same questions.
  const accepted = candidates
    .filter(q => {
      if (!q.stem.trim()) return false;
      if (q.choices.length !== 5) return false;
      if (new Set(q.choices.map(choice => stemKey(choice))).size !== 5) return false;
      if (!Number.isInteger(q.answer) || q.answer < 1 || q.answer > 5) return false;
      if (!q.explanation.trim()) return false;
      return true;
    })
    .map(q => frozenAccepted(q));

  await saveFrozenSetQuestions(
    passageId,
    uid,
    job.bankRevision || currentBankRevision(p),
    accepted,
    job
  );

  job.candidates = [];
  job.targets = [];
  job.auditVerdicts = undefined;
  job.generationRejections = [];
  job.repairRound = 0;

  const result = await makeBuildResult(
    passageId,
    job.savedQuestionIds?.length || 0,
    job.generatedCount,
    accepted.length,
    0
  );
  job.result = result;
  await saveBuildJob(uid, passageId, jobId, job);

  const structuralRejected = Math.max(0, candidates.length - accepted.length);
  return json({
    ...result,
    // `complete` here stops the async worker after the single authorized model call.
    // `bankComplete` is the actual publication readiness flag.
    complete: true,
    bankComplete: result.complete,
    pipelineComplete: true,
    manualReviewRequired: !result.complete,
    apiCallsMaximum: 1,
    structuralRejected,
    rejectionSummary: result.complete
      ? ''
      : `FROZEN 1회 세트 생성은 끝났지만 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
  });
}

'''
s = s[:start] + one_shot + s[end:]

required = [
    "v10.11-frozen-set-adaptive-v5",
    "v10.11-frozen-set-v5",
    "apiPlan: 'one-call-frozen-set'",
    "apiStage: 'frozen-generate-self-review'",
    "apiCallsMaximum: 1",
    "question.qualityVersion === saved.qualityVersion",
]
for item in required:
    if item not in s:
        raise SystemExit(f'missing v5 marker: {item}')

# Auto-build v5 must not invoke the separate QA/repair helpers.
block = s[start:s.find('function bankQualityIssues(', start)]
for forbidden in ['startFrozenSetQa(', 'startFrozenSetRepairBackground(']:
    if forbidden in block:
        raise SystemExit(f'forbidden extra API stage still in v5 build step: {forbidden}')

path.write_text(s, encoding='utf-8')
print('Applied one-call FROZEN set pipeline v5')
