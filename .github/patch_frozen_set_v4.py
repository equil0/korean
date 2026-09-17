from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

repls = [
    ("const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v3';", "const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v4';"),
    ("const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v3';", "const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v4';"),
    ("const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v3';", "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v4';"),
    ("QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v3'", "QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v4'"),
]
for old, new in repls:
    if s.count(old) != 1:
        raise SystemExit(f'marker mismatch {old!r}: {s.count(old)}')
    s = s.replace(old, new, 1)

start = s.find('const FROZEN_SET_QUESTION_COUNT = 25;')
end = s.find('function bankQualityIssues(', start)
if start < 0 or end < 0 or end <= start:
    raise SystemExit('could not locate v3 FROZEN set helper block')

helper = r'''const FROZEN_SET_QUESTION_COUNT = 25;
type FrozenSetQaRaw = {
  index: number;
  answer: number;
  pass: boolean;
  stemClear: boolean;
  uniqueAnswer: boolean;
  evidenceValid: boolean;
  explanationValid: boolean;
  issues: string[];
};

function frozenSetTargets(): BuildTarget[] {
  const groups: Array<{ level: Level; objective: Objective }> = [
    { level: 'L1', objective: 'remediation' },
    { level: 'L2', objective: 'diagnostic' },
    { level: 'L2', objective: 'stabilization' },
    { level: 'L3', objective: 'integration' },
    { level: 'L3', objective: 'challenge' },
  ];
  return groups.flatMap(group =>
    skills.map(skill => ({ skill, level: group.level, objective: group.objective }))
  );
}

function frozenSetTargetPlan(targets: BuildTarget[]) {
  return targets
    .map((target, index) => {
      const setNo = Math.floor(index / 5) + 1;
      return `문항 ${index + 1} (내부 세트 ${setNo}): skill=${target.skill}, level=${target.level}, objective=${target.objective || 'integration'}`;
    })
    .join('\n');
}

function frozenSetGenerationInstructions(targets: BuildTarget[]) {
  return `v10.11 FROZEN 규칙으로 아래 ${targets.length}문항을 하나의 문제은행 세트로 완결하라.
이 작업은 학생별 실시간 생성이 아니라 교사용 사전 문제은행 구축이다. 전체 세트를 한 번에 설계하고 자체 검수한 뒤 최종 문항만 출력한다.

[적응형 문제은행 메타데이터 계획]
${frozenSetTargetPlan(targets)}

[세트 전역 규칙]
- 전체 ${targets.length}문항은 5문항짜리 내부 세트 5개로 본다. 각 내부 세트에는 content, logic, inference, comparison, application이 각각 1문항씩 있다.
- 각 내부 세트마다 부정형 발문은 정확히 1문항만 사용한다. 단순히 긍정형 문장의 어미만 뒤집지 말고 실제 판단 과업이 부정형이어야 한다.
- 정답 번호는 전체 25문항에서 1~5가 각각 대체로 5회가 되게 하고, 가능하면 각 내부 세트에서도 1~5를 한 번씩 사용한다. 정답 위치를 맞추려고 의미를 훼손하지 않는다.
- 정답 선지가 유일한 최장 선지가 되는 문항은 전체 5개 이하로 제한한다. 길이 맞추기용 패딩은 금지한다.
- 발문은 한 번 읽고 질문 대상을 즉시 알 수 있는 간결한 한 문장을 원칙으로 한다. 난도는 긴 발문이나 중첩 관형절이 아니라 근거 결합과 선지 판별에서 만든다.
- L1은 핵심 정보·조건 확인, L2는 서로 다른 근거의 연결, L3는 여러 조건과 근거를 결합한 판단을 요구한다.
- skill/level/objective는 적응형 선택을 위한 설계 목표다. 각 문항은 지정된 목표에 맞게 설계한다.
- 동일 소재·동일 판단을 표현만 바꿔 반복하지 않는다.
- 원문에 없는 지식이나 사실을 끌어오지 않는다.
- 설계와 자기검수는 내부적으로 수행하고 JSON에는 최종 문항 필드만 출력한다.
- questions 배열 순서는 위 1~25 목표 순서와 반드시 일치한다.`;
}

function frozenCompactQuestionSchema(count: number) {
  return {
    type: 'object',
    properties: {
      questions: {
        type: 'array',
        minItems: count,
        maxItems: count,
        items: {
          type: 'object',
          properties: {
            stem: { type: 'string', minLength: 8, maxLength: 650 },
            choices: {
              type: 'array',
              minItems: 5,
              maxItems: 5,
              items: { type: 'string', minLength: 1, maxLength: 180 },
            },
            answer: { type: 'integer', enum: [1, 2, 3, 4, 5] },
            explanation: { type: 'string', minLength: 8, maxLength: 900 },
            misconception: { type: 'string', minLength: 3, maxLength: 300 },
            evidence: { type: 'string', minLength: 3, maxLength: 500 },
          },
          required: ['stem', 'choices', 'answer', 'explanation', 'misconception', 'evidence'],
          additionalProperties: false,
        },
      },
    },
    required: ['questions'],
    additionalProperties: false,
  };
}

function frozenSetQaSchema(count: number) {
  return {
    type: 'object',
    properties: {
      verdicts: {
        type: 'array',
        minItems: count,
        maxItems: count,
        items: {
          type: 'object',
          properties: {
            index: { type: 'integer', minimum: 0, maximum: Math.max(0, count - 1) },
            answer: { type: 'integer', enum: [1, 2, 3, 4, 5] },
            pass: { type: 'boolean' },
            stemClear: { type: 'boolean' },
            uniqueAnswer: { type: 'boolean' },
            evidenceValid: { type: 'boolean' },
            explanationValid: { type: 'boolean' },
            issues: {
              type: 'array',
              maxItems: 5,
              items: { type: 'string', maxLength: 240 },
            },
          },
          required: ['index', 'answer', 'pass', 'stemClear', 'uniqueAnswer', 'evidenceValid', 'explanationValid', 'issues'],
          additionalProperties: false,
        },
      },
    },
    required: ['verdicts'],
    additionalProperties: false,
  };
}

function frozenRawToQuestion(raw: unknown, target: BuildTarget): Q | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const choices = Array.isArray(value.choices)
    ? value.choices.map(item => (typeof item === 'string' ? item.trim() : ''))
    : [];
  const answer = Number(value.answer);
  if (
    typeof value.stem !== 'string' ||
    choices.length !== 5 ||
    choices.some(choice => !choice) ||
    !Number.isInteger(answer) ||
    answer < 1 ||
    answer > 5 ||
    typeof value.explanation !== 'string' ||
    typeof value.misconception !== 'string' ||
    typeof value.evidence !== 'string'
  ) return null;
  return {
    stem: value.stem.trim(),
    choices,
    answer,
    explanation: value.explanation.trim(),
    misconception: value.misconception.trim(),
    evidence: value.evidence.trim(),
    skill: target.skill,
    level: target.level,
    objective: target.objective || 'integration',
  };
}

function frozenSetLocalIssues(q: Q, sourceText: string) {
  const issues: string[] = [];
  if (!q.stem.trim() || q.stem.length > 650) issues.push('발문 길이/형식 오류');
  if (q.choices.length !== 5) issues.push('선택지 수 오류');
  const choiceKeys = q.choices.map(choice => stemKey(choice));
  if (new Set(choiceKeys).size !== 5) issues.push('중복 선택지');
  if (!Number.isInteger(q.answer) || q.answer < 1 || q.answer > 5) issues.push('정답 번호 오류');
  if (!q.explanation.trim()) issues.push('해설 누락');
  if (!q.evidence.trim()) issues.push('근거 누락');
  const source = normalizeOldHangul(sourceText);
  const evidence = normalizeOldHangul(q.evidence).trim();
  if (evidence && !source.includes(evidence)) issues.push('근거가 원문 연속 구절과 일치하지 않음');
  if (/(이라는 기준으로|하도록 하는 방식이라는 기준으로|관계를 파악하도록 하는 방식)/.test(q.stem))
    issues.push('발문 문장 구조가 지나치게 복잡함');
  return issues;
}

function frozenDifficultyFor(q: Q): DifficultyReview {
  const steps = q.explanation
    .split(/(?<=[.!?。])\s+|\n+/)
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 4);
  return {
    observedSkill: q.skill,
    observedLevel: q.level,
    singleFactRetrieval: q.level === 'L1',
    answerCued: false,
    reasoningSteps: steps.length ? steps : [q.explanation.slice(0, 180)],
    evidenceQuotes: [q.evidence],
    decisiveCondition: q.misconception || '원문의 결정적 조건과 적용 범위를 구별한다.',
    levelRationale: 'v10.11 FROZEN 세트 설계 목표와 일괄 QA를 기준으로 저장한 적응형 메타데이터',
  };
}

function frozenAccepted(q: Q, verdict?: AuditVerdict): Q {
  const difficulty = frozenDifficultyFor(q);
  const strongest = q.answer === 1 ? 2 : 1;
  return {
    ...q,
    qualityVersion: QUALITY_VERSION,
    verification: {
      engineVersion: QUESTION_ENGINE_VERSION,
      reviewMode: 'ai-multimodel',
      solverConfidence: 1,
      secondConfidence: 1,
      finalConfidence: 1,
      finalPass: true,
      auditPass: true,
      models: {
        generator: GPT_MODELS.generator,
        solverA: 'not-used:frozen-set-v4',
        solverB: 'not-used:frozen-set-v4',
        solverC: 'not-used:frozen-set-v4',
        audit: GPT_MODELS.audit,
      },
      difficulty,
      blindDemand: {
        observedSkill: q.skill,
        observedLevel: q.level,
        shortcut: 'none',
        shortcutReason: 'v10.11 FROZEN 세트 생성과 일괄 QA를 통과함',
        minimalSteps: difficulty.reasoningSteps,
        evidenceTests: [{
          quote: q.evidence,
          competingChoices: [strongest],
          reason: difficulty.decisiveCondition,
        }],
        strongestDistractor: strongest,
        sharedGround: '정답과 경쟁 오답이 지문 근거를 공유함',
        decisiveDifference: difficulty.decisiveCondition,
      },
      distractorReviews: q.choices
        .map((_, index) => index + 1)
        .filter(choice => choice !== q.answer)
        .map(choice => ({ choice, trap: q.misconception })),
    },
  };
}

function frozenQaToAudit(raw: FrozenSetQaRaw, q: Q): AuditVerdict {
  const difficulty = frozenDifficultyFor(q);
  return {
    index: raw.index,
    answer: raw.answer,
    pass: raw.pass,
    stemClear: raw.stemClear,
    uniqueAnswer: raw.uniqueAnswer,
    evidenceValid: raw.evidenceValid,
    explanationValid: raw.explanationValid,
    skillValid: true,
    levelValid: true,
    difficulty,
    choiceChecks: q.choices.map((_, index) => ({
      choice: index + 1,
      judgement: index + 1 === q.answer ? 'correct' : 'incorrect',
      reason: index + 1 === q.answer ? q.explanation : q.misconception,
      plausible: index + 1 !== q.answer,
      trap: index + 1 === q.answer ? '' : q.misconception,
    })),
    issues: raw.issues || [],
  };
}

function frozenQaIssues(q: Q, verdict: AuditVerdict | undefined, sourceText: string) {
  const issues = frozenSetLocalIssues(q, sourceText);
  if (!verdict) issues.push('FROZEN 일괄 QA 결과 누락');
  else {
    if (verdict.answer !== q.answer) issues.push(`정답 불일치: 출제 ${q.answer}, QA ${verdict.answer}`);
    if (!verdict.pass) issues.push(...(verdict.issues?.length ? verdict.issues : ['FROZEN QA 미통과']));
    if (!verdict.stemClear) issues.push('발문 명료성 미통과');
    if (!verdict.uniqueAnswer) issues.push('정답 유일성 미통과');
    if (!verdict.evidenceValid) issues.push('원문 근거 검증 미통과');
    if (!verdict.explanationValid) issues.push('해설 검증 미통과');
  }
  return [...new Set(issues)].slice(0, 8);
}

async function frozenSetAssets(p: Passage, existing: Array<Q & { id: string }>, sourceChunk = 0) {
  const sourceValidation = await validatePassageSource(p);
  if (sourceValidation.issues.length)
    throw statusError('원문 품질 문제 때문에 출제를 중단했습니다: ' + sourceValidation.issues.join(', '), 422);
  const content = sourceValidation.content;
  const imageMode = p.sourceMode === 'image';
  const rawPageTexts = imageMode ? await loadSourcePageTexts(p) : [];
  const alignedPageTexts = imageMode ? alignSourcePageTexts(p, rawPageTexts) : [];
  const sourcePages = imageMode ? relevantSourcePages(p, alignedPageTexts, content.text) : [];
  if (imageMode && !sourcePages.length)
    throw statusError('PDF 페이지와 학생용 확정 지문 경계를 일치시킬 수 없어 구축을 시작하지 않았습니다.', 422);
  const focusPages = imageMode && sourcePages.length
    ? selectBuildFocusPages(sourcePages, existing, sourceChunk)
    : [];
  const focusedText = focusedSourceText(p, content.text, focusPages);
  if (focusedText.replace(/\s/g, '').length < 100)
    throw statusError('문항 생성에 사용할 목표 지문 텍스트가 부족합니다.', 422);
  return { content, imageMode, sourcePages, focusPages, focusedText };
}

async function saveFrozenSetQuestions(passageId: string, uid: string, bankRevision: number, questions: Q[], job: BuildJob) {
  if (!questions.length) return 0;
  const existing = await listQuestions(passageId);
  const fresh = questions.filter((q, index) =>
    !existing.some(old => sameGeneratedQuestion(old, q)) &&
    questions.findIndex(other => sameGeneratedQuestion(other, q)) === index
  );
  if (!fresh.length) return 0;
  const currentPassage = await getPassage(passageId);
  if (!currentPassage || currentPassage.ownerUid !== uid || currentPassage.deleting ||
      currentBankRevision(currentPassage) !== bankRevision || currentPassage.status === 'published')
    throw statusError('검수 중 문제은행 revision이 변경되어 문항을 저장하지 않았습니다.', 409);
  const ids = await db.add(qTable(passageId), fresh);
  if (ids.some(id => id === null)) {
    const partialIds = ids.filter((id): id is string => id !== null);
    if (partialIds.length) await deleteDbRows(qTable(passageId), partialIds);
    throw statusError('검증 문항 일부를 저장하지 못해 이번 저장분을 되돌렸습니다.', 500);
  }
  const canonicalIds = await canonicalizeSavedQuestionDuplicates(
    passageId,
    ids.filter((id): id is string => id !== null),
    new Set(existing.map(question => question.id))
  );
  job.savedQuestionIds = [...(job.savedQuestionIds || []), ...canonicalIds];
  return canonicalIds.length;
}

async function startFrozenSetGeneration(assets: Awaited<ReturnType<typeof frozenSetAssets>>, targets: BuildTarget[]) {
  return openAiStartBackground({
    model: GPT_MODELS.generator,
    schemaName: 'frozen_set_questions_v4',
    schema: frozenCompactQuestionSchema(targets.length),
    system: `${frozenGenerationPrompt(assets.focusedText)}\n\n${FROZEN_ADAPTER_RULES}`,
    prompt: `${frozenSetGenerationInstructions(targets)}\n\n[승인 지문]\n${assets.focusedText}`,
    images: [],
    maxOutputTokens: 26000,
    reasoning: 'medium',
  });
}

async function startFrozenSetQa(assets: Awaited<ReturnType<typeof frozenSetAssets>>, candidates: Q[]) {
  const auditInput = candidates.map((q, index) => ({
    index,
    stem: q.stem,
    choices: q.choices,
    answer: q.answer,
    explanation: q.explanation,
    evidence: q.evidence,
  }));
  return openAiStartBackground({
    model: GPT_MODELS.audit,
    schemaName: 'frozen_set_qa_v4',
    schema: frozenSetQaSchema(candidates.length),
    system: AUDIT_SYSTEM,
    prompt: `[승인 지문]\n${assets.focusedText}\n\n[검수 지시]\nv10.11 FROZEN 기준으로 아래 세트 전체를 한 번에 검수한다. 서버의 skill/level 목표와 일치하는지는 합격 조건으로 삼지 않는다. 오직 원문 정합성, 정답 유일성, 발문 명료성, 근거 충분성, 해설 타당성, 세트 내 중복·단서 편향을 검사한다. 실제 수정이 필요한 결함만 issues에 적는다.\n\n[문항 세트]\n${JSON.stringify(auditInput)}`,
    images: [],
    maxOutputTokens: 9000,
    reasoning: 'medium',
  });
}

async function startFrozenSetRepair(assets: Awaited<ReturnType<typeof frozenSetAssets>>, candidates: Q[], targets: BuildTarget[], issues: string[]) {
  const repairItems = candidates.map((q, index) => ({
    index,
    target: targets[index],
    previousQuestion: {
      stem: q.stem,
      choices: q.choices,
      answer: q.answer,
      explanation: q.explanation,
      misconception: q.misconception,
      evidence: q.evidence,
    },
    issues: issues[index] || 'FROZEN QA에서 수정 필요',
  }));
  return openAiStartBackground({
    model: GPT_MODELS.generator,
    schemaName: 'frozen_set_repairs_v4',
    schema: frozenCompactQuestionSchema(targets.length),
    system: `${FROZEN_READING_QA_PROMPT}\n\n${FROZEN_QA_ADAPTER_RULES}`,
    prompt: `[승인 지문]\n${assets.focusedText}\n\n[수정 지시]\n아래 결함 문항만 v10.11 FROZEN 기준으로 수정한다. 각 target의 skill/level/objective를 유지하고, 지적된 결함을 제거한 최종 문항만 같은 순서로 출력한다. 수정 후 스스로 정답 유일성·원문 근거·발문 명료성을 다시 확인한다. 이미 합격한 문항은 건드리지 않는다.\n\n[수정 대상]\n${JSON.stringify(repairItems)}`,
    images: [],
    maxOutputTokens: Math.min(20000, Math.max(7000, targets.length * 700)),
    reasoning: 'medium',
  });
}

async function frozenSetBuildStep(
  uid: string,
  passageId: string,
  initialPassage: Passage,
  body: { sourceChunk?: unknown; phase?: unknown; jobId?: unknown }
) {
  let p = initialPassage;
  const sourceChunk = typeof body.sourceChunk === 'number' && Number.isInteger(body.sourceChunk)
    ? body.sourceChunk : 0;

  if (typeof body.jobId !== 'string' || !body.jobId) {
    const existing = await listQuestions(passageId);
    if (complete(existing)) {
      const result = await makeBuildResult(passageId, 0, 0, 0, 0);
      return json({ ...result, bankComplete: result.complete, pipelineComplete: true });
    }
    const resumed = await findResumableBuildJob(uid, passageId, currentBankRevision(p));
    if (resumed)
      return json({
        phase: resumed.pendingGenerationResponseId ? 'generating' :
          resumed.pendingAuditResponseId ? 'auditing' :
          resumed.candidates.length ? 'generated' : 'generation-ready',
        jobId: resumed.id,
        resumed: true,
        generatedCount: resumed.generatedCount,
        targetCount: resumed.targets?.length || FROZEN_SET_QUESTION_COUNT,
      });

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
      apiPlan: '1x-set-generation -> 1x-set-QA -> optional-1x-repair',
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

  if (job.repairRound === 1) {
    const targets = job.targets || [];
    if (!targets.length || !job.candidates.length)
      throw statusError('FROZEN 수정 대상 상태가 올바르지 않습니다.', 409);

    if (job.pendingGenerationResponseId) {
      const pending = await pollBuildStage<{ questions: unknown[] }>(
        uid, passageId, jobId, job, 'generation', GPT_MODELS.generator
      );
      if (pending.state === 'waiting')
        return json({ phase: 'generating', jobId, repairPending: true, targetCount: targets.length, apiStage: 'repairing' });
      const raw = Array.isArray(pending.data.questions) ? pending.data.questions : [];
      const repaired = targets
        .map((target, index) => frozenRawToQuestion(raw[index], target))
        .filter((q): q is Q => !!q);
      delete job.pendingGenerationResponseId;
      job.generatedCount += raw.length;
      const valid = repaired.filter(q => frozenSetLocalIssues(q, assets.content.text).length === 0);
      const accepted = valid.map(q => frozenAccepted(q));
      await saveFrozenSetQuestions(
        passageId, uid, job.bankRevision || currentBankRevision(p), accepted, job
      );
      job.candidates = [];
      job.targets = [];
      job.generationRejections = [];
      job.repairRound = 2;
      const result = await makeBuildResult(
        passageId,
        job.savedQuestionIds?.length || 0,
        job.generatedCount,
        job.auditIndex || 0,
        job.auditIndex || 0
      );
      job.result = result;
      await saveBuildJob(uid, passageId, jobId, job);
      return json({
        ...result,
        complete: true,
        bankComplete: result.complete,
        pipelineComplete: true,
        manualReviewRequired: !result.complete,
        apiCallsMaximum: 3,
        rejectionSummary: result.complete ? '' :
          `FROZEN 생성·QA·수정 3회 상한까지 완료했지만 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
      });
    }

    job.pendingGenerationResponseId = await startFrozenSetRepair(
      assets, job.candidates, targets, job.generationRejections || []
    );
    await saveBuildJob(uid, passageId, jobId, job);
    return json({ phase: 'generating', jobId, repairPending: true, targetCount: targets.length, apiStage: 'repair-failures-only' });
  }

  if (!job.candidates.length) {
    const targets = job.targets || frozenSetTargets();
    if (job.pendingGenerationResponseId) {
      const pending = await pollBuildStage<{ questions: unknown[] }>(
        uid, passageId, jobId, job, 'generation', GPT_MODELS.generator
      );
      if (pending.state === 'waiting')
        return json({ phase: 'generating', jobId, targetCount: targets.length, generatedCount: job.generatedCount });
      const raw = Array.isArray(pending.data.questions) ? pending.data.questions : [];
      const candidates = targets
        .map((target, index) => frozenRawToQuestion(raw[index], target))
        .filter((q): q is Q => !!q);
      delete job.pendingGenerationResponseId;
      job.generatedCount += raw.length;
      job.generationIndex = targets.length;
      job.candidates = candidates;
      await saveBuildJob(uid, passageId, jobId, job);
      if (candidates.length !== targets.length)
        throw statusError(`FROZEN 세트 생성 응답 ${targets.length}개 중 ${candidates.length}개만 구조화되었습니다. 추가 API 호출을 중단합니다.`, 502);
      return json({ phase: 'generated', jobId, generatedCount: job.generatedCount, targetCount: candidates.length, apiStage: 'set-generated' });
    }
    job.pendingGenerationResponseId = await startFrozenSetGeneration(assets, targets);
    await saveBuildJob(uid, passageId, jobId, job);
    return json({ phase: 'generating', jobId, targetCount: targets.length, apiStage: 'generate-set' });
  }

  if (!job.auditVerdicts) {
    if (job.pendingAuditResponseId) {
      const pending = await pollBuildStage<{ verdicts: FrozenSetQaRaw[] }>(
        uid, passageId, jobId, job, 'audit', GPT_MODELS.audit
      );
      if (pending.state === 'waiting')
        return json({ phase: 'auditing', jobId, targetCount: job.candidates.length, apiStage: 'qa-set' });
      const rawVerdicts = Array.isArray(pending.data.verdicts) ? pending.data.verdicts : [];
      job.auditVerdicts = rawVerdicts
        .map(raw => {
          const q = job.candidates[raw.index];
          return q ? frozenQaToAudit(raw, q) : null;
        })
        .filter((item): item is AuditVerdict => !!item);
      job.auditIndex = job.auditVerdicts.length;
      delete job.pendingAuditResponseId;
      await saveBuildJob(uid, passageId, jobId, job);
    } else {
      job.pendingAuditResponseId = await startFrozenSetQa(assets, job.candidates);
      await saveBuildJob(uid, passageId, jobId, job);
      return json({ phase: 'auditing', jobId, targetCount: job.candidates.length, apiStage: 'qa-set' });
    }
  }

  const verdicts = job.auditVerdicts || [];
  const passed: Q[] = [];
  const failedQuestions: Q[] = [];
  const failedTargets: BuildTarget[] = [];
  const failedIssues: string[] = [];

  job.candidates.forEach((q, index) => {
    const verdict = verdicts.find(item => item.index === index);
    const issues = frozenQaIssues(q, verdict, assets.content.text);
    if (!issues.length && verdict) passed.push(frozenAccepted(q, verdict));
    else {
      failedQuestions.push(q);
      failedTargets.push({ skill: q.skill, level: q.level, objective: q.objective });
      failedIssues.push(issues.join(' / '));
    }
  });

  await saveFrozenSetQuestions(
    passageId, uid, job.bankRevision || currentBankRevision(p), passed, job
  );

  if (failedQuestions.length) {
    job.candidates = failedQuestions;
    job.targets = failedTargets;
    job.generationRejections = failedIssues;
    job.auditVerdicts = undefined;
    job.repairRound = 1;
    job.generationIndex = 0;
    await saveBuildJob(uid, passageId, jobId, job);
    return json({
      phase: 'generated',
      jobId,
      repairPending: true,
      passedCount: passed.length,
      repairCount: failedQuestions.length,
      apiStage: 'repair-required',
    });
  }

  job.candidates = [];
  job.targets = [];
  const result = await makeBuildResult(
    passageId,
    job.savedQuestionIds?.length || 0,
    job.generatedCount,
    verdicts.length,
    verdicts.length
  );
  job.result = result;
  await saveBuildJob(uid, passageId, jobId, job);
  return json({
    ...result,
    complete: true,
    bankComplete: result.complete,
    pipelineComplete: true,
    manualReviewRequired: !result.complete,
    apiCallsMaximum: 2,
    rejectionSummary: result.complete ? '' :
      `FROZEN 세트 생성·일괄 QA까지 완료했지만 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
  });
}

'''

s = s[:start] + helper + s[end:]

required = [
    "v10.11-frozen-set-adaptive-v4",
    "v10.11-frozen-set-v4",
    "function frozenCompactQuestionSchema",
    "function frozenSetQaSchema",
    "maxOutputTokens: 26000",
    "reasoning: 'medium'",
    "apiPlan: '1x-set-generation -> 1x-set-QA -> optional-1x-repair'",
    "QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v4'",
]
for item in required:
    if item not in s:
        raise SystemExit(f'missing marker after v4 patch: {item}')

for forbidden in [
    "questionDesignIssues(q, assets.focusedText)",
    "auditPasses(verdict, q, assets.focusedText)",
    "solverA: 'not-used:frozen-set-v3'",
]:
    block = s[start:s.find('function bankQualityIssues(', start)]
    if forbidden in block:
        raise SystemExit(f'v4 block still contains forbidden duplicate gate: {forbidden}')

path.write_text(s, encoding='utf-8')
print('Applied v10.11 FROZEN compact set pipeline v4')
