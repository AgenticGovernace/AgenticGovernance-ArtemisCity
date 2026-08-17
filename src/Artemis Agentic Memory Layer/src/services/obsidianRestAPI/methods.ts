import { obsidianAPI } from './index';

interface SearchResult {
  path: string;
  excerpt: string;
}

interface SimpleSearchHit {
  filename: string;
  score: number;
  matches?: Array<{ match: { start: number; end: number }; context: string }>;
}

interface NoteJson {
  path: string;
  content: string;
  frontmatter?: Record<string, unknown>;
  tags?: string[];
}

// Local REST API treats `/` as the path separator inside a vault, so encode each
// segment but keep slashes intact.
function encodeVaultPath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}

/**
 * Read the markdown content of a note.
 * Wraps `GET /vault/{path}` from the Obsidian Local REST API.
 *
 * @param path - Vault-relative note path to read.
 * @returns Markdown content stored at the requested vault path.
 */
export async function readNote(path: string): Promise<string> {
  const response = await obsidianAPI.get<string>(`/vault/${encodeVaultPath(path)}`, {
    headers: { Accept: 'text/markdown' },
    transformResponse: (data) => data,
  });
  return typeof response.data === 'string' ? response.data : String(response.data);
}

/**
 * Create, overwrite, or append to a note.
 * Wraps `PUT /vault/{path}` for overwrites and `POST /vault/{path}` for appends.
 *
 * @param path - Vault-relative note path to update.
 * @param content - Markdown content to write to the note.
 * @param options - Optional write settings such as append mode.
 * @returns Status message describing whether the note was updated or appended.
 */
export async function updateNote(
  path: string,
  content: string,
  options?: { append?: boolean },
): Promise<string> {
  const url = `/vault/${encodeVaultPath(path)}`;
  const config = { headers: { 'Content-Type': 'text/markdown' } };
  if (options?.append) {
    await obsidianAPI.post(url, content, config);
    return `Content appended to '${path}'.`;
  }
  await obsidianAPI.put(url, content, config);
  return `Note '${path}' updated.`;
}

/**
 * Run a simple text search across the vault.
 * Wraps `POST /search/simple/` and flattens hits to `{ path, excerpt }`.
 *
 * @param query - Search query to send to the Obsidian API.
 * @returns Matching note paths with a short excerpt for the top match in each note.
 */
export async function searchNotes(query: string): Promise<SearchResult[]> {
  const response = await obsidianAPI.post<SimpleSearchHit[]>('/search/simple/', null, {
    params: { query },
  });
  return (response.data ?? []).map((hit) => ({
    path: hit.filename,
    excerpt: hit.matches?.[0]?.context ?? '',
  }));
}

/**
 * List all markdown notes in the vault.
 * Walks the Local REST API directory listing depth-first and returns `.md` files only.
 *
 * @returns Markdown note paths discovered while traversing the vault.
 */
export async function listNotes(): Promise<string[]> {
  const results: string[] = [];
  const stack: string[] = [''];
  while (stack.length) {
    const dir = stack.pop() as string;
    const normalizedDir = dir.replace(/\/+$/, '');
    const url = normalizedDir === '' ? '/vault/' : `/vault/${encodeVaultPath(normalizedDir)}/`;
    const response = await obsidianAPI.get<{ files: string[] }>(url);
    for (const entry of response.data.files ?? []) {
      const full = dir === '' ? entry : `${dir}${entry}`;
      if (entry.endsWith('/')) {
        stack.push(full);
      } else if (entry.toLowerCase().endsWith('.md')) {
        results.push(full);
      }
    }
  }
  return results;
}

/**
 * Delete a note from the vault.
 * Wraps `DELETE /vault/{path}`.
 *
 * @param path - Vault-relative note path to delete.
 * @returns Status message confirming the deletion request.
 */
export async function deleteNote(path: string): Promise<string> {
  await obsidianAPI.delete(`/vault/${encodeVaultPath(path)}`);
  return `Note '${path}' deleted successfully.`;
}

/**
 * Replace a single frontmatter key on a note.
 * Uses the Local REST API frontmatter patch headers documented for v4.x.
 *
 * @param path - Vault-relative note path to update.
 * @param key - Frontmatter key to replace.
 * @param value - JSON-serializable value to store under the given key.
 * @returns Status message confirming the frontmatter update.
 */
export async function manageFrontmatter(path: string, key: string, value: unknown): Promise<string> {
  await obsidianAPI.patch(`/vault/${encodeVaultPath(path)}`, JSON.stringify(value), {
    headers: {
      Operation: 'replace',
      'Target-Type': 'frontmatter',
      Target: key,
      'Content-Type': 'application/json',
    },
  });
  return `Frontmatter for '${path}' updated.`;
}

/**
 * Add or remove tags from a note's frontmatter `tags` array.
 * Performs a read-modify-write cycle to avoid duplicates and handle missing arrays.
 *
 * @param path - Vault-relative note path to update.
 * @param tags - Tags to add to or remove from the note.
 * @param action - Whether the provided tags should be added or removed.
 * @returns Status message confirming the tag update.
 */
export async function manageTags(
  path: string,
  tags: string[],
  action: 'add' | 'remove',
): Promise<string> {
  const url = `/vault/${encodeVaultPath(path)}`;
  const current = await obsidianAPI.get<NoteJson>(url, {
    headers: { Accept: 'application/vnd.olrapi.note+json' },
  });
  const existing = Array.isArray(current.data.tags) ? current.data.tags : [];
  const set = new Set(existing);
  if (action === 'add') {
    for (const tag of tags) set.add(tag);
  } else {
    for (const tag of tags) set.delete(tag);
  }
  const next = Array.from(set);
  await obsidianAPI.patch(url, JSON.stringify(next), {
    headers: {
      Operation: 'replace',
      'Target-Type': 'frontmatter',
      Target: 'tags',
      'Content-Type': 'application/json',
    },
  });
  return `Tags for '${path}' ${action === 'add' ? 'added' : 'removed'} successfully.`;
}

/**
 * Replace all occurrences of one string with another inside a note.
 * Reads the note, performs an in-memory replacement, and writes the content back.
 *
 * @param path - Vault-relative note path to update.
 * @param search - Literal text to find inside the note.
 * @param replace - Replacement text to write in place of each match.
 * @returns Updated note content after all replacements are applied.
 */
export async function searchReplace(path: string, search: string, replace: string): Promise<string> {
  const content = await readNote(path);
  const updated = content.split(search).join(replace);
  await updateNote(path, updated);
  return updated;
}
