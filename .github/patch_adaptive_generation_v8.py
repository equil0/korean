from pathlib import Path
p=Path('v66-backend/backend/index.ts')
s=p.read_text(encoding='utf-8')

# Add explicit adaptive generation version marker without changing public-bank quality version.
const_marker = "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v7';"
if s.count(const_marker) != 1:
    raise SystemExit(f'question engine marker count={s.count(const_marker)}')
s = s.replace(const_marker, const_marker + "\nconst ADAPTIVE_GENERATION_VERSION = 'adaptive-prefetch-v1';", 1)

# 1) Extend Q with adaptive metadata.
old="""type Q = {
  design?: QuestionDesign;
  stem: string;
  choices: string[];
  answer: number;
  explanation: string;
  skill: Skill;
  level: Level;
  objective: Objective;
  misconception: string;
  evidence: string;
  qualityVersion?: string;
  verification?: Verification;
};"""
new="""type Q = {
  design?: QuestionDesign;
  stem: string;
  choices: string[];
  answer: number;
  explanation: string;
  skill: Skill;
  level: Level;
  objective: Objective;
  misconception: string;
  evidence: string;
  qualityVersion?: string;
  verification?: Verification;
  adaptiveOwnerUid?: string;
  adaptiveBranch?: 'success' | 'recovery';
  adaptiveSourceQuestionId?: string;
  adaptiveGeneratedAt?: string;
};"""
assert s.count(old)==1, s.count(old)
s=s.replace(old,new,1)

# 2) Insert adaptive helpers after chooseNext.
marker="""function stemReadabilityIssues(stem: string) {"""
assert s.count(marker)==1
helpers=r'''
type AdaptiveBranch = 'success' | 'recovery';
type AdaptiveTarget = BuildTarget & {
  branch: AdaptiveBranch;
  misconception?: string;
};
type AdaptivePrefetchMarker = {
  sourceQuestionId: string;
  jobId: string;
  bankRevision: number;
  createdAt: string;
};

function adaptiveQuestionTable(uid: string, passageId: string, revision: number) {
  return `adaptive-q-v1:${uid}:${passageId}:${revision}`;
}
function adaptivePrefetchTable(uid: string, passageId: string, revision: number) {
  return `adaptive-prefetch-v1:${uid}:${passageId}:${revision}`;
}
function adaptiveLevel(mastery: number): Level {
  return mastery < 0.45 ? 'L1' : mastery < 0.72 ? 'L2' : 'L3';
}
function adaptiveNextSkill(p: Progress) {
  const counts = p.sessionSkillCounts || blankSessionSkillCounts();
  const minCount = Math.min(...skills.map(skill => counts[skill] || 0));
  const eligible = skills.filter(skill => (counts[skill] || 0) === minCount);
  if (p.recentWrongSkill && eligible.includes(p.recentWrongSkill))
    return p.recentWrongSkill;
  return eligible.reduce((a, b) => (p.mastery[a] <= p.mastery[b] ? a : b));
}
function adaptiveObjective(level: Level, recovery = false): Objective {
  if (recovery) return 'remediation';
  if (level === 'L3') return 'challenge';
  if (level === 'L2') return 'integration';
  return 'diagnostic';
}
function adaptiveTargetsForCurrent(q: Q & { id: string }, p: Progress): AdaptiveTarget[] {
  const successMastery = { ...p.mastery };
  const gain = q.level === 'L3' ? 0.11 : q.level === 'L2' ? 0.09 : 0.07;
  successMastery[q.skill] = clamp(successMastery[q.skill] + gain);
  const successCounts = { ...(p.sessionSkillCounts || blankSessionSkillCounts()) };
  successCounts[q.skill] = (successCounts[q.skill] || 0) + 1;
  const successProgress: Progress = {
    ...p,
    mastery: successMastery,
    sessionSkillCounts: successCounts,
    recentWrongSkill: p.recentWrongSkill === q.skill ? null : p.recentWrongSkill,
  };
  const successSkill = adaptiveNextSkill(successProgress);
  const successLevel = adaptiveLevel(successMastery[successSkill]);

  const recoveryMastery = clamp(p.mastery[q.skill] - 0.06);
  const recoveryLevel = adaptiveLevel(recoveryMastery);
  return [
    {
      branch: 'success',
      skill: successSkill,
      level: successLevel,
      objective: adaptiveObjective(successLevel, false),
      misconception: '',
    },
    {
      branch: 'recovery',
      skill: q.skill,
      level: recoveryLevel,
      objective: 'remediation',
      misconception:
        p.recentMisconception && p.recentMisconception !== '모르겠음'
          ? p.recentMisconception
          : q.misconception,
    },
  ];
}
async function listAdaptiveQuestions(uid: string, passageId: string, revision: number) {
  const rows = await listAll<Q>(adaptiveQuestionTable(uid, passageId, revision), 100, 10);
  return usableQuestions(rows).filter(q => q.adaptiveOwnerUid === uid);
}
async function latestAdaptivePrefetchMarker(
  uid: string,
  passageId: string,
  revision: number,
  sourceQuestionId: string
) {
  const rows = await listAll<AdaptivePrefetchMarker>(
    adaptivePrefetchTable(uid, passageId, revision),
    100,
    10
  );
  return rows
    .filter(row => row.sourceQuestionId === sourceQuestionId && row.bankRevision === revision)
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))[0];
}
async function ensureAdaptivePrefetch(
  uid: string,
  passageId: string,
  revision: number,
  q: Q & { id: string },
  p: Progress
) {
  try {
    const existing = await latestAdaptivePrefetchMarker(
      uid,
      passageId,
      revision,
      q.id
    );
    if (existing) {
      try {
        const job = await learningPlatform.getAiJob(uid, existing.jobId);
        if (job.status === 'queued' || job.status === 'running' || job.status === 'completed')
          return existing.jobId;
      } catch {
        // A missing/failed job is safely replaced below.
      }
    }
    const targets = adaptiveTargetsForCurrent(q, p);
    const job = await learningPlatform.enqueueAiJob({
      kind: 'adaptive-prefetch',
      payload: {
        passageId,
        bankRevision: revision,
        sourceQuestionId: q.id,
        targets,
        recentAnswered: p.recentAnswered.slice(-12),
      },
      createdBy: uid,
      maxAttempts: 2,
    });
    await db.add(adaptivePrefetchTable(uid, passageId, revision), [
      {
        sourceQuestionId: q.id,
        jobId: job.id,
        bankRevision: revision,
        createdAt: new Date().toISOString(),
      } satisfies AdaptivePrefetchMarker,
    ]);
    return job.id;
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
async function readyAdaptiveQuestion(
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
  if (!marker) return undefined;
  let job: Awaited<ReturnType<typeof learningPlatform.getAiJob>>;
  try {
    job = await learningPlatform.getAiJob(uid, marker.jobId);
  } catch {
    return undefined;
  }
  if (job.status !== 'completed' || !job.result || typeof job.result !== 'object')
    return undefined;
  const result = job.result as Record<string, unknown>;
  const key = branch === 'success' ? 'successQuestionId' : 'recoveryQuestionId';
  const id = typeof result[key] === 'string' ? result[key] as string : '';
  if (!id) return undefined;
  const [q] = await db.get<Q>(adaptiveQuestionTable(uid, passageId, revision), [id]);
  if (!q || q.adaptiveOwnerUid !== uid || q.qualityVersion !== QUALITY_VERSION)
    return undefined;
  return { ...q, id } as Q & { id: string };
}
function adaptiveGeneratedIssues(
  q: Q,
  sourceText: string,
  existing: Array<Q & { id: string }>
) {
  const issues = [
    ...frozenProofIssues(q, sourceText),
    ...stemReadabilityIssues(q.stem),
  ];
  if (frozenUniqueLongest(q))
    issues.push('정답 길이 단서: 정답이 유일한 최장 선지');
  if (existing.some(old => sameGeneratedQuestion(old, q)))
    issues.push('기존 문항과 발문 또는 판단이 중복됨');
  return [...new Set(issues)];
}
function parseAdaptiveTargets(value: unknown): AdaptiveTarget[] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const out: AdaptiveTarget[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') return null;
    const item = raw as Record<string, unknown>;
    const branch = item.branch;
    const skill = item.skill;
    const level = item.level;
    const objective = item.objective;
    if (
      (branch !== 'success' && branch !== 'recovery') ||
      !skills.includes(skill as Skill) ||
      !levels.includes(level as Level) ||
      !objectives.includes(objective as Objective)
    ) return null;
    out.push({
      branch: branch as AdaptiveBranch,
      skill: skill as Skill,
      level: level as Level,
      objective: objective as Objective,
      misconception: typeof item.misconception === 'string'
        ? item.misconception.slice(0, 300)
        : '',
    });
  }
  if (new Set(out.map(item => item.branch)).size !== 2) return null;
  return out;
}
async function generateAdaptivePrefetch(
  uid: string,
  passageId: string,
  revision: number,
  sourceQuestionId: string,
  targets: AdaptiveTarget[]
) {
  const p = await getPassage(passageId);
  if (!p || !isPublishedBankCurrent(p) || currentBankRevision(p) !== revision)
    throw statusError('적응형 문항 생성 중 문제은행이 변경되었습니다.', 409);
  const sourceValidation = await validatePassageSource(p, false);
  if (sourceValidation.issues.length)
    throw statusError('적응형 출제 원문을 확인할 수 없습니다.', 409);
  const bank = usableQuestions(await listQuestions(passageId));
  const personal = await listAdaptiveQuestions(uid, passageId, revision);
  const existing = [...bank, ...personal];
  const [sourceQ] = await db.get<Q>(adaptiveQuestionTable(uid, passageId, revision), [sourceQuestionId]);
  const current = sourceQ
    ? ({ ...sourceQ, id: sourceQuestionId } as Q & { id: string })
    : bank.find(q => q.id === sourceQuestionId);
  if (!current) throw statusError('적응형 출제의 기준 문항을 찾을 수 없습니다.', 404);

  const targetPlan = targets.map((target, index) =>
    `문항 ${index + 1}: branch=${target.branch}, skill=${target.skill}, level=${target.level}, objective=${target.objective}, misconception=${target.misconception || '없음'}`
  ).join('\n');
  const recentStems = existing.slice(-30).map(q => q.stem);
  const data = await openAiStructured<{ questions: unknown[] }>({
    model: GPT_MODELS.generator,
    schemaName: 'adaptive_prefetch_questions_v1',
    schema: frozenCompactQuestionSchema(2),
    system: `${frozenGenerationPrompt(sourceValidation.content.text)}\n\n${FROZEN_ADAPTER_RULES}`,
    prompt: `학생 한 명의 다음 학습 분기를 위해 서로 다른 두 문항을 생성한다. 두 문항은 공개 문제은행 재고를 고르는 것이 아니라 이 학생을 위해 새로 만들어야 한다.\n\n[현재 문항]\n${JSON.stringify({ stem: current.stem, skill: current.skill, level: current.level, objective: current.objective, misconception: current.misconception })}\n\n[분기 목표]\n${targetPlan}\n\n- success 문항은 현재 문항을 맞혔을 때의 다음 학습 목표다. 현재 수준이 충분하면 더 높은 추론 부담이나 다른 취약 영역으로 이동한다.\n- recovery 문항은 현재 문항을 틀렸거나 모르겠다고 했을 때의 보완 목표다. 지정된 misconception을 직접 겨냥하되 정답을 암기하게 만드는 재진술 문제는 금지한다.\n- 두 문항 모두 현재 문항이나 아래 기존 발문을 단어만 바꿔 재사용하지 않는다.\n- L3는 FROZEN v7 기준의 서로 다른 원문 근거 3개와 생략 불가능한 판단 3단계를 실제로 요구한다.\n- 발문은 짧고 명료하게 유지하고, 난도는 근거 통합과 강한 오답 판별에서 만든다.\n- 정답이 유일하게 가장 긴 선지가 되지 않게 한다.\n- questions 배열 순서는 success, recovery 순서다.\n\n[최근/기존 발문 - 중복 금지]\n${JSON.stringify(recentStems)}\n\n[승인 지문]\n${sourceValidation.content.text}`,
    images: [],
    maxOutputTokens: 10000,
    reasoning: 'medium',
    timeoutMs: 100000,
  });
  const raw = Array.isArray(data.questions) ? data.questions : [];
  if (raw.length !== 2) throw statusError('적응형 생성 응답이 2문항이 아닙니다.', 502);
  const parsed = targets.map((target, index) =>
    frozenRawToQuestion(raw[index], target)
  );
  if (parsed.some(q => !q))
    throw statusError('적응형 생성 문항의 구조화 형식이 올바르지 않습니다.', 502);
  const candidates = parsed as Q[];
  const issueSets = candidates.map(q => adaptiveGeneratedIssues(q, sourceValidation.content.text, existing));
  if (issueSets.some(issues => issues.length))
    throw statusError(
      '적응형 생성 품질 게이트 미통과: ' + issueSets.map((issues, i) => `#${i + 1} ${issues.join(', ')}`).join(' / '),
      422
    );
  const accepted = candidates.map((q, index) => ({
    ...frozenAccepted(q),
    adaptiveOwnerUid: uid,
    adaptiveBranch: targets[index].branch,
    adaptiveSourceQuestionId: sourceQuestionId,
    adaptiveGeneratedAt: new Date().toISOString(),
  }));
  const ids = await db.add(adaptiveQuestionTable(uid, passageId, revision), accepted);
  if (ids.some(id => !id))
    throw statusError('학생 맞춤 문항 저장에 실패했습니다.', 500);
  return {
    successQuestionId: ids[0] as string,
    recoveryQuestionId: ids[1] as string,
    generatedCount: 2,
    adaptive: true,
  };
}

'''
s=s.replace(marker,helpers+marker,1)

# 3) Patch study start to include adaptive questions in current id validation and enqueue prefetch.
old="""            const revision = currentBankRevision(p);
            const longTermRows = await learningPlatform.getStudentMastery(uid);"""
new="""            const revision = currentBankRevision(p);
            const adaptiveQs = await listAdaptiveQuestions(uid, passageId, revision);
            const studyQs = [...qs, ...adaptiveQs];
            const longTermRows = await learningPlatform.getStudentMastery(uid);"""
assert s.count(old)==1, s.count(old)
s=s.replace(old,new,1)

old="""              new Set(qs.map(q => q.id)),
              masterySeed
            );"""
new="""              new Set(studyQs.map(q => q.id)),
              masterySeed
            );"""
assert s.count(old)==1, s.count(old)
s=s.replace(old,new,1)

old="""            let q = pr.currentQuestionId
              ? qs.find(x => x.id === pr.currentQuestionId)
              : undefined;
            if (!q) q = chooseNext(qs, pr);
            pr.currentQuestionId = q?.id || null;"""
new="""            let q = pr.currentQuestionId
              ? studyQs.find(x => x.id === pr.currentQuestionId)
              : undefined;
            if (!q) q = chooseNext(qs, pr);
            pr.currentQuestionId = q?.id || null;
            if (q)
              ctx.event.waitUntil(
                ensureAdaptivePrefetch(uid, passageId, revision, q, pr)
              );"""
assert s.count(old)==1, s.count(old)
s=s.replace(old,new,1)

# 4) Patch answer route to include adaptive questions and source-matched prefetched next.
old="""            const all = await listQuestions(passageId);
            const qs = usableQuestions(all);
            if (!complete(all))"""
assert s.count(old)>=1
pos=s.index("'POST /api/study/answer': [")
idx=s.index(old,pos)
s=s[:idx]+s[idx:].replace(old,"""            const all = await listQuestions(passageId);
            const qs = usableQuestions(all);
            const revision = currentBankRevision(p);
            const adaptiveQs = await listAdaptiveQuestions(uid, passageId, revision);
            const studyQs = [...qs, ...adaptiveQs];
            if (!complete(all))""",1)

pos=s.index("'POST /api/study/answer': [")
tail=s[pos:]
old="""            const revision = currentBankRevision(p);
            if (found.bankRevision !== revision)"""
assert tail.count(old)==1, tail.count(old)
tail=tail.replace(old,"""            if (found.bankRevision !== revision)""",1)
s=s[:pos]+tail

pos=s.index("'POST /api/study/answer': [")
tail=s[pos:]
old="""              new Set(qs.map(q => q.id))
            );"""
assert tail.count(old)>=1, tail.count(old)
tail=tail.replace(old,"""              new Set(studyQs.map(q => q.id))
            );""",1)
s=s[:pos]+tail

pos=s.index("'POST /api/study/answer': [")
tail=s[pos:]
old="""            const q = qs.find(question => question.id === questionId);
            if (!q) return error('검증된 문항을 찾을 수 없습니다.', 404);"""
assert tail.count(old)==1
tail=tail.replace(old,"""            const q = studyQs.find(question => question.id === questionId);
            if (!q) return error('검증된 문항을 찾을 수 없습니다.', 404);""",1)
s=s[:pos]+tail

pos=s.index("'POST /api/study/answer': [")
tail=s[pos:]
old="""              const next = pr.lastSubmission.nextQuestionId
                ? qs.find(
                    question =>
                      question.id === pr.lastSubmission!.nextQuestionId
                  )
                : undefined;"""
assert tail.count(old)==1
tail=tail.replace(old,"""              const next = pr.lastSubmission.nextQuestionId
                ? studyQs.find(
                    question =>
                      question.id === pr.lastSubmission!.nextQuestionId
                  )
                : undefined;""",1)
s=s[:pos]+tail

pos=s.index("'POST /api/study/answer': [")
tail=s[pos:]
old="""            const next = done ? undefined : chooseNext(qs, pr);
            pr.currentQuestionId = next?.id || null;"""
assert tail.count(old)==1
tail=tail.replace(old,"""            let next: (Q & { id: string }) | undefined;
            if (!done) {
              const branch: AdaptiveBranch = isCorrect ? 'success' : 'recovery';
              next = await readyAdaptiveQuestion(
                uid,
                passageId,
                revision,
                questionId,
                branch
              );
              if (!next) next = chooseNext(qs, pr);
            }
            pr.currentQuestionId = next?.id || null;
            if (next)
              ctx.event.waitUntil(
                ensureAdaptivePrefetch(uid, passageId, revision, next, pr)
              );""",1)
s=s[:pos]+tail

# 5) Add worker-only adaptive route before study/start routes.
route_marker="""  'POST /api/study/start': ["""
assert s.count(route_marker)==1
route=r'''  'POST /api/worker/adaptive-prefetch': [
    requireAuth(),
    async ctx => {
      const expectedSecret = runtimeSetting('AI_WORKER_SECRET');
      const providedSecret = ctx.event.request.headers.get('x-ai-worker-secret') || '';
      if (!expectedSecret || providedSecret !== expectedSecret)
        return error('worker unauthorized', 401);
      const b = requestBody<{
        passageId?: unknown;
        bankRevision?: unknown;
        sourceQuestionId?: unknown;
        targets?: unknown;
      }>(ctx.body);
      if (
        typeof b.passageId !== 'string' ||
        typeof b.sourceQuestionId !== 'string' ||
        typeof b.bankRevision !== 'number' ||
        !Number.isInteger(b.bankRevision)
      ) return error('적응형 작업 형식이 올바르지 않습니다.', 400);
      const targets = parseAdaptiveTargets(b.targets);
      if (!targets) return error('적응형 분기 목표 형식이 올바르지 않습니다.', 400);
      try {
        const result = await generateAdaptivePrefetch(
          ctx.user!.userId,
          b.passageId,
          b.bankRevision,
          b.sourceQuestionId,
          targets
        );
        return json(result);
      } catch (e) {
        return operationErrorResponse(e);
      }
    },
  ],

'''
s=s.replace(route_marker,route+route_marker,1)

required=[
    "ADAPTIVE_GENERATION_VERSION",
    "kind: 'adaptive-prefetch'",
    "'POST /api/worker/adaptive-prefetch': [",
    "readyAdaptiveQuestion(",
    "ensureAdaptivePrefetch(",
    "adaptiveQuestionTable(",
    "generateAdaptivePrefetch(",
]
for r in required:
    assert r in s, r

p.write_text(s,encoding='utf-8')
print('Applied adaptive generation prefetch v1', len(s))
