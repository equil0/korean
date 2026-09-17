from pathlib import Path

path = Path('v66-backend/backend/index.ts')
s = path.read_text(encoding='utf-8')

repls = [
    ("const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v5';", "const QUALITY_VERSION = 'v10.11-frozen-set-adaptive-v6';"),
    ("const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v5';", "const BUILD_ENGINE_VERSION = 'v10.11-frozen-set-build-v6';"),
    ("const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v5';", "const QUESTION_ENGINE_VERSION = 'v10.11-frozen-set-v6';"),
    ("schemaName: 'frozen_set_questions_v5',", "schemaName: 'frozen_set_questions_v6',"),
    ("QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v5'", "QUESTION_ENGINE_VERSION === 'v10.11-frozen-set-v6'"),
]
for old, new in repls:
    if s.count(old) != 1:
        raise SystemExit(f'marker mismatch {old!r}: {s.count(old)}')
    s = s.replace(old, new, 1)

old_prompt = """- L1은 핵심 정보·조건 확인, L2는 서로 다른 근거의 연결, L3는 여러 조건과 근거를 결합한 판단을 요구한다.
- skill/level/objective는 적응형 선택을 위한 설계 목표다. 각 문항은 지정된 목표에 맞게 설계한다."""
new_prompt = """- L1은 핵심 정보·조건 확인, L2는 서로 다른 원문 근거 2개를 연결해야 풀리게 한다.
- L3는 반드시 서로 다른 원문 근거 3개 이상을 결합하고, 생략할 수 없는 판단을 3단계 이상 거쳐야 정답을 고를 수 있게 한다. 한 문장·한 문단·한 요약문만 찾아도 풀리면 L3가 아니다.
- L3에서는 '중심 생각/주제', 단순 일치·불일치, 단순 순서, '모두 포함한 것은', 한 문장의 이유 찾기, 원문 한 구절과 정답의 직접 대응을 금지한다.
- L3 content는 서로 떨어진 세 정보의 범위·조건을 동시에 만족하는 종합 선지를 고르게 한다.
- L3 logic은 둘 이상의 관계와 예외·전제·조건을 연결한 뒤 마지막 조건에서 선지를 가르게 한다.
- L3 inference는 원문에 직접 쓰이지 않은 결론을 세 근거로 도출하게 하며, 정답 문장을 원문에서 그대로 찾을 수 없게 한다.
- L3 comparison은 두 대상의 공통점/차이 하나를 찾는 문제가 아니라 공통 기준 아래 여러 속성과 조건을 교차 비교하게 한다.
- L3 application은 <보기>에 최소 세 조건을 주고, 원문의 둘 이상의 원리를 동시에 적용해야 한다. 단순히 잘못된 표현 하나나 수정 항목 체크리스트를 찾는 문제는 금지한다.
- 모든 L3 문항에는 정답과 최소 두 근거를 공유하는 강한 오답을 둔다. 그 오답은 결정 조건 하나만 어겨야 하며, 과장어·상식·선지 길이만으로 제거할 수 없어야 한다.
- difficultyEvidence에는 실제 원문에서 짧게 그대로 옮긴 서로 다른 필수 근거를 기록한다. L1은 1개 이상, L2는 2개 이상, L3는 정확히 3개를 사용한다.
- reasoningSteps에는 학생이 실제로 해야 하는 서로 다른 판단을 기록한다. L1은 1개 이상, L2는 2개 이상, L3는 정확히 3개다. '지문 읽기/선지 고르기/정답 확인'은 판단 단계가 아니다.
- strongestDistractor에는 가장 경쟁력 있는 오답 번호를, decisiveDifference에는 그 오답과 정답을 마지막에 가르는 원문 조건을 짧게 적는다.
- 출력 직전에 L3 10문항 각각에 대해 '근거 3개가 실제로 서로 다른가 → 판단 3단계가 생략 불가능한가 → 강한 오답이 정답과 근거를 공유하는가 → 한 문장 검색으로 풀리지 않는가'를 내부 검수하고 하나라도 아니면 문항을 다시 설계한다.
- skill/level/objective는 적응형 선택을 위한 설계 목표다. 각 문항은 지정된 목표에 맞게 설계한다."""
if s.count(old_prompt) != 1:
    raise SystemExit(f'prompt difficulty marker count={s.count(old_prompt)}')
s = s.replace(old_prompt, new_prompt, 1)

old_props = """            evidence: { type: 'string', minLength: 3, maxLength: 500 },
          },
          required: ['stem', 'choices', 'answer', 'explanation', 'misconception', 'evidence'],"""
new_props = """            evidence: { type: 'string', minLength: 3, maxLength: 500 },
            difficultyEvidence: {
              type: 'array',
              minItems: 1,
              maxItems: 3,
              items: { type: 'string', minLength: 3, maxLength: 180 },
            },
            reasoningSteps: {
              type: 'array',
              minItems: 1,
              maxItems: 3,
              items: { type: 'string', minLength: 3, maxLength: 220 },
            },
            strongestDistractor: { type: 'integer', enum: [1, 2, 3, 4, 5] },
            decisiveDifference: { type: 'string', minLength: 3, maxLength: 300 },
          },
          required: ['stem', 'choices', 'answer', 'explanation', 'misconception', 'evidence', 'difficultyEvidence', 'reasoningSteps', 'strongestDistractor', 'decisiveDifference'],"""
if s.count(old_props) != 1:
    raise SystemExit(f'schema marker count={s.count(old_props)}')
s = s.replace(old_props, new_props, 1)

old_parse = """    typeof value.explanation !== 'string' ||
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
  };"""
new_parse = """    typeof value.explanation !== 'string' ||
    typeof value.misconception !== 'string' ||
    typeof value.evidence !== 'string' ||
    !Array.isArray(value.difficultyEvidence) ||
    !Array.isArray(value.reasoningSteps) ||
    typeof value.decisiveDifference !== 'string'
  ) return null;
  const difficultyEvidence = value.difficultyEvidence
    .map(item => typeof item === 'string' ? item.trim() : '')
    .filter(Boolean)
    .slice(0, 3);
  const reasoningSteps = value.reasoningSteps
    .map(item => typeof item === 'string' ? item.trim() : '')
    .filter(Boolean)
    .slice(0, 3);
  const strongestDistractor = Number(value.strongestDistractor);
  if (!Number.isInteger(strongestDistractor) || strongestDistractor < 1 || strongestDistractor > 5 || strongestDistractor === answer)
    return null;
  const decisiveDifference = value.decisiveDifference.trim();
  if (!difficultyEvidence.length || !reasoningSteps.length || !decisiveDifference) return null;
  return {
    design: {
      answerability: 'supported',
      limitation: '',
      evidenceQuotes: difficultyEvidence,
      sourceRelation: decisiveDifference,
      decisiveCondition: decisiveDifference,
      reasoningSteps,
      distractors: [{
        choice: strongestDistractor,
        sourceTruth: '정답과 일부 원문 근거를 공유함',
        misreading: value.misconception.trim(),
      }],
    },
    stem: value.stem.trim(),
    choices,
    answer,
    explanation: value.explanation.trim(),
    misconception: value.misconception.trim(),
    evidence: value.evidence.trim(),
    skill: target.skill,
    level: target.level,
    objective: target.objective || 'integration',
  };"""
if s.count(old_parse) != 1:
    raise SystemExit(f'raw parser marker count={s.count(old_parse)}')
s = s.replace(old_parse, new_parse, 1)

old_difficulty = """function frozenDifficultyFor(q: Q): DifficultyReview {
  const steps = q.explanation
    .split(/(?<=[.!?。])\\s+|\\n+/)
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
}"""
new_difficulty = """function frozenDifficultyFor(q: Q): DifficultyReview {
  const steps = q.design?.reasoningSteps?.filter(Boolean).slice(0, 3) || [];
  const evidenceQuotes = q.design?.evidenceQuotes?.filter(Boolean).slice(0, 3) || [];
  return {
    observedSkill: q.skill,
    observedLevel: q.level,
    singleFactRetrieval: q.level === 'L1' && steps.length <= 1,
    answerCued: false,
    reasoningSteps: steps.length ? steps : [q.explanation.slice(0, 180)],
    evidenceQuotes: evidenceQuotes.length ? evidenceQuotes : [q.evidence],
    decisiveCondition: q.design?.decisiveCondition || q.misconception || '원문의 결정적 조건과 적용 범위를 구별한다.',
    levelRationale: 'v10.11 FROZEN v6 난도 증명 필드(필수 근거·실제 판단 단계)를 기준으로 저장한 적응형 메타데이터',
  };
}"""
if s.count(old_difficulty) != 1:
    raise SystemExit(f'difficulty marker count={s.count(old_difficulty)}')
s = s.replace(old_difficulty, new_difficulty, 1)

old_filter = """      if (!q.explanation.trim()) return false;
      return true;
    })"""
new_filter = """      if (!q.explanation.trim()) return false;
      const proof = q.design;
      if (!proof) return false;
      const required = q.level === 'L3' ? 3 : q.level === 'L2' ? 2 : 1;
      const evidenceQuotes = proof.evidenceQuotes.map(item => normalizeOldHangul(item).trim()).filter(Boolean);
      const reasoningSteps = proof.reasoningSteps.map(item => item.trim()).filter(Boolean);
      if (evidenceQuotes.length < required || reasoningSteps.length < required) return false;
      if (new Set(evidenceQuotes.map(item => stemKey(item))).size < required) return false;
      if (new Set(reasoningSteps.map(item => stemKey(item))).size < required) return false;
      const source = normalizeOldHangul(assets.content.text);
      if (evidenceQuotes.slice(0, required).some(quote => !source.includes(quote))) return false;
      if (q.level === 'L3' && /(?:중심 생각|중심 내용|주제|모두 포함|이동 순서|구성 순서|제시된 .*모두|이유로 가장 적절|이유는\\?|알 수 있는 것은\\?|성격으로 가장 적절)/.test(q.stem)) return false;
      if (q.level === 'L3' && (proof.distractors?.[0]?.choice === q.answer || !proof.decisiveCondition.trim())) return false;
      return true;
    })"""
if s.count(old_filter) != 1:
    raise SystemExit(f'one-call acceptance filter marker count={s.count(old_filter)}')
s = s.replace(old_filter, new_filter, 1)

# Use the model-provided strongest distractor in stored verification instead of an arbitrary choice.
old_strongest = """  const difficulty = frozenDifficultyFor(q);
  const strongest = q.answer === 1 ? 2 : 1;"""
new_strongest = """  const difficulty = frozenDifficultyFor(q);
  const strongest = q.design?.distractors?.find(item => item.choice !== q.answer)?.choice || (q.answer === 1 ? 2 : 1);"""
if s.count(old_strongest) != 1:
    raise SystemExit(f'strongest distractor marker count={s.count(old_strongest)}')
s = s.replace(old_strongest, new_strongest, 1)

# Make the stored model labels current.
s = s.replace("'not-used:frozen-set-v4'", "'not-used:frozen-set-v6'")
s = s.replace("'v10.11 FROZEN 세트 생성과 일괄 QA를 통과함'", "'v10.11 FROZEN v6 자체검수 및 난도 증명 게이트를 통과함'")

required_markers = [
    "v10.11-frozen-set-adaptive-v6",
    "v10.11-frozen-set-v6",
    "difficultyEvidence",
    "L3는 반드시 서로 다른 원문 근거 3개 이상",
    "const required = q.level === 'L3' ? 3",
    "난도 증명 필드",
]
for item in required_markers:
    if item not in s:
        raise SystemExit(f'missing v6 marker: {item}')

path.write_text(s, encoding='utf-8')
print('Applied FROZEN v6 genuine difficulty proof gates')
