from datetime import datetime

from ..utils.helpers import logger, sanitize_for_log


class ObsidianGenerator:
    """Provide the ObsidianGenerator abstraction used by this module."""

    def generate_agent_report(
        self, agent_name: str, task_id: str, results: dict
    ) -> str:
        """Generates a Markdown report from agent results.

        Args:
            agent_name (str): Name of the agent involved in the operation.
            task_id (str): Identifier of the task being processed.
            results (dict): Result payload to serialize or summarize.

        Returns:
            str: String result produced by the operation.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_title = f"Agent Report: {agent_name} - {task_id}"

        markdown = f"""---\ntask_id: {task_id}\nagent: {agent_name}\ntimestamp: {timestamp}\nstatus: completed\ntags: ["agent_report", "{agent_name.lower().replace(' ', '_')}"]\n---\n\n# {report_title}\n\n## Summary of Findings\n\n{results.get('summary', 'No summary provided.')}\n\n## Key Data/Outputs\n\n"""
        # Add key-value pairs from results
        for key, value in results.items():
            if key not in ["summary"]:  # Exclude summary as it's handled above
                if isinstance(value, list):
                    markdown += f"\n### {key.replace('_', ' ').title()}\n"
                    for item in value:
                        markdown += f"- {item}\n"
                elif isinstance(value, dict):
                    markdown += f"\n### {key.replace('_', ' ').title()}\n"
                    for sub_key, sub_value in value.items():
                        markdown += f"- **{sub_key.title()}**: {sub_value}\n"
                else:
                    markdown += f"- **{key.replace('_', ' ').title()}**: {value}\n"

        markdown += f"""\n## Next Steps (Optional)\n\n- [ ]  Review this report\n- [ ]  Discuss findings with team\n"""
        logger.info("Generated report for %s, task %s", sanitize_for_log(agent_name), sanitize_for_log(task_id))
        return markdown

    def generate_task_note(self, task_data: dict) -> str:
        """Generates a new task note from structured data.

        Args:
            task_data (dict): Structured task data to serialize or dispatch.

        Returns:
            str: String result produced by the operation.
        """
        title = task_data.get("title", "New Agent Task")
        agent = task_data.get("agent", "general")
        required_capability = task_data.get("required_capability")
        status = task_data.get("status", "pending")
        tags = task_data.get("tags", ["agent_task", agent.lower().replace(" ", "_")])
        capability_line = (
            f"required_capability: {required_capability}\n"
            if required_capability
            else ""
        )

        markdown = (
            f"---\n"
            f"task_id: {task_data.get('task_id', 'AUTO_GEN_ID')}\n"
            f"agent: {agent}\n"
            f"status: {status}\n"
            f"{capability_line}"
            f"tags: {tags}\n"
            f"---\n\n"
            f"# {title}\n\n"
        )
        if "context" in task_data:
            markdown += f"## Context\n{task_data['context']}\n\n"
        if "keywords" in task_data:
            markdown += f"Keywords: {task_data['keywords']}\n\n"
        if "target" in task_data:
            markdown += f"Target: {task_data['target']}\n\n"

        if "subtasks" in task_data and task_data["subtasks"]:
            markdown += "## Subtasks\n"
            for subtask in task_data["subtasks"]:
                checkbox = "[x]" if subtask.get("completed") else "[ ]"
                markdown += f"- {checkbox} {subtask['text']}\n"

        logger.info("Generated task note for '%s'", sanitize_for_log(title))
        return markdown
