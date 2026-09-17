from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

repls = [
    ("const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v6';", "const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v7';"),
    ("const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v6';", "const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v7';"),
    ("const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v6';", "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v7';"),
    ("schemaName: 'frozen_set_questions_v6',", "schemaName: 'frozen_set_questions_v7',"),
    ("QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v6'", "QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v7'"),
]
for old, new in repls:
    if s.count(old) != 1:
        raise SystemExit(f'marker mismatch {old!r}: {s.count(old)}')
    s = s.replace(old, new, 1)

# Persist references needed for one bounded targeted repair call.
old_type = """  repairInputs?: Array<{ question: Q; issues: string[] }>;
  pendingGenerationResponseId?: string;"""
new_type = """  repairInputs?: Array<{ question: Q; issues: string[] }>;
  repairQuestionRefs?: string[];
  repairTargets?: BuildTarget[];
  pendingGenerationResponseId?: string;"""
if s.count(old_type) != 1:
    raise SystemExit(f'BuildJob repair type marker count={s.count(old_type)}')
s = s.replace(old_type, new_type, 1)

marker = 'async function frozenSetBuildStep('
if s.count(marker) != 1:
    raise SystemExit(f'frozenSetBuildStep marker count={s.count(marker)}')

helpers = r'''
function frozenNegativeStem(stem: string) {
  const head = stem.split(/\n\s*<보기>|\n\s*〈보기〉/)[0];
  return /(?:적절하지|옳지|타당하지|일치하지|부합하지|아닌 것은|않은 것은|없는 것은|추론할 수 없는|뒷받침되지 않는|알 수 없는|부적절)/.test(head);
}

function frozenUniqueLongest(q: Q) {
  const lengths = q.choices.map(choice => choice.replace(/\s/g, '').length);
  const answerLength = lengths[q.answer - 1] || 0;
  const max = Math.max(...lengths);
  return answerLength === max && lengths.filter(length => length === max).length === 1;
}

function frozenProofIssues(q: Q, sourceText: string) {
  const issues: string[] = [];
  if (!q.stem.trim()) issues.push('발문 누락');
  if (q.choices.length !== 5 || new Set(q.choices.map(choice => stemKey(choice))).size !== 5)
    issues.push('선택지 구조 또는 중복 오류');
  if (!Number.isInteger(q.answer) || q.answer < 1 || q.answer > 5) issues.push('정답 번호 오류');
  if (!q.explanation.trim()) issues.push('해설 누락');
  const proof = q.design;
  if (!proof) return [...issues, '난도 증명 필드 누락'];
  const required = q.level === 'L3' ? 3 : q.level === 'L2' ? 2 : 1;
  const evidence = (proof.evidenceQuotes || []).map(item => normalizeOldHangul(item).trim()).filter(Boolean);
  const steps = (proof.reasoningSteps || []).map(item => item.trim()).filter(Boolean);
  if (evidence.length < required || new Set(evidence.map(item => stemKey(item))).size < required)
    issues.push(`${q.level} 필수 원문 근거 ${required}개 미충족`);
  if (steps.length < required || new Set(steps.map(item => stemKey(item))).size < required)
    issues.push(`${q.level} 필수 판단 ${required}단계 미충족`);
  const source = normalizeOldHangul(sourceText);
  if (evidence.slice(0, required).some(quote => !source.includes(quote)))
    issues.push('난도 증명 근거가 승인 원문과 불일치');
  if (q.level === 'L3' && /(?:중심 생각|중심 내용|주제|모두 포함|이동 순서|구성 순서|제시된 .*모두|이유로 가장 적절|이유는\?|알 수 있는 것은\?|성격으로 가장 적절)/.test(q.stem))
    issues.push('L3 금지형 단순 확인 발문');
  if (q.level === 'L3' && (!proof.decisiveCondition?.trim() || proof.distractors?.[0]?.choice === q.answer))
    issues.push('L3 경쟁 오답의 결정 조건이 불충분');
  return [...new Set(issues)];
}

type FrozenRepairPlanItem = {
  ref: string;
  target: BuildTarget;
  question: Q;
  issues: string[];
};

function frozenAutomaticRepairPlan(
  existing: Array<Q & { id: string }>,
  candidates: Q[],
  sourceText: string
): FrozenRepairPlanItem[] {
  const rows: FrozenRepairPlanItem[] = [
    ...existing.map(q => ({
      ref: q.id,
      target: { skill: q.skill, level: q.level, objective: q.objective },
      question: q,
      issues: [] as string[],
    })),
    ...candidates.map((q, index) => ({
      ref: `new:${index}`,
      target: { skill: q.skill, level: q.level, objective: q.objective },
      question: q,
      issues: frozenProofIssues(q, sourceText),
    })),
  ];
  const add = (row: FrozenRepairPlanItem, issue: string) => {
    if (!row.issues.includes(issue)) row.issues.push(issue);
  };
  const total = rows.length;
  if (!total) return [];

  // v10.11 FROZEN set-wide negative-stem distribution: 20-40%.
  const negative = rows.filter(row => frozenNegativeStem(row.question.stem));
  const minNegative = Math.ceil(total * 0.2);
  const maxNegative = Math.floor(total * 0.4);
  if (negative.length < minNegative) {
    const need = minNegative - negative.length;
    const pool = rows
      .filter(row => !frozenNegativeStem(row.question.stem) && !row.issues.length)
      .sort((a, b) => Number(a.question.level === 'L3') - Number(b.question.level === 'L3'));
    pool.slice(0, need).forEach(row => add(row, '세트 극성 보정: 의미상 자연스러운 부정형 판단 과업으로 수정'));
  } else if (negative.length > maxNegative) {
    negative.slice(maxNegative).forEach(row => add(row, '세트 극성 보정: 긍정형 판단 과업으로 수정'));
  }

  // Correct answer may be uniquely longest in at most 20% of the bank.
  const longest = rows
    .filter(row => frozenUniqueLongest(row.question))
    .map(row => {
      const lengths = row.question.choices.map(choice => choice.replace(/\s/g, '').length);
      const answerLength = lengths[row.question.answer - 1] || 0;
      const second = Math.max(...lengths.filter((_, index) => index !== row.question.answer - 1));
      return { row, gap: answerLength - second };
    })
    .sort((a, b) => b.gap - a.gap);
  const allowedLongest = Math.floor(total * 0.2);
  longest.slice(0, Math.max(0, longest.length - allowedLongest)).forEach(({ row }) =>
    add(row, '정답 길이 단서 제거: 정답 의미는 유지하되 군더더기를 줄이고 오답에는 패딩을 넣지 말 것')
  );

  // Keep answer-position distribution within the existing public-bank guard.
  const maxAnswer = Math.max(7, Math.floor(total * 0.3));
  const byAnswer = new Map<number, FrozenRepairPlanItem[]>();
  for (const answer of [1, 2, 3, 4, 5]) byAnswer.set(answer, rows.filter(row => row.question.answer === answer));
  for (const answer of [1, 2, 3, 4, 5]) {
    const group = byAnswer.get(answer) || [];
    if (group.length > maxAnswer)
      group.slice(maxAnswer).forEach(row => add(row, `정답 위치 ${answer}번 과다: 의미를 바꾸지 말고 선택지 순서를 재배열`));
  }

  // Exact/near duplicate stems should be rewritten, not silently accepted.
  for (let i = 0; i < rows.length; i++) {
    for (let j = 0; j < i; j++) {
      if (sameGeneratedQuestion(rows[i].question, rows[j].question)) {
        add(rows[i], '다른 문항과 발문·판단이 중복됨: 같은 목표 난도를 유지하며 다른 근거 관계로 재설계');
        break;
      }
    }
  }
  return rows.filter(row => row.issues.length);
}

function frozenPlaceholderQuestion(target: BuildTarget): Q {
  return {
    stem: '[재생성 필요]',
    choices: ['가', '나', '다', '라', '마'],
    answer: 1,
    explanation: '구조화 응답 누락으로 동일 목표의 새 문항이 필요하다.',
    misconception: '구조화 응답 누락',
    evidence: '',
    skill: target.skill,
    level: target.level,
    objective: target.objective || 'integration',
  };
}

async function startFrozenAutomaticRepair(
  assets: Awaited<ReturnType<typeof frozenSetAssets>>,
  items: FrozenRepairPlanItem[]
) {
  const targets = items.map(item => item.target);
  const payload = items.map((item, index) => ({
    index,
    target: item.target,
    issues: item.issues,
    currentQuestion: {
      stem: item.question.stem,
      choices: item.question.choices,
      answer: item.question.answer,
      explanation: item.question.explanation,
      misconception: item.question.misconception,
      evidence: item.question.evidence,
      difficultyEvidence: item.question.design?.evidenceQuotes || [],
      reasoningSteps: item.question.design?.reasoningSteps || [],
      strongestDistractor: item.question.design?.distractors?.[0]?.choice || (item.question.answer === 1 ? 2 : 1),
      decisiveDifference: item.question.design?.decisiveCondition || '',
    },
  }));
  return openAiStartBackground({
    model: GPT_MODELS.generator,
    schemaName: 'frozen_targeted_repairs_v7',
    schema: frozenCompactQuestionSchema(targets.length),
    system: `${FROZEN_READING_QA_PROMPT}\n\n${FROZEN_QA_ADAPTER_RULES}`,
    prompt: `[승인 지문]\n${assets.focusedText}\n\n아래 문항만 v10.11 FROZEN 기준으로 수정한다. 제공되지 않은 문항은 건드리지 않는다.\n각 target의 skill/level/objective를 그대로 유지한다. 발문은 간결하게 유지하고 난도를 문장 복잡성으로 만들지 않는다.\nL3는 서로 다른 원문 근거 3개와 생략 불가능한 판단 3단계를 실제로 요구해야 하며, 단순 주제·일치·순서·한 문장 확인형으로 바꾸지 않는다.\n'정답 길이 단서 제거'는 정답의 군더더기를 줄이거나 선지 전체를 자연스럽게 재작성해 해결한다. 오답에 의미 없는 패딩을 붙이지 않는다.\n'정답 위치 과다'는 정답 내용을 바꾸지 말고 선택지 순서를 재배열해 해결할 수 있다.\n'극성 보정'은 어미만 기계적으로 뒤집지 말고 실제 판단 과업 자체를 자연스럽게 바꾼다.\n수정 후 각 문항은 difficultyEvidence/reasoningSteps/strongestDistractor/decisiveDifference를 다시 정확히 작성한다.\n\n수정 대상:\n${JSON.stringify(payload)}`,
    images: [],
    maxOutputTokens: Math.min(18000, Math.max(7000, targets.length * 1700)),
    reasoning: 'medium',
  });
}

async function updateFrozenExistingQuestions(
  passageId: string,
  replacements: Array<{ id: string; question: Q }>
) {
  if (!replacements.length) return;
  const results = await db.update(
    qTable(passageId),
    replacements.map(item => ({ id: item.id, record: frozenAccepted(item.question) }))
  );
  if (results.some(saved => !saved))
    throw statusError('자동 품질 보정 문항 일부를 저장하지 못했습니다.', 500);
}

'''
s = s.replace(marker, helpers + marker, 1)

start = s.find('async function frozenSetBuildStep(')
end = s.find('function bankQualityIssues(', start)
if start < 0 or end < 0 or end <= start:
    raise SystemExit('could not locate frozenSetBuildStep block')

new_build = r'''async function frozenSetBuildStep(
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
      return json({ ...result, complete: true, bankComplete: true, pipelineComplete: true, apiCallsMaximum: 0 });
    }
    const resumed = await findResumableBuildJob(uid, passageId, currentBankRevision(p));
    if (resumed && resumed.engineVersion === QUESTION_ENGINE_VERSION)
      return json({
        phase: resumed.pendingGenerationResponseId ? 'generating' : 'generation-ready',
        jobId: resumed.id,
        resumed: true,
        generatedCount: resumed.generatedCount,
        targetCount: resumed.targets?.length || resumed.repairTargets?.length || frozenMissingTargets(existing).length || FROZEN_SET_QUESTION_COUNT,
        repairPending: resumed.repairRound === 1,
        apiPlan: 'generate-once -> deterministic-check -> targeted-repair-once',
      });
    if (resumed) await clearBuildJobs(uid, passageId);

    if (p.status === 'published') p = await invalidatePassageBank(passageId, p);
    await frozenSetAssets(p, existing, sourceChunk);
    await clearBuildJobs(uid, passageId);
    const targets = frozenMissingTargets(existing);
    if (!targets.length) {
      const result = await makeBuildResult(passageId, 0, 0, 0, 0);
      return json({ ...result, complete: true, bankComplete: result.complete, pipelineComplete: true, apiCallsMaximum: 0 });
    }
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
      apiPlan: 'generate-once -> deterministic-check -> targeted-repair-once',
      apiCallsMaximum: 2,
    });
  }

  const jobId = body.jobId;
  const job = await loadBuildJob(uid, passageId, jobId);
  if (job.engineVersion !== QUESTION_ENGINE_VERSION)
    return error('이전 출제 엔진 작업입니다. 새 자동 구축을 시작해 주세요.', 409);
  if (job.bankRevision !== currentBankRevision(p))
    return error('문제은행 revision이 변경되었습니다. 새 구축을 시작해 주세요.', 409);

  const existing = await listQuestions(passageId);
  const existingUsable = usableQuestions(existing);
  const assets = await frozenSetAssets(p, existing, job.sourceChunk || sourceChunk);

  // Second and final model call: repair only deterministically flagged questions.
  if (job.repairRound === 1) {
    const repairTargets = job.repairTargets || [];
    const refs = job.repairQuestionRefs || [];
    if (!repairTargets.length || refs.length !== repairTargets.length || !job.pendingGenerationResponseId)
      return error('자동 품질 보정 상태가 올바르지 않습니다.', 409);
    const pending = await pollBuildStage<{ questions: unknown[] }>(
      uid, passageId, jobId, job, 'generation', GPT_MODELS.generator
    );
    if (pending.state === 'waiting')
      return json({ phase: 'generating', jobId, repairPending: true, targetCount: repairTargets.length, apiStage: 'targeted-quality-repair', apiCallsMaximum: 2 });

    const raw = Array.isArray(pending.data.questions) ? pending.data.questions : [];
    const repaired = repairTargets.map((target, index) =>
      frozenRawToQuestion(raw[index], target) || frozenPlaceholderQuestion(target)
    );
    delete job.pendingGenerationResponseId;
    job.generatedCount += raw.length;

    const generated = [...job.candidates];
    const existingReplacement = new Map<string, Q>();
    refs.forEach((ref, index) => {
      const q = repaired[index];
      if (ref.startsWith('new:')) {
        const candidateIndex = Number(ref.slice(4));
        if (Number.isInteger(candidateIndex) && candidateIndex >= 0 && candidateIndex < generated.length)
          generated[candidateIndex] = q;
      } else {
        existingReplacement.set(ref, q);
      }
    });
    const prospectiveExisting = existingUsable.map(q => {
      const replacement = existingReplacement.get(q.id);
      return replacement ? ({ ...replacement, id: q.id } as Q & { id: string }) : q;
    });
    const remaining = frozenAutomaticRepairPlan(prospectiveExisting, generated, assets.content.text);
    if (remaining.length) {
      job.repairRound = 2;
      job.result = await makeBuildResult(passageId, 0, job.generatedCount, 0, 0);
      job.generationRejections = remaining.slice(0, 12).map(item => `${item.target.skill}/${item.target.level}: ${item.issues.join(' / ')}`);
      job.pendingGenerationResponseId = undefined;
      await saveBuildJob(uid, passageId, jobId, job);
      return json({
        ...job.result,
        complete: true,
        bankComplete: false,
        pipelineComplete: true,
        manualReviewRequired: true,
        apiCallsMaximum: 2,
        rejectionSummary: `자동 생성 1회와 표적 보정 1회를 마쳤지만 ${remaining.length}문항에 품질 조건이 남아 저장을 보류했습니다.`,
      });
    }

    await updateFrozenExistingQuestions(
      passageId,
      [...existingReplacement.entries()].map(([id, question]) => ({ id, question }))
    );
    const acceptedGenerated = generated.map(q => frozenAccepted(q));
    await saveFrozenSetQuestions(
      passageId, uid, job.bankRevision || currentBankRevision(p), acceptedGenerated, job
    );
    job.candidates = [];
    job.targets = [];
    job.repairTargets = [];
    job.repairQuestionRefs = [];
    job.repairInputs = [];
    job.repairRound = 2;
    const result = await makeBuildResult(passageId, job.savedQuestionIds?.length || 0, job.generatedCount, generated.length, 0);
    job.result = result;
    await saveBuildJob(uid, passageId, jobId, job);
    return json({
      ...result,
      complete: true,
      bankComplete: result.complete,
      pipelineComplete: true,
      manualReviewRequired: !result.complete,
      apiCallsMaximum: 2,
      rejectionSummary: result.complete ? '' : `자동 표적 보정 후에도 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
    });
  }

  const targets = job.targets || frozenMissingTargets(existing);
  if (!job.pendingGenerationResponseId) {
    job.pendingGenerationResponseId = await startFrozenSetGeneration(assets, targets);
    await saveBuildJob(uid, passageId, jobId, job);
    return json({ phase: 'generating', jobId, targetCount: targets.length, apiStage: 'frozen-generate-self-review', apiCallsMaximum: 2 });
  }

  const pending = await pollBuildStage<{ questions: unknown[] }>(
    uid, passageId, jobId, job, 'generation', GPT_MODELS.generator
  );
  if (pending.state === 'waiting')
    return json({ phase: 'generating', jobId, targetCount: targets.length, generatedCount: job.generatedCount, apiStage: 'frozen-generate-self-review', apiCallsMaximum: 2 });

  const raw = Array.isArray(pending.data.questions) ? pending.data.questions : [];
  const candidates = targets.map((target, index) =>
    frozenRawToQuestion(raw[index], target) || frozenPlaceholderQuestion(target)
  );
  delete job.pendingGenerationResponseId;
  job.generatedCount += raw.length;
  job.generationIndex = targets.length;
  job.candidates = candidates;

  const plan = frozenAutomaticRepairPlan(existingUsable, candidates, assets.content.text);
  if (plan.length) {
    job.repairRound = 1;
    job.repairQuestionRefs = plan.map(item => item.ref);
    job.repairTargets = plan.map(item => item.target);
    job.repairInputs = plan.map(item => ({ question: item.question, issues: item.issues }));
    job.pendingGenerationResponseId = await startFrozenAutomaticRepair(assets, plan);
    await saveBuildJob(uid, passageId, jobId, job);
    return json({
      phase: 'generating',
      jobId,
      repairPending: true,
      targetCount: plan.length,
      generatedCount: job.generatedCount,
      apiStage: 'targeted-quality-repair',
      apiCallsMaximum: 2,
    });
  }

  const accepted = candidates.map(q => frozenAccepted(q));
  await saveFrozenSetQuestions(
    passageId, uid, job.bankRevision || currentBankRevision(p), accepted, job
  );
  job.candidates = [];
  job.targets = [];
  const result = await makeBuildResult(passageId, job.savedQuestionIds?.length || 0, job.generatedCount, candidates.length, 0);
  job.result = result;
  await saveBuildJob(uid, passageId, jobId, job);
  return json({
    ...result,
    complete: true,
    bankComplete: result.complete,
    pipelineComplete: true,
    manualReviewRequired: !result.complete,
    apiCallsMaximum: 1,
    rejectionSummary: result.complete ? '' : `FROZEN 1회 생성 후 공개 조건이 남았습니다: ${bankQualityIssues(await listQuestions(passageId)).join(' · ')}`,
  });
}

'''
s = s[:start] + new_build + s[end:]

# Update current stored-model labels in the new engine's verification metadata.
s = s.replace("'not-used:frozen-set-v6'", "'not-used:frozen-set-v7'")
s = s.replace("'v10.11 FROZEN v6 자체검수 및 난도 증명 게이트를 통과함'", "'v10.11 FROZEN v7 자동 품질 게이트 및 필요 시 표적 보정을 통과함'")

required = [
    "v10.11-frozen-set-adaptive-v7",
    "v10.11-frozen-set-v7",
    "function frozenAutomaticRepairPlan",
    "startFrozenAutomaticRepair",
    "targeted-quality-repair",
    "apiCallsMaximum: 2",
    "repairQuestionRefs",
    "정답 길이 단서 제거",
]
for item in required:
    if item not in s:
        raise SystemExit(f'missing v7 marker: {item}')

path.write_text(s, encoding='utf-8')
print('Applied FROZEN v7 deterministic quality gate + one targeted repair call')
