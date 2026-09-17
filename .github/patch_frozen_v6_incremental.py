from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

marker = """function frozenSetTargets(): BuildTarget[] {
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
"""
if s.count(marker) != 1:
    raise SystemExit(f'frozenSetTargets marker count={s.count(marker)}')
helper = marker + """
function frozenMissingTargets(qs: Array<Q & { id: string }>): BuildTarget[] {
  const counts = new Map<string, number>();
  for (const q of usableQuestions(qs)) {
    const key = `${q.skill}:${q.level}:${q.objective}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return frozenSetTargets().filter(target => {
    const key = `${target.skill}:${target.level}:${target.objective || 'integration'}`;
    const count = counts.get(key) || 0;
    if (count > 0) {
      counts.set(key, count - 1);
      return false;
    }
    return true;
  });
}
"""
s = s.replace(marker, helper, 1)

old = """- 전체 ${targets.length}문항은 5문항짜리 내부 세트 5개로 본다. 각 내부 세트에는 content, logic, inference, comparison, application이 각각 1문항씩 있다.
- 각 내부 세트마다 부정형 발문은 정확히 1문항만 사용한다. 단순히 긍정형 문장의 어미만 뒤집지 말고 실제 판단 과업이 부정형이어야 한다.
- 정답 번호는 전체 25문항에서 1~5가 각각 대체로 5회가 되게 하고, 가능하면 각 내부 세트에서도 1~5를 한 번씩 사용한다. 정답 위치를 맞추려고 의미를 훼손하지 않는다.
- 정답 선지가 유일한 최장 선지가 되는 문항은 전체 5개 이하로 제한한다. 길이 맞추기용 패딩은 금지한다."""
new = """- 전체 ${targets.length}문항은 같은 level/objective를 공유하는 5문항 묶음 ${Math.ceil(targets.length / 5)}개로 설계한다. 완전한 5문항 묶음에는 content, logic, inference, comparison, application이 각각 1문항씩 있다.
- 각 완전한 5문항 묶음마다 부정형 발문은 정확히 1문항만 사용한다. 단순히 긍정형 문장의 어미만 뒤집지 말고 실제 판단 과업이 부정형이어야 한다.
- 각 완전한 5문항 묶음에서 정답 번호 1~5를 가능하면 한 번씩 사용한다. 정답 위치를 맞추려고 의미를 훼손하지 않는다.
- 정답 선지가 유일한 최장 선지가 되는 문항은 이번 생성분 전체에서 최대 ${Math.max(1, Math.floor(targets.length * 0.2))}개로 제한한다. 길이 맞추기용 패딩은 금지한다."""
if s.count(old) != 1:
    raise SystemExit(f'variable batch prompt marker count={s.count(old)}')
s = s.replace(old, new, 1)

# New builds should create only missing current-version targets. This lets us keep good
# L1/L2 questions and replace only deficient L3 questions with a single model call.
old_targets = """    const targets = frozenSetTargets();
    const job: BuildJob = {"""
new_targets = """    const targets = frozenMissingTargets(existing);
    if (!targets.length) {
      const result = await makeBuildResult(passageId, 0, 0, 0, 0);
      return json({ ...result, complete: true, bankComplete: result.complete, pipelineComplete: true, apiCallsMaximum: 0 });
    }
    const job: BuildJob = {"""
if s.count(old_targets) != 1:
    raise SystemExit(f'new build targets marker count={s.count(old_targets)}')
s = s.replace(old_targets, new_targets, 1)

old_resume = """        targetCount: resumed.targets?.length || FROZEN_SET_QUESTION_COUNT,
        apiPlan: 'one-call-frozen-set',"""
new_resume = """        targetCount: resumed.targets?.length || frozenMissingTargets(existing).length || FROZEN_SET_QUESTION_COUNT,
        apiPlan: 'one-call-frozen-set',"""
if s.count(old_resume) != 1:
    raise SystemExit(f'resume target count marker count={s.count(old_resume)}')
s = s.replace(old_resume, new_resume, 1)

required = [
    'function frozenMissingTargets',
    'const targets = frozenMissingTargets(existing);',
    'Math.ceil(targets.length / 5)',
    'Math.floor(targets.length * 0.2)',
]
for item in required:
    if item not in s:
        raise SystemExit(f'missing incremental v6 marker: {item}')

path.write_text(s, encoding='utf-8')
print('Applied incremental FROZEN v6 missing-target generation')
