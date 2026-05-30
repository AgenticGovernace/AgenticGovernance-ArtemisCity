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
 * Reads the markdown content of a note.
 * Wraps GET /vault/{path} from the Obsidian Local REST API.
 */
export async function readNote(path: string): Promise<string> {
  const response = await obsidianAPI.get<string>(`/vault/${encodeVaultPath(path)}`, {
    headers: { Accept: 'text/markdown' },
    transformResponse: (data) => data,
  });
  return typeof response.data === 'string' ? response.data : String(response.data);
}

/**
 * Creates, overwrites, or appends to a note.
 * Wraps PUT /vault/{path} (overwrite) or POST /vault/{path} (append).
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
 * Simple text search across the vault.
 * Wraps POST /search/simple/?query=... and flattens hits to { path, excerpt }.
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
 * Lists all markdown notes in the vault.
 * Local REST API exposes one directory at a time via GET /vault/{dir}/, so this
 * walks the tree depth-first and returns markdown files only.
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
 * Deletes a note. Wraps DELETE /vault/{path}.
 */
export async function deleteNote(path: string): Promise<string> {
  await obsidianAPI.delete(`/vault/${encodeVaultPath(path)}`);
  return `Note '${path}' deleted successfully.`;
}

/**
 * Replaces a single frontmatter key on a note.
 * Wraps PATCH /vault/{path} with the frontmatter target headers documented by
 * Local REST API v4.x. A JSON body is sent so values can be strings, numbers,
 * booleans, arrays, or objects.
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
 * Adds or removes tags from a note's frontmatter `tags` array.
 * Read-modify-write against PATCH on `Target: tags` — avoids duplicates on add
 * and handles missing arrays on remove.
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
 * Replaces all occurrences of `search` with `replace` inside a note.
 * Local REST API has no native string-replace endpoint, so we read the note,
 * mutate the string, and PUT it back.
 */
export async function searchReplace(path: string, search: string, replace: string): Promise<string> {
  const content = await readNote(path);
  const updated = content.split(search).join(replace);
  await updateNote(path, updated);
  return updated;
}
