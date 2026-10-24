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

  // Check if user has explicitly logged out
  const isLoggedOut = event.cookies.get('jobscanr_logged_out') === 'true';

  if (isLoggedOut) {
    event.locals.user = null;
    event.locals.session = null;
  }

  const pathname = event.url.pathname;
  const isProtected =
    pathname.startsWith('/matches') ||
    pathname.startsWith('/applications') ||
    pathname.startsWith('/settings') ||
    pathname.startsWith('/profile');

  // Allow bypass only when explicitly configured for local mock prototype mode and not logged out
  const mockAuth = process.env.VITE_MOCK_AUTH === 'true' && !isLoggedOut;

  if (isProtected && !event.locals.user && !mockAuth) {
    throw redirect(303, '/login');
  }

  // Redirect root to /matches if authenticated, otherwise to /login
  if (pathname === '/') {
    if (event.locals.user || mockAuth) {
      throw redirect(303, '/matches');
    } else {
      throw redirect(303, '/login');
    }
  }

  return resolve(event, {
    filterSerializedResponseHeaders(name) {
      return name === 'content-range' || name === 'x-supabase-api-version';
    }
  });
};
