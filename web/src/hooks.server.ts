import { createSupabaseServerClient, isSupabaseConfigured } from '$lib/supabase/server';
import { redirect, type Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.supabase = createSupabaseServerClient(event);
  const supabaseReady = isSupabaseConfigured();

  event.locals.getSession = async () => {
    if (!supabaseReady) return null;
    const {
      data: { session }
    } = await event.locals.supabase.auth.getSession();
    return session;
  };

  if (supabaseReady) {
    const {
      data: { user }
    } = await event.locals.supabase.auth.getUser();
    event.locals.user = user;
    event.locals.session = await event.locals.getSession();
  } else {
    event.locals.user = null;
    event.locals.session = null;
  }

  // Support query param transitions with clean URL redirect (e.g. /matches?demo=true -> /matches)
  if (event.url.searchParams.get('demo') === 'true') {
    event.cookies.delete('jobscanr_logged_out', { path: '/' });
    event.cookies.set('jobscanr_demo_session', 'true', {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7
    });
    throw redirect(303, event.url.pathname);
  }

  if (event.url.searchParams.get('logout') === 'true') {
    event.cookies.delete('jobscanr_demo_session', { path: '/' });
    event.cookies.set('jobscanr_logged_out', 'true', {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7
    });
    throw redirect(303, event.url.pathname);
  }

  // Check if user is in demo mode or explicitly logged out
  const isDemoSession =
    event.cookies.get('jobscanr_demo_session') === 'true' || event.url.searchParams.get('demo') === 'true';
  const isLoggedOut =
    event.cookies.get('jobscanr_logged_out') === 'true' && event.url.searchParams.get('demo') !== 'true';

  // Allow bypass when explicitly configured for local mock prototype mode, or when in active demo session
  const mockAuth = (process.env.VITE_MOCK_AUTH === 'true' || isDemoSession) && !isLoggedOut;

  if (isLoggedOut) {
    event.locals.user = null;
    event.locals.session = null;
  } else if ((mockAuth || isDemoSession) && !event.locals.user) {
    event.locals.user = {
      id: 'demo-user-id',
      email: 'stefan@example.com',
      app_metadata: {},
      user_metadata: { full_name: 'Stefan Ghimpu' },
      aud: 'authenticated',
      created_at: new Date().toISOString()
    } as any;
  }

  const pathname = event.url.pathname;
  const isProtected =
    pathname.startsWith('/matches') ||
    pathname.startsWith('/applications') ||
    pathname.startsWith('/settings') ||
    pathname.startsWith('/profile');

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
