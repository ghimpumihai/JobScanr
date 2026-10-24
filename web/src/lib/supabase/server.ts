import { createServerClient } from '@supabase/ssr';
import type { RequestEvent } from '@sveltejs/kit';
import type { SupabaseClient } from '@supabase/supabase-js';

export function isSupabaseConfigured(): boolean {
  const url = process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
  const anonKey = process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || '';
  return Boolean(
    url &&
    anonKey &&
    !url.includes('placeholder') &&
    !anonKey.includes('placeholder')
  );
}

export function createSupabaseServerClient(event: RequestEvent): SupabaseClient {
  const url = process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || 'https://placeholder-project.supabase.co';
  const anonKey = process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || 'placeholder-anon-key';

  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return event.cookies.getAll();
      },
      setAll(cookiesToSet: Array<{ name: string; value: string; options: any }>) {
        cookiesToSet.forEach(({ name, value, options }) => {
          event.cookies.set(name, value, { ...options, path: '/' });
        });
      }
    }
  });
}
