/**
 * Starts a remote fill session for the panel. If the panel was closed while the form was being filled
 * (`isOpen()` is false by then), nobody will see the live view: end the session at once and return null,
 * so the remote browser does not run on, using the provider's free minutes, until its timeout.
 */
export async function startUnlessClosed<T extends { sessionId: number }>(
  start: () => Promise<T>,
  end: (sessionId: number) => Promise<unknown>,
  isOpen: () => boolean
): Promise<T | null> {
  const started = await start();
  if (isOpen()) return started;
  await end(started.sessionId).catch(() => {});
  return null;
}
