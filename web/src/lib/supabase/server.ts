import { createServerClient } from '@supabase/ssr';
import type { RequestEvent } from '@sveltejs/kit';
import type { SupabaseClient } from '@supabase/supabase-js';

function resolveSupabaseUrl(): string {
  let url = process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
  if (!url && process.env.DATABASE_URL) {
    const match = process.env.DATABASE_URL.match(/postgres\.([a-z0-9]+):/);
    if (match) {
      url = `https://${match[1]}.supabase.co`;
    }
  }
  return url;
}

export function isSupabaseConfigured(): boolean {
  const url = resolveSupabaseUrl();
  const anonKey = process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || '';
  return Boolean(
    url &&
    anonKey &&
    !url.includes('placeholder') &&
    !anonKey.includes('placeholder')
  );
}

export function createSupabaseServerClient(event: RequestEvent): SupabaseClient {
  const url = resolveSupabaseUrl() || 'https://placeholder-project.supabase.co';
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
