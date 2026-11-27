import type { LayoutServerLoad } from './$types';
import { isSupabaseConfigured } from '$lib/supabase/server';

/** The scan runs daily at 06:00 UTC (GitHub Actions); the menu shows that schedule. */
function scanStatus(now: Date) {
  const ranToday = now.getUTCHours() >= 6;
  return { last: ranToday ? 'today' : 'yesterday', next: ranToday ? 'tomorrow' : 'today' };
}

export const load: LayoutServerLoad = async ({ locals }) => {
  const user = locals.user;
  const name: string = user?.user_metadata?.full_name ?? user?.user_metadata?.name ?? '';
  const email = user?.email ?? '';
  const live = user && locals.supabase && isSupabaseConfigured() && user.id !== 'demo-user-id';
  let inboxCount: number | null = 5; // the demo Inbox
  if (live) {
    const { count, error } = await locals.supabase
      .from('applications')
      .select('id', { count: 'exact', head: true })
      .eq('status', 'manual_apply');
    inboxCount = error ? null : (count ?? 0);
  }
  return { account: { name, email }, inboxCount, scan: scanStatus(new Date()), demo: !live };
};
