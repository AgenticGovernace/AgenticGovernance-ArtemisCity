import { deleteNote as deleteObsidianNote } from '../../services/obsidianRestAPI/methods';

export async function deleteNote({path}: { path: string }) {
  try {
    console.debug(`Attempting to delete note: ${path}`);
    await deleteObsidianNote(path);
    console.info(`Successfully deleted note: ${path}`);
    return { success: true, message: `Note '${path}' deleted successfully.` };
  } catch (error: any) {
    console.error(`Error deleting note '${path}': ${error.message}`);
    return { success: false, error: error.message };
  }
}
