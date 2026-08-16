import re
from utils.helpers import logger


class ObsidianParser:
    def parse_task_note(self, content: str) -> dict | None:
        """
        Parses an Obsidian note expected to contain a task.
        Assumes a structure like:
        ---
        task_id: T123
        agent: research_agent
        status: pending
        ---
        # Task Title
        Context: This is the detailed context for the task.
        Keywords: keyword1, keyword2
        Target: [[Some Other Note]]
        - [ ] Subtask 1
        - [ ] Subtask 2
        """
        task_data = {}

        # 1. Parse YAML front matter (if present)
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) > 1:
                front_matter = parts[1].strip()
                for line in front_matter.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        task_data[key.strip()] = value.strip()
                content = parts[2].strip()  # Remaining content

        # 2. Parse main content for headings, key-value pairs, and list items
        lines = content.split("\n")
        current_section = None
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for H1 as title
            if line.startswith("# ") and "title" not in task_data:
                task_data["title"] = line[2:].strip()
                continue

            # Key-Value pairs (e.g., "Context: Some text")
            match = re.match(r"(\w+):\s*(.*)", line)
            if match:
                key = match.group(1).lower()
                value = match.group(2).strip()
                task_data[key] = value
                continue

            # Checkbox lists (useful for subtasks)
            if line.startswith("- [ ] ") or line.startswith("- [x] "):
                if "subtasks" not in task_data:
                    task_data["subtasks"] = []
                task_data["subtasks"].append(
                    {"text": line[6:].strip(), "completed": line[3] == "x"}
                )

        if not task_data:
            logger.warning("No structured task data found in note.")
            return None

        return task_data

    def update_status_in_note(
        self, original_content: str, new_status: str, task_id: str = None
    ) -> str:
        """
        Updates the 'status' field in the YAML front matter of a note, or adds it.
        If task_id is provided, it tries to match and update a specific task.
        """
        updated_content = original_content

        if updated_content.startswith("---"):
            parts = updated_content.split("---", 2)
            if len(parts) > 1:
                front_matter = parts[1].strip()
                main_content = parts[2].strip()

                new_front_matter_lines = []
                status_found = False
                for line in front_matter.split("\n"):
                    if line.startswith("status:"):
                        new_front_matter_lines.append(f"status: {new_status}")
                        status_found = True
                    else:
                        new_front_matter_lines.append(line)

                if not status_found:
                    new_front_matter_lines.append(f"status: {new_status}")

                updated_content = (
                    "---\n"
                    + "\n".join(new_front_matter_lines)
                    + "\n---\n"
                    + main_content
                )
        else:
            # No front matter, add it
            updated_content = f"---\nstatus: {new_status}\n---\n" + original_content

        return updated_content
