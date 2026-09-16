import { createClient, type SupabaseClient } from '@supabase/supabase-js';

type AuthUser = {
  userId: string;
  email?: string;
  name?: string;
  scope: string;
};

type RouterContext = {
  body: unknown;
  query: Record<string, string>;
  params: Record<string, string>;
  event: {
    request: Request;
    waitUntil: (promise: Promise<unknown>) => void;
  };
  user?: AuthUser;
};

type Middleware = (
  context: RouterContext
) => Promise<Response | void> | Response | void;
type Routes = Record<string, Middleware[]>;

const RECORDS_TABLE = 'engine_records';
const STORAGE_BUCKET = 'engine-private';

function runtimeEnv(name: string) {
  const runtime = globalThis as unknown as {
    Deno?: { env?: { get?: (key: string) => string | undefined } };
    process?: { env?: Record<string, string | undefined> };
  };
  return runtime.Deno?.env?.get?.(name) || runtime.process?.env?.[name];
}

export function runtimeSetting(name: string) {
  return (runtimeEnv(name) || '').trim();
}

function defaultKey(value: string | undefined) {
  if (!value) return '';
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    return typeof parsed.default === 'string' ? parsed.default : '';
  } catch {
    return '';
  }
}

let cachedAdmin: SupabaseClient | null = null;
function admin() {
  if (cachedAdmin) return cachedAdmin;
  const url = runtimeEnv('SUPABASE_URL');
  const key =
    defaultKey(runtimeEnv('SUPABASE_SECRET_KEYS')) ||
    runtimeEnv('SUPABASE_SERVICE_ROLE_KEY');
  if (!url || !key)
    throw Object.assign(
      new Error('Supabase 서버 키가 설정되지 않았습니다.'),
      { statusCode: 503 }
    );
  cachedAdmin = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return cachedAdmin;
}

function storedRecord(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
  const { id: _ignored, ...record } = value as Record<string, unknown>;
  return record;
}

function rowRecord<T>(row: { id: string; record_json: unknown }) {
  const record =
    typeof row.record_json === 'string'
      ? (JSON.parse(row.record_json) as T)
      : (row.record_json as T);
  return { ...(record as object), id: row.id } as T & { id: string };
}

export const db = {
  async add<T>(table: string, records: T[]): Promise<Array<string | null>> {
    const out: Array<string | null> = [];
    for (const record of records) {
      const id = crypto.randomUUID();
      const { error: insertError } = await admin()
        .from(RECORDS_TABLE)
        .insert({
          table_name: table,
          id,
          record_json: storedRecord(record),
          created_at: Date.now(),
        });
      if (insertError) {
        console.error('[db-add]', { table, message: insertError.message });
        out.push(null);
      } else out.push(id);
    }
    return out;
  },

  async get<T>(table: string, ids: string[]): Promise<Array<T | null>> {
    if (!ids.length) return [];
    const { data, error: selectError } = await admin()
      .from(RECORDS_TABLE)
      .select('id, record_json')
      .eq('table_name', table)
      .in('id', ids);
    if (selectError) throw selectError;
    const byId = new Map(
      (data || []).map(row => {
        const parsed = rowRecord<T>(row);
        return [row.id, parsed] as const;
      })
    );
    return ids.map(id => (byId.get(id) as T | undefined) || null);
  },

  async list<T>(
    table: string,
    options: { limit?: number; nextToken?: string } = {}
  ): Promise<{ items: Array<T & { id: string }>; nextToken?: string }> {
    const limit = Math.max(1, Math.min(1000, options.limit || 100));
    const parsedOffset = Number.parseInt(options.nextToken || '0', 10);
    const offset =
      Number.isFinite(parsedOffset) && parsedOffset >= 0 ? parsedOffset : 0;
    const { data, error: selectError } = await admin()
      .from(RECORDS_TABLE)
      .select('id, record_json')
      .eq('table_name', table)
      .order('created_at', { ascending: true })
      .order('id', { ascending: true })
      .range(offset, offset + limit - 1);
    if (selectError) throw selectError;
    const rows = data || [];
    return {
      items: rows.map(row => rowRecord<T>(row)),
      nextToken:
        rows.length === limit ? String(offset + rows.length) : undefined,
    };
  },

  async update<T>(
    table: string,
    updates: Array<{ id: string; record: T }>
  ): Promise<boolean[]> {
    const out: boolean[] = [];
    for (const update of updates) {
      const { data, error: updateError } = await admin()
        .from(RECORDS_TABLE)
        .update({ record_json: storedRecord(update.record) })
        .eq('table_name', table)
        .eq('id', update.id)
        .select('id');
      if (updateError)
        console.error('[db-update]', {
          table,
          id: update.id,
          message: updateError.message,
        });
      out.push(!updateError && !!data?.length);
    }
    return out;
  },

  async delete(table: string, ids: string[]): Promise<boolean[]> {
    const out: boolean[] = [];
    for (const id of ids) {
      const { data, error: deleteError } = await admin()
        .from(RECORDS_TABLE)
        .delete()
        .eq('table_name', table)
        .eq('id', id)
        .select('id');
      if (deleteError)
        console.error('[db-delete]', {
          table,
          id,
          message: deleteError.message,
        });
      out.push(!deleteError && !!data?.length);
    }
    return out;
  },
};

export const secrets = {
  async readSecret(name: string) {
    const value = runtimeEnv(name);
    if (!value)
      throw Object.assign(new Error(`${name} secret is not configured.`), {
        statusCode: 503,
      });
    return value;
  },
};

export const storage = {
  async write(
    items: Array<{ path: string; content: string; contentType?: string }>
  ) {
    return await Promise.all(
      items.map(async item => {
        const { error: uploadError } = await admin()
          .storage.from(STORAGE_BUCKET)
          .upload(item.path, new TextEncoder().encode(item.content), {
            contentType: item.contentType || 'application/octet-stream',
            upsert: true,
          });
        if (uploadError)
          console.error('[storage-write]', {
            path: item.path,
            message: uploadError.message,
          });
        return !uploadError;
      })
    );
  },

  async read(paths: string[]) {
    return await Promise.all(
      paths.map(async path => {
        const { data, error: downloadError } = await admin()
          .storage.from(STORAGE_BUCKET)
          .download(path);
        if (downloadError || !data)
          return { path, content: null, contentType: undefined };
        return {
          path,
          content: await data.text(),
          contentType: data.type || undefined,
        };
      })
    );
  },

  async delete(paths: string[]) {
    if (!paths.length) return [];
    const { error: removeError } = await admin()
      .storage.from(STORAGE_BUCKET)
      .remove(paths);
    if (removeError)
      console.error('[storage-delete]', { message: removeError.message });
    return paths.map(() => !removeError);
  },

  async list(options: { prefix?: string; limit?: number; nextToken?: string }) {
    const prefix = (options.prefix || '').replace(/\/$/, '');
    const limit = Math.max(1, Math.min(1000, options.limit || 100));
    const parsedOffset = Number.parseInt(options.nextToken || '0', 10);
    const offset =
      Number.isFinite(parsedOffset) && parsedOffset >= 0 ? parsedOffset : 0;
    const { data, error: listError } = await admin()
      .storage.from(STORAGE_BUCKET)
      .list(prefix, {
        limit,
        offset,
        sortBy: { column: 'name', order: 'asc' },
      });
    if (listError) throw listError;
    const rows = (data || []).filter(item => item.id);
    return {
      paths: rows.map(item => (prefix ? `${prefix}/${item.name}` : item.name)),
      nextToken:
        rows.length === limit ? String(offset + rows.length) : undefined,
    };
  },
};


type StudentMasteryRow = {
  skill: string;
  mastery: number;
  attempts: number;
  correct: number;
};

type AssignmentAccess = {
  assignmentId: string;
  classId: string;
  className: string;
  passageId: string;
  title: string;
  startsAt: string;
  dueAt: string | null;
};

function platformFailure(stage: string, message: string, statusCode = 503) {
  return Object.assign(new Error(`${stage}: ${message}`), { statusCode });
}

function cleanDisplayName(value: string | undefined) {
  return (value || '').replace(/\s+/g, ' ').trim().slice(0, 80);
}

function classJoinCode() {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, byte => alphabet[byte % alphabet.length]).join('');
}


async function syncLearningProfile(userId: string, displayName?: string) {
  const name = cleanDisplayName(displayName);
  const { error: upsertError } = await admin()
    .from('learning_profiles')
    .upsert(
      {
        user_id: userId,
        display_name: name,
        updated_at: new Date().toISOString(),
      },
      { onConflict: 'user_id' }
    );
  if (upsertError)
    throw platformFailure('프로필 저장', upsertError.message);
}

/**
 * Normalized deployment data for learning_classes, learning_assignments and analytics.
 * The legacy question engine remains in engine_records; these tables are the
 * student-distribution layer and are safe to evolve independently.
 */
export const learningPlatform = {
  async syncProfile(userId: string, displayName?: string) {
    await syncLearningProfile(userId, displayName);
  },

  async createClass(teacherId: string, name: string) {
    const className = name.replace(/\s+/g, ' ').trim().slice(0, 120);
    if (!className) throw platformFailure('학급 생성', '학급명이 필요합니다.', 400);
    for (let attempt = 0; attempt < 8; attempt++) {
      const joinCode = classJoinCode();
      const { data, error: insertError } = await admin()
        .from('learning_classes')
        .insert({
          teacher_id: teacherId,
          name: className,
          join_code: joinCode,
          is_active: true,
        })
        .select('id, name, join_code, is_active, created_at')
        .single();
      if (!insertError && data) return data;
      if (insertError?.code === '23505') continue;
      throw platformFailure('학급 생성', insertError?.message || '저장 실패');
    }
    throw platformFailure('학급 생성', '학급 코드를 만들지 못했습니다. 다시 시도해 주세요.');
  },

  async listTeacherClasses(teacherId: string) {
    const { data, error: selectError } = await admin()
      .from('learning_classes')
      .select('id, name, join_code, is_active, created_at, updated_at')
      .eq('teacher_id', teacherId)
      .order('created_at', { ascending: false });
    if (selectError) throw platformFailure('학급 목록', selectError.message);
    return data || [];
  },

  async classRoster(teacherId: string, classId: string) {
    const { data: cls, error: classError } = await admin()
      .from('learning_classes')
      .select('id')
      .eq('id', classId)
      .eq('teacher_id', teacherId)
      .maybeSingle();
    if (classError) throw platformFailure('학급 확인', classError.message);
    if (!cls) throw platformFailure('학급 확인', '담당 학급을 찾을 수 없습니다.', 404);
    const { data, error: memberError } = await admin()
      .from('learning_class_members')
      .select('student_id, display_name, status, joined_at, updated_at')
      .eq('class_id', classId)
      .order('joined_at', { ascending: true });
    if (memberError) throw platformFailure('학생 명단', memberError.message);
    return data || [];
  },

  async joinClass(studentId: string, joinCode: string, displayName?: string) {
    const code = joinCode.toUpperCase().replace(/[^A-Z2-9]/g, '').slice(0, 8);
    if (code.length !== 8)
      throw platformFailure('학급 참여', '학급 코드 형식이 올바르지 않습니다.', 400);
    const { data: cls, error: classError } = await admin()
      .from('learning_classes')
      .select('id, name, join_code, is_active')
      .eq('join_code', code)
      .eq('is_active', true)
      .maybeSingle();
    if (classError) throw platformFailure('학급 참여', classError.message);
    if (!cls) throw platformFailure('학급 참여', '사용 가능한 학급 코드를 찾을 수 없습니다.', 404);
    const name = cleanDisplayName(displayName);
    const { error: memberError } = await admin()
      .from('learning_class_members')
      .upsert(
        {
          class_id: cls.id,
          student_id: studentId,
          display_name: name,
          status: 'active',
          updated_at: new Date().toISOString(),
        },
        { onConflict: 'class_id,student_id' }
      );
    if (memberError) throw platformFailure('학급 참여', memberError.message);
    await syncLearningProfile(studentId, name);
    return { id: cls.id, name: cls.name, joinCode: cls.join_code };
  },

  async createAssignment(input: {
    teacherId: string;
    classId: string;
    passageId: string;
    title: string;
    startsAt?: string;
    dueAt?: string | null;
  }) {
    const { data: cls, error: classError } = await admin()
      .from('learning_classes')
      .select('id')
      .eq('id', input.classId)
      .eq('teacher_id', input.teacherId)
      .eq('is_active', true)
      .maybeSingle();
    if (classError) throw platformFailure('과제 학급 확인', classError.message);
    if (!cls) throw platformFailure('과제 생성', '담당 학급을 찾을 수 없습니다.', 404);
    const title = input.title.replace(/\s+/g, ' ').trim().slice(0, 160);
    if (!title) throw platformFailure('과제 생성', '과제 제목이 필요합니다.', 400);
    const startsAt = input.startsAt || new Date().toISOString();
    const { data, error: insertError } = await admin()
      .from('learning_assignments')
      .insert({
        class_id: input.classId,
        passage_id: input.passageId,
        title,
        starts_at: startsAt,
        due_at: input.dueAt || null,
        is_active: true,
        created_by: input.teacherId,
      })
      .select('id, class_id, passage_id, title, starts_at, due_at, is_active, created_at')
      .single();
    if (insertError || !data)
      throw platformFailure('과제 생성', insertError?.message || '저장 실패');
    return data;
  },

  async listTeacherAssignments(teacherId: string, classId?: string) {
    let learning_classesQuery = admin()
      .from('learning_classes')
      .select('id, name')
      .eq('teacher_id', teacherId);
    if (classId) learning_classesQuery = learning_classesQuery.eq('id', classId);
    const { data: learning_classes, error: learning_classesError } = await learning_classesQuery;
    if (learning_classesError) throw platformFailure('과제 목록', learning_classesError.message);
    const classRows = learning_classes || [];
    if (!classRows.length) return [];
    const classNames = new Map(classRows.map(row => [row.id, row.name]));
    const { data, error: assignmentError } = await admin()
      .from('learning_assignments')
      .select('id, class_id, passage_id, title, starts_at, due_at, is_active, created_at')
      .in('class_id', classRows.map(row => row.id))
      .order('created_at', { ascending: false });
    if (assignmentError) throw platformFailure('과제 목록', assignmentError.message);
    return (data || []).map(row => ({ ...row, class_name: classNames.get(row.class_id) || '' }));
  },

  async listStudentAssignments(studentId: string) {
    const { data: memberships, error: membershipError } = await admin()
      .from('learning_class_members')
      .select('class_id, display_name')
      .eq('student_id', studentId)
      .eq('status', 'active');
    if (membershipError) throw platformFailure('학생 과제 목록', membershipError.message);
    const classIds = [...new Set((memberships || []).map(row => row.class_id))];
    if (!classIds.length) return [];
    const { data: learning_classes, error: classError } = await admin()
      .from('learning_classes')
      .select('id, name, is_active')
      .in('id', classIds)
      .eq('is_active', true);
    if (classError) throw platformFailure('학생 과제 목록', classError.message);
    const activeClasses = learning_classes || [];
    if (!activeClasses.length) return [];
    const classNames = new Map(activeClasses.map(row => [row.id, row.name]));
    const { data: learning_assignments, error: assignmentError } = await admin()
      .from('learning_assignments')
      .select('id, class_id, passage_id, title, starts_at, due_at, is_active, created_at')
      .in('class_id', activeClasses.map(row => row.id))
      .eq('is_active', true)
      .order('starts_at', { ascending: false });
    if (assignmentError) throw platformFailure('학생 과제 목록', assignmentError.message);
    const assignments = learning_assignments || [];
    if (!assignments.length) return [];
    const { data: attempts, error: attemptError } = await admin()
      .from('learning_assignment_attempts')
      .select('assignment_id, started_at, last_activity_at, completed_at, last_completed_at, session_count')
      .eq('student_id', studentId)
      .in('assignment_id', assignments.map(row => row.id));
    if (attemptError) throw platformFailure('학생 과제 진행상태', attemptError.message);
    type StudentAttemptSummary = { assignment_id: string; started_at: string; last_activity_at: string; completed_at: string | null; last_completed_at: string | null; session_count: number };
    const attemptByAssignment = new Map<string, StudentAttemptSummary>((attempts || []).map((row: StudentAttemptSummary) => [row.assignment_id, row]));
    const now = Date.now();
    return assignments.map(row => {
      const attempt = attemptByAssignment.get(row.id);
      return {
        ...row,
        class_name: classNames.get(row.class_id) || '',
        availability:
          Date.parse(row.starts_at) > now
            ? 'upcoming'
            : row.due_at && Date.parse(row.due_at) < now
              ? 'closed'
              : 'active',
        attempt: attempt ? {
          started_at: attempt.started_at,
          last_activity_at: attempt.last_activity_at,
          completed_at: attempt.completed_at,
          last_completed_at: attempt.last_completed_at || attempt.completed_at,
          session_count: Number(attempt.session_count || 1),
        } : null,
        completed: Boolean(attempt?.completed_at),
      };
    });
  },

  async resolveAssignmentAccess(studentId: string, assignmentId: string): Promise<AssignmentAccess> {
    const { data: assignment, error: assignmentError } = await admin()
      .from('learning_assignments')
      .select('id, class_id, passage_id, title, starts_at, due_at, is_active')
      .eq('id', assignmentId)
      .maybeSingle();
    if (assignmentError) throw platformFailure('과제 확인', assignmentError.message);
    if (!assignment || !assignment.is_active)
      throw platformFailure('과제 확인', '사용 가능한 과제를 찾을 수 없습니다.', 404);
    const { data: membership, error: memberError } = await admin()
      .from('learning_class_members')
      .select('class_id')
      .eq('class_id', assignment.class_id)
      .eq('student_id', studentId)
      .eq('status', 'active')
      .maybeSingle();
    if (memberError) throw platformFailure('과제 참여 권한', memberError.message);
    if (!membership)
      throw platformFailure('과제 참여 권한', '이 과제에 참여할 수 없습니다.', 403);
    const { data: cls, error: classError } = await admin()
      .from('learning_classes')
      .select('id, name, is_active')
      .eq('id', assignment.class_id)
      .maybeSingle();
    if (classError) throw platformFailure('과제 학급 확인', classError.message);
    if (!cls?.is_active)
      throw platformFailure('과제 학급 확인', '현재 사용 중인 학급이 아닙니다.', 409);
    const now = Date.now();
    if (Date.parse(assignment.starts_at) > now)
      throw platformFailure('과제 시작', '아직 시작되지 않은 과제입니다.', 409);
    if (assignment.due_at && Date.parse(assignment.due_at) < now)
      throw platformFailure('과제 시작', '마감된 과제입니다.', 409);
    return {
      assignmentId: assignment.id,
      classId: assignment.class_id,
      className: cls.name,
      passageId: assignment.passage_id,
      title: assignment.title,
      startsAt: assignment.starts_at,
      dueAt: assignment.due_at,
    };
  },

  async touchAssignmentAttempt(input: {
    assignmentId: string;
    studentId: string;
    passageId: string;
    sessionKey?: string | null;
    completed?: boolean;
  }) {
    const { data: existing, error: readError } = await admin()
      .from('learning_assignment_attempts')
      .select('id, session_count, completed_at, last_completed_at, last_session_key')
      .eq('assignment_id', input.assignmentId)
      .eq('student_id', input.studentId)
      .maybeSingle();
    if (readError) throw platformFailure('과제 학습 기록', readError.message);
    const now = new Date().toISOString();
    const sessionKey = (input.sessionKey || '').slice(0, 120) || null;
    if (existing) {
      const newSession = Boolean(sessionKey && sessionKey !== existing.last_session_key);
      const { error: updateError } = await admin()
        .from('learning_assignment_attempts')
        .update({
          last_activity_at: now,
          session_count: newSession ? Number(existing.session_count || 1) + 1 : Number(existing.session_count || 1),
          last_session_key: sessionKey || existing.last_session_key,
          last_session_started_at: newSession ? now : undefined,
          completed_at: input.completed ? (existing.completed_at || now) : existing.completed_at,
          last_completed_at: input.completed ? now : existing.last_completed_at,
        })
        .eq('id', existing.id);
      if (updateError) throw platformFailure('과제 학습 기록', updateError.message);
      return;
    }
    const { error: insertError } = await admin()
      .from('learning_assignment_attempts')
      .insert({
        assignment_id: input.assignmentId,
        student_id: input.studentId,
        passage_id: input.passageId,
        started_at: now,
        last_activity_at: now,
        completed_at: input.completed ? now : null,
        last_completed_at: input.completed ? now : null,
        last_session_key: sessionKey,
        last_session_started_at: now,
        session_count: 1,
      });
    if (insertError) throw platformFailure('과제 학습 기록', insertError.message);
  },

  async assignmentAnalytics(teacherId: string, assignmentId: string) {
    const { data: assignment, error: assignmentError } = await admin()
      .from('learning_assignments')
      .select('id, class_id, passage_id, title, starts_at, due_at, is_active')
      .eq('id', assignmentId)
      .maybeSingle();
    if (assignmentError) throw platformFailure('과제 분석', assignmentError.message);
    if (!assignment) throw platformFailure('과제 분석', '과제를 찾을 수 없습니다.', 404);
    const { data: cls, error: classError } = await admin()
      .from('learning_classes')
      .select('id, name, teacher_id')
      .eq('id', assignment.class_id)
      .eq('teacher_id', teacherId)
      .maybeSingle();
    if (classError) throw platformFailure('과제 분석', classError.message);
    if (!cls) throw platformFailure('과제 분석', '담당 과제가 아닙니다.', 403);

    const { data: members, error: memberError } = await admin()
      .from('learning_class_members')
      .select('student_id, display_name, status')
      .eq('class_id', assignment.class_id)
      .eq('status', 'active');
    if (memberError) throw platformFailure('과제 분석 학생', memberError.message);
    const studentIds = (members || []).map(row => row.student_id);
    const [{ data: attempts, error: attemptsError }, { data: events, error: eventsError }, { data: mastery, error: masteryError }] = await Promise.all([
      admin().from('learning_assignment_attempts')
        .select('student_id, started_at, last_activity_at, completed_at, last_completed_at, session_count')
        .eq('assignment_id', assignmentId),
      admin().from('learning_answer_events')
        .select('student_id, question_id, question_snapshot, skill, level, selected, correct, unknown, misconception, response_ms, answered_at')
        .eq('assignment_id', assignmentId)
        .order('answered_at', { ascending: true }),
      studentIds.length
        ? admin().from('learning_student_skill_mastery')
            .select('student_id, skill, mastery, attempts, correct')
            .in('student_id', studentIds)
        : Promise.resolve({ data: [], error: null } as { data: Array<Record<string, unknown>>; error: null }),
    ]);
    if (attemptsError) throw platformFailure('과제 분석 진행상태', attemptsError.message);
    if (eventsError) throw platformFailure('과제 분석 응답', eventsError.message);
    if (masteryError) throw platformFailure('과제 분석 수준', masteryError.message);

    type AnalyticsAttempt = { student_id: string; completed_at: string | null; last_completed_at: string | null; session_count: number };
    const attemptByStudent = new Map<string, AnalyticsAttempt>((attempts || []).map((row: AnalyticsAttempt) => [row.student_id, row]));
    const eventsByStudent = new Map<string, typeof events>();
    for (const event of events || []) {
      const rows = eventsByStudent.get(event.student_id) || [];
      rows.push(event);
      eventsByStudent.set(event.student_id, rows);
    }
    const masteryByStudent = new Map<string, Array<Record<string, unknown>>>();
    for (const row of (mastery || []) as Array<Record<string, unknown>>) {
      const studentId = String(row.student_id || '');
      const rows = masteryByStudent.get(studentId) || [];
      rows.push(row);
      masteryByStudent.set(studentId, rows);
    }
    const skillOrder = ['content','logic','inference','comparison','application'];
    const studentRows = (members || []).map(member => {
      const studentEvents = eventsByStudent.get(member.student_id) || [];
      const correct = studentEvents.filter(event => event.correct).length;
      const responseValues = studentEvents.map(event => Number(event.response_ms)).filter(value => Number.isFinite(value) && value >= 0);
      const skillMastery = Object.fromEntries(skillOrder.map(skill => {
        const row = masteryByStudent.get(member.student_id)?.find(value => value.skill === skill);
        return [skill, row ? Number(row.mastery) : 0.5];
      }));
      const weakSkill = skillOrder.reduce((a, b) => Number(skillMastery[a]) <= Number(skillMastery[b]) ? a : b);
      const misconceptions = new Map<string, number>();
      for (const event of studentEvents) {
        const label = String(event.misconception || '').trim();
        if (label) misconceptions.set(label, (misconceptions.get(label) || 0) + 1);
      }
      const attempt = attemptByStudent.get(member.student_id);
      return {
        student_id: member.student_id,
        display_name: member.display_name || '',
        completed_at: attempt?.completed_at || null,
        last_completed_at: attempt?.last_completed_at || attempt?.completed_at || null,
        session_count: Number(attempt?.session_count || 0),
        answered: studentEvents.length,
        correct,
        correct_rate: studentEvents.length ? correct / studentEvents.length : null,
        avg_response_ms: responseValues.length ? Math.round(responseValues.reduce((sum, value) => sum + value, 0) / responseValues.length) : null,
        weak_skill: weakSkill,
        mastery: skillMastery,
        misconceptions: [...misconceptions.entries()].sort((a,b) => b[1] - a[1]).slice(0, 3).map(([label, count]) => ({ label, count })),
      };
    });

    const questionMap = new Map<string, { stem: string; answered: number; correct: number; unknown: number; response: number[]; choices: Map<number, number> }>();
    for (const event of events || []) {
      const snapshot = event.question_snapshot && typeof event.question_snapshot === 'object' ? event.question_snapshot as Record<string, unknown> : {};
      const row = questionMap.get(event.question_id) || { stem: String(snapshot.stem || ''), answered: 0, correct: 0, unknown: 0, response: [], choices: new Map<number, number>() };
      row.answered += 1;
      if (event.correct) row.correct += 1;
      if (event.unknown) row.unknown += 1;
      const responseMs = Number(event.response_ms);
      if (Number.isFinite(responseMs) && responseMs >= 0) row.response.push(responseMs);
      const selected = Number(event.selected);
      row.choices.set(selected, (row.choices.get(selected) || 0) + 1);
      questionMap.set(event.question_id, row);
    }
    const questionRows = [...questionMap.entries()].map(([question_id, row]) => ({
      question_id,
      stem: row.stem,
      answered: row.answered,
      correct_rate: row.answered ? row.correct / row.answered : null,
      unknown_rate: row.answered ? row.unknown / row.answered : null,
      avg_response_ms: row.response.length ? Math.round(row.response.reduce((sum, value) => sum + value, 0) / row.response.length) : null,
      choice_counts: Object.fromEntries([...row.choices.entries()].map(([key, value]) => [String(key), value])),
    })).sort((a,b) => a.correct_rate === null ? 1 : b.correct_rate === null ? -1 : a.correct_rate - b.correct_rate);

    return { assignment: { ...assignment, class_name: cls.name }, students: studentRows, questions: questionRows };
  },

  async getStudentMastery(studentId: string): Promise<StudentMasteryRow[]> {
    const { data, error: selectError } = await admin()
      .from('learning_student_skill_mastery')
      .select('skill, mastery, attempts, correct')
      .eq('student_id', studentId);
    if (selectError) throw platformFailure('장기 학습 수준 조회', selectError.message);
    return (data || []).map(row => ({
      skill: row.skill,
      mastery: Number(row.mastery),
      attempts: Number(row.attempts),
      correct: Number(row.correct),
    }));
  },

  async recordAnswerEvent(input: {
    submissionId: string;
    studentId: string;
    assignmentId?: string | null;
    classId?: string | null;
    passageId: string;
    bankRevision: number;
    progressVersion: number;
    questionId: string;
    questionSnapshot: { stem: string; choices: string[]; answer: number };
    qualityVersion: string;
    skill: string;
    level: string;
    objective: string;
    selected: number;
    correct: boolean;
    unknown: boolean;
    misconception: string;
    masteryBefore: number;
    masteryAfter: number;
    responseMs?: number | null;
    answeredAt: string;
  }) {
    const { data, error: rpcError } = await admin().rpc('learning_record_student_answer_event', {
      p_submission_id: input.submissionId,
      p_student_id: input.studentId,
      p_assignment_id: input.assignmentId || null,
      p_class_id: input.classId || null,
      p_passage_id: input.passageId,
      p_bank_revision: input.bankRevision,
      p_progress_version: input.progressVersion,
      p_question_id: input.questionId,
      p_question_snapshot: input.questionSnapshot,
      p_quality_version: input.qualityVersion,
      p_skill: input.skill,
      p_level: input.level,
      p_objective: input.objective,
      p_selected: input.selected,
      p_correct: input.correct,
      p_unknown: input.unknown,
      p_misconception: input.misconception,
      p_mastery_before: input.masteryBefore,
      p_mastery_after: input.masteryAfter,
      p_response_ms: input.responseMs ?? null,
      p_answered_at: input.answeredAt,
    });
    if (rpcError) throw platformFailure('응답 이력 저장', rpcError.message);
    return data === true;
  },

  async listAiJobs(createdBy: string, limit = 30) {
    const { data, error: selectError } = await admin()
      .from('learning_ai_jobs')
      .select('id, kind, status, attempts, max_attempts, progress, result, last_error, created_at, updated_at, completed_at')
      .eq('created_by', createdBy)
      .order('created_at', { ascending: false })
      .limit(Math.max(1, Math.min(100, Math.floor(limit))));
    if (selectError) throw platformFailure('AI 작업 목록', selectError.message);
    return data || [];
  },

  async getAiJob(createdBy: string, jobId: string) {
    const { data, error: selectError } = await admin()
      .from('learning_ai_jobs')
      .select('id, kind, status, attempts, max_attempts, progress, result, last_error, created_at, updated_at, completed_at')
      .eq('id', jobId)
      .eq('created_by', createdBy)
      .maybeSingle();
    if (selectError) throw platformFailure('AI 작업 상태', selectError.message);
    if (!data) throw platformFailure('AI 작업 상태', '작업을 찾을 수 없습니다.', 404);
    return data;
  },

  async enqueueAiJob(input: {
    kind: string;
    payload: Record<string, unknown>;
    createdBy?: string | null;
    maxAttempts?: number;
  }) {
    const { data, error: insertError } = await admin()
      .from('learning_ai_jobs')
      .insert({
        kind: input.kind,
        payload: input.payload,
        status: 'queued',
        max_attempts: Math.max(1, Math.min(20, input.maxAttempts || 3)),
        created_by: input.createdBy || null,
      })
      .select('id, kind, status, created_at')
      .single();
    if (insertError || !data)
      throw platformFailure('AI 작업 대기열', insertError?.message || '저장 실패');
    return data;
  },

  async claimAiJobs(workerId: string, limit = 1) {
    const { data, error: rpcError } = await admin().rpc('learning_claim_ai_jobs', {
      p_worker_id: workerId.slice(0, 160),
      p_limit: Math.max(1, Math.min(20, Math.floor(limit))),
    });
    if (rpcError) throw platformFailure('AI 작업 claim', rpcError.message);
    return data || [];
  },

  async completeAiJob(jobId: string, workerId: string, result: Record<string, unknown> = {}) {
    const { data, error: rpcError } = await admin().rpc('learning_complete_ai_job', {
      p_job_id: jobId,
      p_worker_id: workerId.slice(0, 160),
      p_result: result,
    });
    if (rpcError) throw platformFailure('AI 작업 완료', rpcError.message);
    return data === true;
  },

  async failAiJob(jobId: string, workerId: string, message: string, retrySeconds = 30) {
    const { data, error: rpcError } = await admin().rpc('learning_fail_ai_job', {
      p_job_id: jobId,
      p_worker_id: workerId.slice(0, 160),
      p_error: message.slice(0, 4000),
      p_retry_seconds: Math.max(0, Math.min(3600, Math.floor(retrySeconds))),
    });
    if (rpcError) throw platformFailure('AI 작업 실패 처리', rpcError.message);
    return typeof data === 'string' ? data : 'missing';
  },
};

export function json(data: unknown, status = 200) {
  return Response.json(data, {
    status,
    headers: { 'Cache-Control': 'no-store' },
  });
}

export function error(message: string, status = 500) {
  return json({ error: message }, status);
}

async function currentUser(request: Request): Promise<AuthUser | null> {
  // Dedicated workers authenticate with a server-only secret and an owner uid.
  // The uid is resolved through Supabase Admin Auth; worker-supplied email/role data
  // is never trusted. This path requires functions.engine.verify_jwt=false so the
  // application router, rather than the gateway, owns authentication.
  const workerSecret = request.headers.get('x-ai-worker-secret') || '';
  const expectedWorkerSecret = runtimeEnv('AI_WORKER_SECRET') || '';
  const workerUserId = request.headers.get('x-ai-worker-user-id') || '';
  if (
    expectedWorkerSecret.length >= 24 &&
    workerSecret === expectedWorkerSecret &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(workerUserId)
  ) {
    const { data, error: lookupError } = await admin().auth.admin.getUserById(workerUserId);
    const user = data.user;
    if (lookupError || !user) return null;
    const metadata = user.user_metadata as Record<string, unknown> | undefined;
    const name =
      typeof metadata?.full_name === 'string'
        ? metadata.full_name
        : typeof metadata?.name === 'string'
          ? metadata.name
          : undefined;
    return { userId: user.id, email: user.email, name, scope: 'internal-worker' };
  }

  const authorization = request.headers.get('Authorization') || '';
  const token = authorization.match(/^Bearer\s+(.+)$/i)?.[1];
  if (!token) return null;
  const { data, error: authError } = await admin().auth.getUser(token);
  const user = data.user;
  if (authError || !user) return null;
  const metadata = user.user_metadata as Record<string, unknown> | undefined;
  const name =
    typeof metadata?.full_name === 'string'
      ? metadata.full_name
      : typeof metadata?.name === 'string'
        ? metadata.name
        : undefined;
  return {
    userId: user.id,
    email: user.email,
    name,
    scope: 'authenticated',
  };
}

export function requireAuth(): Middleware {
  return async context => {
    const user = await currentUser(context.event.request);
    if (!user) return error('로그인이 필요합니다.', 401);
    context.user = user;
  };
}

export function requireAdminEmailAllowlist(emails: string[]): Middleware {
  const allowlist = new Set(emails.map(email => email.trim().toLowerCase()));
  return context => {
    const email = context.user?.email?.trim().toLowerCase();
    if (!email || !allowlist.has(email))
      return error('이 계정에는 교사 관리 권한이 없습니다.', 403);
  };
}

function cors(response: Response, request: Request) {
  const headers = new Headers(response.headers);
  headers.set('Access-Control-Allow-Origin', request.headers.get('Origin') || '*');
  headers.set('Vary', 'Origin');
  headers.set(
    'Access-Control-Allow-Headers',
    'authorization, apikey, content-type, x-client-info'
  );
  headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function routePath(url: URL) {
  const index = url.pathname.indexOf('/api/');
  if (index >= 0) return url.pathname.slice(index);
  return url.pathname.endsWith('/api') ? '/api' : url.pathname;
}

export function router(routes: Routes) {
  return {
    async fetch(request: Request) {
      try {
          if (request.method === 'OPTIONS')
            return cors(new Response(null, { status: 204 }), request);
          const url = new URL(request.url);
          const path = routePath(url);
          if (path === '/api/auth/me' && request.method === 'GET')
            return cors(json({ user: await currentUser(request) }), request);
          if (path === '/api/auth/logout' && request.method === 'POST')
            return cors(json({ ok: true }), request);
          const chain = routes[`${request.method} ${path}`];
          if (!chain)
            return cors(error('요청 경로를 찾을 수 없습니다.', 404), request);
          let body: unknown;
          if (!['GET', 'HEAD'].includes(request.method)) {
            const contentType = request.headers.get('Content-Type') || '';
            if (contentType.includes('application/json')) {
              try {
                body = await request.json();
              } catch {
                return cors(
                  error('JSON 요청 형식이 올바르지 않습니다.', 400),
                  request
                );
              }
            }
          }
          const context: RouterContext = {
            body,
            query: Object.fromEntries(url.searchParams.entries()),
            params: {},
            event: {
              request,
              waitUntil: promise => {
                const runtime = globalThis as unknown as {
                  EdgeRuntime?: { waitUntil?: (value: Promise<unknown>) => void };
                };
                if (runtime.EdgeRuntime?.waitUntil)
                  runtime.EdgeRuntime.waitUntil(promise);
                else void promise.catch(console.error);
              },
            },
          };
          for (const middleware of chain) {
            const response = await middleware(context);
            if (response) return cors(response, request);
          }
          return cors(new Response(null, { status: 204 }), request);
      } catch (routeError) {
        console.error('[edge-route-error]', routeError);
        return cors(
          error(
            routeError instanceof Error
              ? routeError.message
              : '서버 요청을 처리하지 못했습니다.',
            500
          ),
          request
        );
      }
    },
  };
}

