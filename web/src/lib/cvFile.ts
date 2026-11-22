// Keep limits equal to jobs/apply/cv_security.py (tests/test_web_scaffold.py checks). Active content is
// scanned by the worker before each submission, not here.
export const MAX_CV_SIZE = 2 * 1024 * 1024;
const MAX_FILENAME_LENGTH = 120;

const CV_TYPES: Record<string, { contentType: string; magic: number[] }> = {
  '.pdf': { contentType: 'application/pdf', magic: [0x25, 0x50, 0x44, 0x46, 0x2d] },
  '.docx': {
    contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    magic: [0x50, 0x4b, 0x03, 0x04]
  },
  '.doc': { contentType: 'application/msword', magic: [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1] }
};

export type CvCheck =
  | { ok: true; filename: string; extension: string; contentType: string }
  | { ok: false; error: string };

export function checkCvFile(name: string, bytes: Uint8Array): CvCheck {
  // \p{C}: control and invisible formatting characters, e.g. the right-to-left override used to disguise extensions.
  const base = (name.split(/[\\/]/).pop() ?? '').replace(/\p{C}/gu, '').trim().replace(/^\.+/, '');
  const dot = base.lastIndexOf('.');
  const extension = dot > 0 ? base.slice(dot).toLowerCase() : '';
  const type = Object.hasOwn(CV_TYPES, extension) ? CV_TYPES[extension] : undefined;
  if (!type) return { ok: false, error: 'Please upload a PDF, DOCX or DOC file.' };
  if (bytes.length > MAX_CV_SIZE) return { ok: false, error: 'The file is larger than 2 MB.' };
  if (!type.magic.every((byte, i) => bytes[i] === byte)) {
    return { ok: false, error: `The file is empty or is not a valid ${extension.slice(1).toUpperCase()} file.` };
  }
  const stem = [...base.slice(0, dot)].slice(0, MAX_FILENAME_LENGTH - extension.length).join('');
  return { ok: true, filename: stem + extension, extension, contentType: type.contentType };
}
