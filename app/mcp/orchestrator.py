def _sanitize_for_log(value) -> str:
    """Convert values to a single-line printable representation for logging."""
    text = str(value)
    return "".join(
        ch if ch.isprintable() and ch not in "\n\r\t" else " " for ch in text
    )


class Orchestrator:
    # ... existing code ...
    _DEFAULT_TASK_ID = "unknown_task"

    # ... existing code ...

    def _ensure_obsidian_agent_dirs(self) -> None:
        """Ensures the necessary Obsidian directories for agent interaction exist."""
        self.obs_manager.create_folder(AGENT_INPUT_DIR)
        self.obs_manager.create_folder(AGENT_OUTPUT_DIR)
        logger.info(
            "Ensured Obsidian agent input/output directories: %s, %s",
            _sanitize_for_log(AGENT_INPUT_DIR),
            _sanitize_for_log(AGENT_OUTPUT_DIR),
        )

    def _validate_kernel_state(self) -> None:
        """Validates kernel state and reports registered agents."""
        registered_agents = self.agent_registry.get_agent_names()
        if not registered_agents:
            logger.error("KERNEL ERROR: No agents registered in the registry!")
            return

        logger.info(
            "Kernel registered %s agent(s): %s",
            len(registered_agents),
            _sanitize_for_log(", ".join(registered_agents)),
        )

        # Verify each agent has required methods
        for agent_obj in self.agent_registry.get_all_agents():
            if not hasattr(agent_obj, "perform_task"):
                logger.warning(
                    "Agent '%s' missing 'perform_task' method",
                    _sanitize_for_log(agent_obj.name),
                )
            else:
                logger.debug("✓ %s validated", _sanitize_for_log(agent_obj.name))

    def _normalize_required_capability(
        self, task_context: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Optional[str]]:
        """
        Ensure task_context contains the resolved 'required_capability'.

        Returns:
            (normalized_task_context, resolved_capability)
        """
        resolved = self._resolve_required_capability(task_context)
        if not resolved:
            return task_context, None

        if task_context.get("required_capability") == resolved:
            return task_context, resolved

        normalized = dict(task_context)
        normalized["required_capability"] = resolved
        return normalized, resolved

    def _update_task_status_if_possible(
        self,
        original_task_note_path: Optional[str],
        new_status: str,
        task_id: Optional[str],
    ) -> None:
        """Update task status only when a note path is provided."""
        if not original_task_note_path:
            return
        self.update_task_status_in_obsidian(
            original_task_note_path, new_status, task_id or self._DEFAULT_TASK_ID
        )

    def route_and_execute_task(
        self,
        task_context: Dict[str, Any],
        original_task_note_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route a task to the best agent and execute it.
        """
        try:
            task_context, resolved_capability = self._normalize_required_capability(
                task_context
            )
            if not resolved_capability:
                raise ValueError(
                    "Task dictionary must contain a 'required_capability' key or provide a known agent."
                )

            agent_name = self.agent_registry.route_task(task_context)
            logger.info("Task routed to '%s'.", _sanitize_for_log(agent_name))
            return self.assign_and_execute_task(
                agent_name, task_context, original_task_note_path
            )
        except (ValueError, KeyError) as e:
            logger.error("Task routing failed.", exc_info=True)
            self._update_task_status_if_possible(
                original_task_note_path,
                "routing_failed",
                task_context.get("task_id"),
            )
            return {"status": "failed", "error": str(e)}

    def assign_and_execute_task(
        self,
        agent_name: str,
        task_context: Dict[str, Any],
        original_task_note_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Assign a task to a specific agent and execute it.
        """
        task_start_time = time.perf_counter()
        run_logger = _get_run_logger()

        agent = self.agent_registry.get_agent(agent_name)
        if not agent:
            logger.error("Agent '%s' not found in registry.", _sanitize_for_log(agent_name))
            raise ValueError(
                f"Agent '{agent_name}' not registered with the orchestrator."
            )

        logger.info("Orchestrator assigning task to %s...", _sanitize_for_log(agent_name))

        task_id = task_context.get("task_id", "auto_generated")
        task_success = False

        if run_logger:
            run_logger.log_event(
                "task_start",
                "orchestrator",
                {
                    "task_id": task_id,
                    "agent": agent_name,
                    "capability": task_context.get("required_capability"),
                },
                f"Starting task {task_id} with {agent_name}",
            )

        try:
            enriched_context = self._enrich_task_with_memory(task_context)
            results = agent.perform_task(enriched_context)
            result_summary = results.get("summary", "N/A")
            logger.info(
                "Agent %s completed task. Results: %s",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(result_summary),
            )

            task_success = results.get("status") != "failed"

            report_filename = (
                f"{agent_name.replace(' ', '_')}_Report_{task_id}_{len(results)}.md"
            )
            report_md = self.obs_generator.generate_agent_report(
                agent_name, task_id, results
            )
            report_path = f"{AGENT_OUTPUT_DIR}/{report_filename}"
            try:
                self.memory_bus.write_note_with_embedding(
                    report_path,
                    report_md,
                    metadata={"agent": agent_name, "task_id": task_id},
                )
            except Exception:
                logger.error(
                    "Failed to persist report for %s.",
                    _sanitize_for_log(agent_name),
                    exc_info=True,
                )

            self._update_task_status_if_possible(
                original_task_note_path, "completed", task_id
            )

        except Exception as e:
            logger.error(
                "Agent %s failed on task %s.",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(task_id),
                exc_info=True,
            )
            task_success = False
            results = {
                "status": "failed",
                "error": str(e),
                "summary": f"Task failed: {e}",
            }

            self._update_task_status_if_possible(original_task_note_path, "failed", task_id)

        self._update_hebbian_weights(agent_name, task_id, task_success)

        task_duration_ms = (time.perf_counter() - task_start_time) * 1000
        if run_logger:
            run_logger.log_task_execution(
                task_id=task_id,
                agent_name=agent_name,
                status="completed" if task_success else "failed",
                duration_ms=task_duration_ms,
                metadata={
                    "capability": task_context.get("required_capability"),
                    "summary": results.get("summary", "")[:100],
                },
            )

        return results

    def check_for_new_tasks_from_obsidian(self) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Scan the Obsidian input directory for new pending tasks.
        """
        logger.info(
            "Checking for new tasks in Obsidian folder: %s",
            _sanitize_for_log(AGENT_INPUT_DIR),
        )
        input_notes = self.obs_manager.list_notes_in_folder(AGENT_INPUT_DIR)

        new_tasks: List[Tuple[str, Dict[str, Any]]] = []
        for note_filename in input_notes:
            relative_path = os.path.join(AGENT_INPUT_DIR, note_filename)
            content = self.obs_manager.read_note(relative_path)
            if content:
                task_data = self.obs_parser.parse_task_note(content)
                if task_data and task_data.get("status", "pending").lower() == "pending":
                    task_data = dict(task_data)
                    task_data["task_id"] = task_data.get(
                        "task_id", f"task_{hash(note_filename) % 100000}"
                    )

                    task_data, _ = self._normalize_required_capability(task_data)

                    logger.info(
                        "Found new pending task: '%s' for agent '%s'",
                        _sanitize_for_log(task_data.get("title", note_filename)),
                        _sanitize_for_log(task_data.get("agent")),
                    )
                    new_tasks.append((relative_path, task_data))
                else:
                    logger.debug(
                        "Note '%s' is not a pending task or couldn't be parsed.",
                        _sanitize_for_log(note_filename),
                    )

        return new_tasks

    def update_task_status_in_obsidian(
        self, relative_note_path: str, new_status: str, task_id: Optional[str] = None
    ) -> None:
        """
        Updates the status of a specific task note in Obsidian.
        """
        logger.info(
            "Updating status for task note '%s' to '%s'",
            _sanitize_for_log(relative_note_path),
            _sanitize_for_log(new_status),
        )
        original_content = self.obs_manager.read_note(relative_note_path)
        if original_content:
            updated_content = self.obs_parser.update_status_in_note(
                original_content, new_status, task_id
            )
            try:
                self.memory_bus.write_note_with_embedding(
                    relative_note_path,
                    updated_content,
                    metadata={"task_id": task_id, "status": new_status},
                )
            except Exception:
                logger.error(
                    "Memory bus write failed for %s.",
                    _sanitize_for_log(relative_note_path),
                    exc_info=True,
                )
                self.obs_manager.write_note(relative_note_path, updated_content)
            logger.info(
                "Status updated for '%s' to '%s'.",
                _sanitize_for_log(relative_note_path),
                _sanitize_for_log(new_status),
            )
        else:
            logger.warning(
                "Could not read original content for '%s' to update status.",
                _sanitize_for_log(relative_note_path),
            )

    def create_new_task_in_obsidian(
        self, task_data: Dict[str, Any], filename: Optional[str] = None
    ) -> str:
        """
        Creates a new task note in the AGENT_INPUT_DIR of Obsidian.
        Returns the relative path to the new note.
        """
        task_title = task_data.get("title", "new_agent_task")

        task_data, resolved_capability = self._normalize_required_capability(task_data)
        if not resolved_capability:
            logger.warning(
                "No required_capability provided or inferred for task '%s'. Task may not be routed correctly.",
                _sanitize_for_log(task_title),
            )

        if not filename:
            title_slug = task_title.lower().replace(" ", "_")
            filename = f"{title_slug}_{datetime.now().strftime('%Y%m%d%H%M%S')}.md"

        relative_path = os.path.join(AGENT_INPUT_DIR, filename)
        markdown_content = self.obs_generator.generate_task_note(task_data)
        try:
            self.memory_bus.write_note_with_embedding(
                relative_path,
                markdown_content,
                metadata={
                    "task_id": task_data.get("task_id"),
                    "created_by": "orchestrator",
                },
            )
        except Exception:
            logger.error(
                "Failed to persist new task to memory bus for %s.",
                _sanitize_for_log(relative_path),
                exc_info=True,
            )
            self.obs_manager.write_note(relative_path, markdown_content)
        logger.info(
            "Created new task note in Obsidian: %s",
            _sanitize_for_log(relative_path),
        )
        return relative_path

    def execute_all_pending_tasks(self) -> Dict[str, Any]:
        """
        Executes every pending task discovered in the Obsidian input directory.
        Returns a summary with counts and per-task results.
        """
        pending_tasks = self.check_for_new_tasks_from_obsidian()
        summary: Dict[str, Any] = {
            "total": len(pending_tasks),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        if not pending_tasks:
            logger.info("No pending tasks found to execute.")
            return summary

        logger.info("Executing %s pending task(s) from Obsidian.", len(pending_tasks))

        for relative_note_path, task_data in pending_tasks:
            task_id = task_data.get("task_id", self._DEFAULT_TASK_ID)

            task_data, resolved_capability = self._normalize_required_capability(task_data)
            if not resolved_capability:
                logger.warning(
                    "Skipping task %s at %s: no required_capability found or inferred.",
                    _sanitize_for_log(task_id),
                    _sanitize_for_log(relative_note_path),
                )
                self.update_task_status_in_obsidian(
                    relative_note_path, "no_capability", task_id
                )
                summary["skipped"] += 1
                summary["details"].append(
                    {"task_id": task_id, "status": "skipped", "reason": "no_capability"}
                )
                continue

            try:
                self.update_task_status_in_obsidian(
                    relative_note_path, "in progress", task_id
                )
                self.route_and_execute_task(task_data, relative_note_path)
                summary["completed"] += 1
                summary["details"].append({"task_id": task_id, "status": "completed"})
            except Exception as exc:
                logger.error(
                    "Failed to execute task %s from %s.",
                    _sanitize_for_log(task_id),
                    _sanitize_for_log(relative_note_path),
                    exc_info=True,
                )
                self.update_task_status_in_obsidian(
                    relative_note_path, "failed", task_id
                )
                summary["failed"] += 1
                summary["details"].append(
                    {"task_id": task_id, "status": "failed", "error": str(exc)}
                )

        return summary
