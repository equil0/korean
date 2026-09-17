from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

replacements = [
    ("const QUALITY_VERSION = 'v10.11-frozen-adaptive-v1';", "const QUALITY_VERSION = 'v10.11-frozen-adaptive-v2';"),
    ("const BUILD_ENGINE_VERSION = 'v10.11-frozen-batched-v1';", "const BUILD_ENGINE_VERSION = 'v10.11-frozen-batched-v2';"),
    ("const QUESTION_ENGINE_VERSION = 'v10.11-frozen-adapter-v1';", "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-adapter-v2';"),
]
for old, new in replacements:
    if s.count(old) != 1:
        raise SystemExit(f'expected exactly one version marker: {old!r}, got {s.count(old)}')
    s = s.replace(old, new, 1)

marker = 'function bankQualityIssues(qs: Array<Q & { id: string }>) {'
if s.count(marker) != 1:
    raise SystemExit(f'bankQualityIssues marker count={s.count(marker)}')

helper = r'''
function frozenBankGenerationPlan(
  qs: Array<Q & { id: string }>,
  batchSize: number
) {
  const usable = usableQuestions(qs);
  const total = usable.length;
  const projected = total + Math.max(1, batchSize);
  const negativeCount = usable.filter(q => negativeStem(q.stem)).length;
  const desiredNegative = Math.ceil(projected * 0.26);
  let negativeNeeded = Math.max(0, Math.min(batchSize, desiredNegative - negativeCount));
  const currentNegativeRatio = total ? negativeCount / total : 0;
  if (total >= 5 && currentNegativeRatio >= 0.36) negativeNeeded = 0;
  if (total >= 10 && currentNegativeRatio >= 0.22 && currentNegativeRatio < 0.36)
    negativeNeeded = Math.min(1, negativeNeeded);

  let uniqueLongest = 0;
  for (const q of usable) {
    const lengths = q.choices.map(choice => choice.replace(/\s/g, '').length);
    const max = Math.max(...lengths);
    if (
      lengths[q.answer - 1] === max &&
      lengths.filter(length => length === max).length === 1
    )
      uniqueLongest += 1;
  }
  const maxUniqueLongestAfter = Math.floor(projected * 0.2);
  const uniqueLongestAllowance = Math.max(
    0,
    Math.min(batchSize, maxUniqueLongestAfter - uniqueLongest)
  );

  const cellCounts = new Map<string, number>();
  const skillCounts = Object.fromEntries(
    skills.map(skill => [skill, 0])
  ) as Record<Skill, number>;
  for (const q of usable) {
    skillCounts[q.skill] += 1;
    const key = `${q.skill}:${q.level}`;
    cellCounts.set(key, (cellCounts.get(key) || 0) + 1);
  }
  const missingCells = skills.flatMap(skill =>
    levels
      .filter(level => !cellCounts.get(`${skill}:${level}`))
      .map(level => `${skill}:${level}`)
  );
  const thinSkills = skills
    .filter(skill => skillCounts[skill] < 4)
    .map(skill => `${skill}=${skillCounts[skill]}`);

  return `[현재 문제은행 FROZEN 전역 상태]\n` +
    `활성 검증 문항 ${total}개, 부정형 ${negativeCount}개, 정답 유일 최장 ${uniqueLongest}개.\n` +
    `이번 ${batchSize}문항 배치에서는 의미상 자연스러운 부정형(N)을 ${negativeNeeded}개 설계하라. ` +
    `단순히 '적절한'을 '적절하지 않은'으로 뒤집지 말고, 내용 불일치·근거 부족·추론 불가·적용 오류·관점 귀속 오류처럼 실제 부정형 판단 과업을 사용하라. ` +
    `같은 위치나 같은 표현에 부정형을 기계적으로 반복 배치하지 마라.\n` +
    `이번 배치에서 정답이 유일한 최장 선지가 되는 문항은 최대 ${uniqueLongestAllowance}개다. ` +
    `길이를 맞추기 위한 오답 패딩은 금지하며, 정답의 불필요한 해설형 표현을 압축하고 near-miss 오답의 의미 밀도를 높여라.\n` +
    `아직 비어 있는 skill:level 조합: ${missingCells.length ? missingCells.join(', ') : '없음'}. ` +
    `4문항 미만 영역: ${thinSkills.length ? thinSkills.join(', ') : '없음'}. ` +
    `서버가 지정한 이번 target을 우선 지키고, 특히 빈 조합과 부족 영역을 다른 영역으로 흘려보내지 마라.\n` +
    `발문은 한 번 읽고 질문 대상을 즉시 파악할 수 있는 간결한 한 문장을 원칙으로 한다. ` +
    `난도는 발문 문법을 꼬아서 만들지 말고 근거 결합·조건 비교·선지 판별에서 만들어라. ` +
    `'~이라는 기준으로 ~하는 방식'처럼 추상 명사와 관형절이 중첩되는 표현은 피하라.`;
}

'''
s = s.replace(marker, helper + marker, 1)

old = '공통 규칙: misconception에는 가장 매력적인 오답을 고르게 되는 문항 고유의 구체적인 근거 오독을 적는다.'
new = '${frozenBankGenerationPlan(existing, batchTargets.length)}\\\n\\\n공통 규칙: misconception에는 가장 매력적인 오답을 고르게 되는 문항 고유의 구체적인 근거 오독을 적는다.'
if s.count(old) != 1:
    raise SystemExit(f'generation common-rules marker count={s.count(old)}')
s = s.replace(old, new, 1)

old2 = '발문을 길게 하는 데 그치지 말고 실제로 근거를 연결해야 풀리게 한다. 발문은 보기를 포함해 650자 이내, 선택지는 각각 180자 이내에서 필요한 정보만 쓴다.'
new2 = '발문을 길게 하는 데 그치지 말고 실제로 근거를 연결해야 풀리게 한다. 발문은 원칙적으로 한 문장으로, 학생이 한 번 읽고 무엇을 묻는지 바로 알 수 있게 쓴다. 난도는 발문의 문장 구조가 아니라 근거 통합과 선지 판단에서 만든다. 추상 명사와 2중 관형절을 겹치지 않는다. 발문은 보기를 포함해 650자 이내, 선택지는 각각 180자 이내에서 필요한 정보만 쓴다.'
if s.count(old2) != 1:
    raise SystemExit(f'readability marker count={s.count(old2)}')
s = s.replace(old2, new2, 1)

path.write_text(s, encoding='utf-8')

check = path.read_text(encoding='utf-8')
required = [
    'v10.11-frozen-adaptive-v2',
    'v10.11-frozen-adapter-v2',
    'function frozenBankGenerationPlan',
    'frozenBankGenerationPlan(existing, batchTargets.length)',
    '이번 배치에서 정답이 유일한 최장 선지가 되는 문항',
]
for item in required:
    if item not in check:
        raise SystemExit(f'missing patched marker: {item}')
print('FROZEN v2 convergence patch applied')
