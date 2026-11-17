/** Only http(s) URLs may become an href; scraped job URLs are third-party data. Anything else becomes '#'. */
export function safeHttpUrl(value: string | null | undefined): string {
  if (!value) return '#';
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:' ? value : '#';
  } catch {
    return '#';
  }
}
