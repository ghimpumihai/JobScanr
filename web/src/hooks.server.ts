import { createSupabaseServerClient } from '$lib/supabase/server';
import { redirect, type Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.supabase = createSupabaseServerClient(event);

  event.locals.getSession = async () => {
    const {
      data: { session }
    } = await event.locals.supabase.auth.getSession();
    return session;
  };

  const {
    data: { user }
  } = await event.locals.supabase.auth.getUser();

  event.locals.user = user;
  event.locals.session = await event.locals.getSession();

  const pathname = event.url.pathname;
  const isProtected =
    pathname.startsWith('/matches') ||
    pathname.startsWith('/applications') ||
    pathname.startsWith('/settings') ||
    pathname.startsWith('/profile');

  // Allow bypass only when explicitly configured for local mock prototype mode
  const mockAuth = process.env.VITE_MOCK_AUTH === 'true';

  if (isProtected && !event.locals.user && !mockAuth) {
    throw redirect(303, '/login');
  }

  // Redirect root to /matches
  if (pathname === '/') {
    throw redirect(303, '/matches');
  }

  return resolve(event, {
    filterSerializedResponseHeaders(name) {
      return name === 'content-range' || name === 'x-supabase-api-version';
    }
  });
};
