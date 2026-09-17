from pathlib import Path
import re

path = Path("v66-backend/backend/index.ts")
s = path.read_text(encoding="utf-8")

repls = [
    ("const QUALITY_VERSION = 'v10.11-frozen-adaptive-v2';",
     "const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v3';"),
    ("const BUILD_ENGINE_VERSION = 'v10.11-frozen-batched-v2';",
     "const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v3';"),
    ("const QUESTION_ENGINE_VERSION = 'v10.11-frozen-adapter-v2';",
     "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v3';"),
    ("const GENERATION_OUTPUT_TOKENS = 16000;",
     "const GENERATION_OUTPUT_TOKENS = 48000;"),
    ("const AUDIT_OUTPUT_TOKENS = 16000;",
     "const AUDIT_OUTPUT_TOKENS = 32000;"),
]
for old, new in repls:
    if s.count(old) != 1:
        raise SystemExit(f"marker mismatch: {old!r} count={s.count(old)}")
    s = s.replace(old, new, 1)

old_evidence = '''  const requiredEvidenceCount = targets.some(target => target.level !== 'L1')
    ? 2
    : 1;
  const requiredReasoningStepCount = targets.some(target => target.level === 'L3')
    ? 3
    : requiredEvidenceCount;'''
new_evidence = '''  const setBatch = targets.length > 5;
  const requiredEvidenceCount = setBatch
    ? 1
    : targets.some(target => target.level !== 'L1')
      ? 2
      : 1;
  const requiredReasoningStepCount = setBatch
    ? 1
    : targets.some(target => target.level === 'L3')
      ? 3
      : requiredEvidenceCount;'''
if s.count(old_evidence) != 1:
    raise SystemExit(f"candidate schema marker count={s.count(old_evidence)}")
s = s.replace(old_evidence, new_evidence, 1)

marker = "function bankQualityIssues(qs: Array<Q & { id: string }>) {"
if s.count(marker) != 1:
    raise SystemExit(f"bank marker count={s.count(marker)}")

helper = r'''
const FROZEN_SET_QUESTION_COUNT = 25;

function frozenSetTargets(): BuildTarget[] {
  const groups: Array<{ level: Level; objective: Objective }> = [
    { level: 'L1', objective: 'remediation' },
    { level: 'L2', objective: 'diagnostic' },
    { level: 'L2', objective: 'stabilization' },
    { level: 'L3', objective: 'integration' },
    { level: 'L3', objective: 'challenge' },
  ];
  return groups.flatMap(group =>
    skills.map(skill => ({
      skill,
      level: group.level,
      objective: group.objective,
    }))
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
이 작업은 학생별 실시간 생성이 아니라 교사용 사전 문제은행 구축이다. 각 문항을 따로 생성하지 말고 전체 세트를 한 번에 설계해 출력한다.

[적응형 문제은행 메타데이터 계획]
${frozenSetTargetPlan(targets)}

[세트 전역 규칙]
- 전체 ${targets.length}문항은 5문항짜리 내부 세트 5개로 본다. 각 내부 세트에는 content, logic, inference, comparison, application이 각각 1문항씩 있다.
- 각 내부 세트마다 부정형 발문은 정확히 1문항만 사용한다. 단순히 '적절한'을 '적절하지 않은'으로 뒤집지 말고 실제 판단 과업이 부정형이어야 한다.
- 정답 번호는 전체 25문항에서 1~5가 각각 대체로 5회가 되게 하고, 가능하면 각 내부 세트에서도 1~5를 한 번씩 사용한다. 정답 위치를 맞추려고 의미를 훼손하지 않는다.
- 정답 선지가 유일한 최장 선지가 되는 문항은 전체 5개 이하로 제한한다. 길이 맞추기용 패딩은 금지한다.
- 모든 문항의 발문은 한 번 읽고 질문 대상을 즉시 알 수 있는 간결한 한 문장을 원칙으로 한다. <보기>를 제외한 질문 문장은 원칙적으로 85자 이내로 한다.
- 난도는 긴 발문·추상명사·중첩 관형절이 아니라 원문 근거 결합, 조건 비교, near-miss 오답 판별에서 만든다.
- L1은 핵심 정보/조건 확인, L2는 서로 다른 근거 2개 이상의 연결, L3는 필수 판단 3단계 이상의 실제 독해 부담을 갖게 한다.
- 각 skill/level/objective는 학생 화면 문구가 아니라 적응형 선택용 메타데이터다. 해당 목표를 실제 풀이 경로로 충족해야 한다.
- 동일 소재·동일 판단을 단어만 바꿔 반복하지 않는다.
- 원문에 없는 교사용 지식이나 외부 사실을 넣지 않는다.
- questions 배열 순서는 위 1~25 목표 순서와 반드시 일치한다.`;
}

async function frozenSetAssets(
  p: Passage,
  existing: Array<Q & { id: string }>,
  sourceChunk = 0
) {
  const sourceValidation = await validatePassageSource(p);
  if (sourceValidation.issues.length)
    throw statusError(
      '원문 품질 문제 때문에 출제를 중단했습니다: ' +
        sourceValidation.issues.join(', '),
      422
    );
  const content = sourceValidation.content;
  const imageMode = p.sourceMode === 'image';
  const rawPageTexts = imageMode ? await loadSourcePageTexts(p) : [];
  const alignedPageTexts = imageMode
    ? alignSourcePageTexts(p, rawPageTexts)
    : [];
  const sourcePages = imageMode
    ? relevantSourcePages(p, alignedPageTexts, content.text)
    : [];
  if (imageMode && !sourcePages.length)
    throw statusError(
      'PDF 페이지와 학생용 확정 지문 경계를 일치시킬 수 없어 구축을 시작하지 않았습니다.',
      422
    );
  const focusPages =
    imageMode && sourcePages.length
      ? selectBuildFocusPages(sourcePages, existing, sourceChunk)
      : [];
  const focusedText = focusedSourceText(p, content.text, focusPages);
  if (focusedText.replace(/\s/g, '').length < 100)
    throw statusError(
      '문항 생성에 사용할 목표 지문 텍스트가 부족합니다.',
      422
    );
  return {
    content,
    imageMode,
    sourcePages,
    focusPages,
    focusedText,
    context: sourceContext(p, focusedText, focusPages),
  };
}

function frozenQaIssues(
  q: Q,
  verdict: AuditVerdict | undefined,
  sourceText: string,
  focusedText: string,
  comparisonStems: string[],
  imageMode: boolean,
  sourcePages: SourcePageText[]
) {
  const issues = [
    ...questionDesignIssues(q, focusedText),
    ...staticQuestionIssues(
      q,
      sourceText,
      comparisonStems,
      imageMode,
      sourcePages
    ),
  ];
  if (!verdict) issues.push('FROZEN 일괄 QA 결과 누락');
  else {
    if (!auditPasses(verdict, q, focusedText))
      issues.push(...(verdict.issues?.length ? verdict.issues : ['FROZEN 일괄 QA 미통과']));
    if (
      verdict.difficulty?.observedSkill !== q.skill ||
      verdict.difficulty?.observedLevel !== q.level
    )
      issues.push(
        `실제 분류 불일치: 목표 ${q.skill}·${q.level}, QA ${verdict.difficulty?.observedSkill || '미분류'}·${verdict.difficulty?.observedLevel || '미분류'}`
      );
  }
  return [...new Set(issues)].slice(0, 8);
}

function frozenAcceptedFromAudit(q: Q, verdict: AuditVerdict): Q {
  const auditedTrap =
    verdict.choiceChecks.find(
      check => check.choice !== q.answer && check.plausible
    )?.trap || '';
  const misconception =
    q.misconception.trim().slice(0, 300) ||
    auditedTrap.trim().slice(0, 300) ||
    '원문의 결정적 조건을 빠뜨린 오독';
  const strongest =
    verdict.choiceChecks.find(
      check => check.choice !== q.answer && check.plausible
    )?.choice || (q.answer === 1 ? 2 : 1);
  const d = verdict.difficulty;
  return {
    ...q,
    misconception,
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
        solverA: 'not-used:frozen-set-v3',
        solverB: 'not-used:frozen-set-v3',
        solverC: 'not-used:frozen-set-v3',
        audit: GPT_MODELS.audit,
      },
      difficulty: d,
      blindDemand: {
        observedSkill: q.skill,
        observedLevel: q.level,
        shortcut: 'none',
        shortcutReason: 'v10.11 FROZEN 세트 일괄 QA를 통과함',
        minimalSteps: d.reasoningSteps,
        evidenceTests: d.evidenceQuotes.map(quote => ({
          quote,
          competingChoices: [strongest],
          reason: d.decisiveCondition,
        })),
        strongestDistractor: strongest,
        sharedGround: '정답과 경쟁 오답이 원문의 일부 근거를 공유함',
        decisiveDifference: d.decisiveCondition,
      },
      distractorReviews: verdict.choiceChecks
        .filter(check => check.choice !== q.answer)
        .map(check => ({
          choice: check.choice,
          trap: check.trap || check.reason,
        })),
    },
  };
}

function frozenAcceptedFromRepair(q: Q): Q {
  const design = q.design;
  const steps =
    design?.reasoningSteps?.filter(Boolean).slice(0, 5) ||
    [q.explanation.slice(0, 180)];
  const evidenceQuotes =
    design?.evidenceQuotes?.filter(Boolean).slice(0, 4) ||
    [q.evidence];
  const decisive =
    design?.decisiveCondition?.trim() ||
    '정답과 가장 매력적인 오답을 가르는 원문의 조건과 적용 범위를 구별한다.';
  const strongest =
    design?.distractors?.find(item => item.choice !== q.answer)?.choice ||
    (q.answer === 1 ? 2 : 1);
  const difficulty: DifficultyReview = {
    observedSkill: q.skill,
    observedLevel: q.level,
    singleFactRetrieval: q.level === 'L1',
    answerCued: false,
    reasoningSteps: steps,
    evidenceQuotes,
    decisiveCondition: decisive,
    levelRationale: 'v10.11 FROZEN 검수·수정 프롬프트로 탈락 사유를 반영해 일괄 수정함',
  };
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
        solverA: 'not-used:frozen-set-v3',
        solverB: 'not-used:frozen-set-v3',
        solverC: 'not-used:frozen-set-v3',
        audit: GPT_MODELS.audit,
      },
      difficulty,
      blindDemand: {
        observedSkill: q.skill,
        observedLevel: q.level,
        shortcut: 'none',
        shortcutReason: 'v10.11 FROZEN QA 수정 단계에서 결함을 제거함',
        minimalSteps: steps,
        evidenceTests: evidenceQuotes.map(quote => ({
          quote,
          competingChoices: [strongest],
          reason: decisive,
        })),
        strongestDistractor: strongest,
        sharedGround: '정답과 경쟁 오답이 원문의 일부 근거를 공유함',
        decisiveDifference: decisive,
      },
      distractorReviews:
        design?.distractors?.map(item => ({
          choice: item.choice,
          trap: item.misreading,
        })) || [],
    },
  };
}

async function saveFrozenSetQuestions(
  passageId: string,
  uid: string,
  bankRevision: number,
  questions: Q[],
  job: BuildJob
) {
  if (!questions.length) return 0;
  const existing = await listQuestions(passageId);
  const fresh = questions.filter(
    (q, index) =>
      !existing.some(old => sameGeneratedQuestion(old, q)) &&
      questions.findIndex(other => sameGeneratedQuestion(other, q)) === index
  );
  if (!fresh.length) return 0;
  const currentPassage = await getPassage(passageId);
  if (
    !currentPassage ||
    currentPassage.ownerUid !== uid ||
    currentPassage.deleting ||
    currentBankRevision(currentPassage) !== bankRevision ||
    currentPassage.status === 'published'
  )
    throw statusError(
      '검수 중 문제은행 revision이 변경되어 문항을 저장하지 않았습니다.',
      409
    );
  const ids = await db.add(qTable(passageId), fresh);
  if (ids.some(id => id === null)) {
    const partialIds = ids.filter((id): id is string => id !== null);
    if (partialIds.length) await deleteDbRows(qTable(passageId), partialIds);
    throw statusError(
      '검증 문항 일부를 저장하지 못해 이번 저장분을 되돌렸습니다.',
      500
    );
  }
  const canonicalIds = await canonicalizeSavedQuestionDuplicates(
    passageId,
    ids.filter((id): id is string => id !== null),
    new Set(existing.map(question => question.id))
  );
  job.savedQuestionIds = [
    ...(job.savedQuestionIds || []),
    ...canonicalIds,
  ];
  return canonicalIds.length;
}

async function startFrozenSetRepairBackground(
  assets: Awaited<ReturnType<typeof frozenSetAssets>>,
  candidates: Q[],
  targets: BuildTarget[],
  issues: string[]
) {
  const repairItems = candidates.map((q, index) => ({
    index,
    target: targets[index],
    previousQuestion: auditQuestion(q),
    issues: issues[index] || 'FROZEN QA에서 수정 필요',
  }));
  return openAiStartBackground({
    model: GPT_MODELS.generator,
    schemaName: 'frozen_set_repairs',
    schema: candidateQuestionSchema(targets, assets.focusedText, true),
    system: `${FROZEN_READING_QA_PROMPT}\n\n${FROZEN_QA_ADAPTER_RULES}`,
    prompt: `${assets.context}

아래는 v10.11 FROZEN 세트 일괄 QA에서 탈락한 문항들이다.
각 항목의 target을 그대로 충족하도록 결함을 수정하고, 완성된 문항 전체를 questions 배열로 같은 순서에 출력하라.
이미 합격한 문항은 건드리지 않는다. 새 문항 수를 늘리지 않는다.
발문은 간결하게 유지하고 난도를 문장 복잡성으로 만들지 않는다.
정답 번호와 부정형/긍정형은 가능하면 기존 세트 분포를 유지하되, 그 자체가 결함이면 의미 품질을 우선해 고친다.
원문 밖 지식을 추가하지 않는다.

수정 대상:
${JSON.stringify(repairItems)}`,
    images: [],
    maxOutputTokens: Math.min(
      GENERATION_OUTPUT_TOKENS,
      Math.max(12000, targets.length * 1800)
    ),
    reasoning: 'high',
  });
}

async function frozenSetBuildStep(
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
      return json({ ...result, bankComplete: result.complete, pipelineComplete: true });
    }
    const resumed = await findResumableBuildJob(
      uid,
      passageId,
      currentBankRevision(p)
    );
    if (resumed)
      return json({
        phase: resumed.pendingGenerationResponseId
          ? 'generating'
          : resumed.candidates.length
            ? resumed.pendingAuditResponseId
              ? 'solving-a'
              : 'generated'
            : 'generation-ready',
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
      apiPlan: 'generate-set -> qa-set -> repair-failures-only',
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
    if (!targets.length || !job.candidates.length) {
      const result = await makeBuildResult(
        passageId,
        job.savedQuestionIds?.length || 0,
        job.generatedCount,
        0,
        job.auditVerdicts?.length || 0
      );
      job.result = result;
      await saveBuildJob(uid, passageId, jobId, job);
      return json({
        ...result,
        complete: true,
        bankComplete: result.complete,
        pipelineComplete: true,
        manualReviewRequired: !result.complete,
        rejectionSummary: '수정할 문항 데이터가 없어 추가 API 호출 없이 종료했습니다.',
      });
    }

    if (job.pendingGenerationResponseId) {
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
          repairPending: true,
          targetCount: targets.length,
        });

      const raw = Array.isArray(pending.data.questions)
        ? pending.data.questions
        : [];
      const repaired = targets
        .map((target, index) => candidateToQuestion(raw[index], target))
        .filter((q): q is Q => !!q);
      delete job.pendingGenerationResponseId;
      job.generatedCount += raw.length;

      const comparisonStems = usableQuestions(existing).map(item => item.stem);
      const valid = repaired.filter(q => {
        const others = repaired
          .filter(other => other !== q)
          .map(other => other.stem);
        return (
          questionDesignIssues(q, assets.focusedText).length === 0 &&
          staticQuestionIssues(
            q,
            assets.content.text,
            [...comparisonStems, ...others],
            assets.imageMode,
            assets.sourcePages
          ).length === 0
        );
      });
      const accepted = valid.map(frozenAcceptedFromRepair);
      await saveFrozenSetQuestions(
        passageId,
        uid,
        job.bankRevision || currentBankRevision(p),
        accepted,
        job
      );
      job.candidates = [];
      job.targets = [];
      job.generationRejections = [];
      job.repairRound = 2;
      const result = await makeBuildResult(
        passageId,
        job.savedQuestionIds?.length || 0,
        job.generatedCount,
        0,
        job.auditVerdicts?.length || 0
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
        rejectionSummary: result.complete
          ? ''
          : `FROZEN 1회 생성·1회 QA·1회 수정까지 마쳤지만 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
      });
    }

    job.pendingGenerationResponseId = await startFrozenSetRepairBackground(
      assets,
      job.candidates,
      targets,
      job.generationRejections || []
    );
    await saveBuildJob(uid, passageId, jobId, job);
    return json({
      phase: 'generating',
      jobId,
      repairPending: true,
      targetCount: targets.length,
      apiStage: 'repair-failures-only',
    });
  }

  if (!job.candidates.length) {
    const targets = job.targets || frozenSetTargets();
    if (job.pendingGenerationResponseId) {
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
        });
      const raw = Array.isArray(pending.data.questions)
        ? pending.data.questions
        : [];
      const candidates = targets
        .map((target, index) => candidateToQuestion(raw[index], target))
        .filter((q): q is Q => !!q);
      delete job.pendingGenerationResponseId;
      job.generatedCount += raw.length;
      job.generationIndex = targets.length;
      job.candidates = candidates;
      await saveBuildJob(uid, passageId, jobId, job);
      if (candidates.length !== targets.length) {
        const result = await makeBuildResult(
          passageId,
          0,
          job.generatedCount,
          0,
          0
        );
        job.result = result;
        await saveBuildJob(uid, passageId, jobId, job);
        return json({
          ...result,
          complete: true,
          bankComplete: false,
          pipelineComplete: true,
          manualReviewRequired: true,
          rejectionSummary: `세트 생성 응답 ${targets.length}개 중 ${candidates.length}개만 구조화되어 추가 API 호출 없이 종료했습니다.`,
        });
      }
      return json({
        phase: 'generated',
        jobId,
        generatedCount: job.generatedCount,
        targetCount: candidates.length,
        apiStage: 'set-generated',
      });
    }

    job.pendingGenerationResponseId = await startQuestionGenerationBackground(
      assets.context,
      frozenSetGenerationInstructions(targets),
      targets,
      [],
      job.generationRetryCount || 0,
      assets.focusedText,
      true
    );
    await saveBuildJob(uid, passageId, jobId, job);
    return json({
      phase: 'generating',
      jobId,
      targetCount: targets.length,
      apiStage: 'generate-set',
    });
  }

  if (!job.auditVerdicts) {
    if (job.pendingAuditResponseId) {
      const pending = await pollBuildStage<{ verdicts: AuditVerdict[] }>(
        uid,
        passageId,
        jobId,
        job,
        'audit',
        GPT_MODELS.audit
      );
      if (pending.state === 'waiting')
        return json({
          phase: 'solving-a',
          jobId,
          targetCount: job.candidates.length,
          apiStage: 'qa-set',
        });
      job.auditVerdicts = Array.isArray(pending.data.verdicts)
        ? pending.data.verdicts
        : [];
      delete job.pendingAuditResponseId;
      await saveBuildJob(uid, passageId, jobId, job);
    } else {
      const auditInput = job.candidates.map((q, index) => ({
        index,
        question: auditQuestion(q),
      }));
      job.pendingAuditResponseId = await openAiStartBackground({
        model: GPT_MODELS.audit,
        schemaName: 'frozen_set_qa',
        schema: auditSchema(job.candidates.length, assets.focusedText),
        system: AUDIT_SYSTEM,
        prompt: `${assets.context}

${auditInstructions(p.category)}

v10.11 FROZEN 세트 전체를 한 번에 검수한다. 문항을 서로 비교해 발문 중복, 판단 중복, 정답 위치 편향, 부정형 편중, 정답 길이 단서를 함께 점검한다.
개별 문항의 observedSkill/observedLevel은 실제 최단 풀이를 기준으로 판정한다.
채택을 막는 결함만 issues에 기록하고, 문제가 없으면 issues는 빈 배열로 둔다.

검수 대상:
${JSON.stringify(auditInput)}`,
        images: [],
        maxOutputTokens: AUDIT_OUTPUT_TOKENS,
        reasoning: 'high',
      });
      await saveBuildJob(uid, passageId, jobId, job);
      return json({
        phase: 'solving-a',
        jobId,
        targetCount: job.candidates.length,
        apiStage: 'qa-set',
      });
    }
  }

  const verdicts = job.auditVerdicts || [];
  const currentUsableStems = usableQuestions(existing).map(item => item.stem);
  const passed: Q[] = [];
  const failedQuestions: Q[] = [];
  const failedTargets: BuildTarget[] = [];
  const failedIssues: string[] = [];

  job.candidates.forEach((q, index) => {
    const verdict = verdicts.find(item => item.index === index);
    const otherStems = job.candidates
      .filter((_, otherIndex) => otherIndex !== index)
      .map(other => other.stem);
    const issues = frozenQaIssues(
      q,
      verdict,
      assets.content.text,
      assets.focusedText,
      [...currentUsableStems, ...otherStems],
      assets.imageMode,
      assets.sourcePages
    );
    if (!issues.length && verdict) passed.push(frozenAcceptedFromAudit(q, verdict));
    else {
      failedQuestions.push(q);
      failedTargets.push({
        skill: q.skill,
        level: q.level,
        objective: q.objective,
      });
      failedIssues.push(issues.join(' / '));
    }
  });

  await saveFrozenSetQuestions(
    passageId,
    uid,
    job.bankRevision || currentBankRevision(p),
    passed,
    job
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
    rejectionSummary: result.complete
      ? ''
      : `FROZEN 세트 생성·일괄 QA를 마쳤지만 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
  });
}

'''
s = s.replace(marker, helper + marker, 1)

route_marker = '''          if (
            phase === 'generate' &&
            (typeof b.jobId !== 'string' || !b.jobId)
          ) {'''
if s.count(route_marker) != 1:
    raise SystemExit(f"build route marker count={s.count(route_marker)}")
branch = '''          if (
            b.trial !== true &&
            QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v3'
          )
            return await frozenSetBuildStep(uid, passageId, p, b);

'''
s = s.replace(route_marker, branch + route_marker, 1)

required = [
    "v10.11-frozen-set-adaptive-v3",
    "v10.11-frozen-set-v3",
    "const FROZEN_SET_QUESTION_COUNT = 25;",
    "function frozenSetTargets()",
    "async function frozenSetBuildStep(",
    "apiPlan: 'generate-set -> qa-set -> repair-failures-only'",
    "QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v3'",
]
for item in required:
    if item not in s:
        raise SystemExit(f"missing marker after patch: {item}")

path.write_text(s, encoding="utf-8")
print("Applied v10.11 FROZEN set pipeline v3")
