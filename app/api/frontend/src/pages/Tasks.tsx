/**
 * Tasks Page Component
 *
 * Comprehensive task management interface for the MCP Dashboard.
 * Supports viewing, creating, and executing tasks stored in the
 * Obsidian vault.
 *
 * Features:
 * - Task table with status badges
 * - Create new task modal with agent/capability selection
 * - Execute individual tasks or batch execute all pending
 * - Real-time status updates via toast notifications
 *
 * @module Tasks
 */

import {
  Box,
  Flex,
  Heading,
  Text,
  Spinner,
  Alert,
  AlertIcon,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Button,
  useDisclosure,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  FormControl,
  FormLabel,
  Input,
  Textarea,
  Select,
  VStack,
  useToast,
  Badge,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { fetchTasks, createNewTask, fetchAgents, executePendingTask, executeAllPendingTasks } from '../api';

/**
 * Interface representing a task entity from the Obsidian vault.
 */
interface Task {
  /** Relative path to the task file in the vault */
  relative_path: string;
  /** Unique task identifier */
  task_id: string;
  /** Name of the assigned agent */
  agent: string;
  /** Current task status (pending, in progress, completed) */
  status: string;
  /** Task title */
  title: string;
  /** Required capability for the agent */
  required_capability?: string;
  /** Task context or description */
  context?: string;
  /** Comma-separated keywords */
  keywords?: string;
  /** Target path or scope */
  target?: string;
  /** List of subtasks with completion status */
  subtasks?: Array<{ text: string; completed: boolean }>;
}

/**
 * Interface representing an agent with capabilities.
 */
interface Agent {
  /** Agent name */
  name: string;
  /** List of capabilities the agent can perform */
  capabilities?: string[];
}

/**
 * Type for new task form data.
 */
type NewTask = {
  agent: string;
  title: string;
  context: string;
  keywords: string;
  required_capability?: string;
};

/**
 * Tasks management page component.
 *
 * Provides a full-featured interface for managing tasks:
 * - View all tasks in a table with status badges
 * - Create new tasks via modal form
 * - Execute individual pending tasks
 * - Batch execute all pending tasks
 *
 * @returns The rendered tasks page
 */
const Tasks = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const { isOpen, onOpen, onClose } = useDisclosure();
  const [newTask, setNewTask] = useState<NewTask>({
    agent: '',
    title: '',
    context: '',
    keywords: '',
    required_capability: '',
  });
  const availableCapabilities =
    agents.find((agent) => agent.name === newTask.agent)?.capabilities || [];

  const loadTasks = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchTasks();
      setTasks(data);
    } catch (err) {
      setError('Failed to fetch tasks.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadAgents = async () => {
    try {
      setError(null);
      const data = await fetchAgents();
      setAgents(data);
      if (data.length > 0) {
        const firstAgent = data[0];
        setNewTask((prev) => ({
          ...prev,
          agent: firstAgent.name,
          required_capability: firstAgent.capabilities?.[0] || '',
        }));
      }
    } catch (err) {
      setError('Failed to fetch agents.');
      console.error(err);
    }
  };

  useEffect(() => {
    loadTasks();
    loadAgents();
  }, []);

  const handleCreateTask = async () => {
    try {
      const capability = newTask.required_capability || availableCapabilities[0] || '';
      if (!newTask.agent || !capability) {
        toast({
          title: 'Missing details.',
          description: 'Please select an agent and capability for this task.',
          status: 'warning',
          duration: 4000,
          isClosable: true,
        });
        return;
      }

      const payload = { ...newTask, required_capability: capability };
      await createNewTask(payload);
      toast({
        title: 'Task created.',
        description: "Your new task has been added to Obsidian.",
        status: 'success',
        duration: 5000,
        isClosable: true,
      });
      onClose();
      const defaultAgent = agents.find((agent) => agent.name === payload.agent) || agents[0];
      setNewTask({
        agent: defaultAgent?.name || '',
        title: '',
        context: '',
        keywords: '',
        required_capability: defaultAgent?.capabilities?.[0] || '',
      });
      loadTasks(); // Reload tasks to show the new one
    } catch (err) {
      toast({
        title: 'Error creating task.',
        description: (err as Error).message,
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
      console.error(err);
    }
  };

  const handleExecuteTask = async (task: Task) => {
    try {
      await executePendingTask(task.relative_path);
      toast({
        title: 'Task execution initiated.',
        description: `Task "${task.title}" is being processed by ${task.agent}.`,
        status: 'info',
        duration: 5000,
        isClosable: true,
      });
      loadTasks(); // Reload tasks to see status change
    } catch (err) {
      toast({
        title: 'Error executing task.',
        description: (err as Error).message,
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
      console.error(err);
    }
  };

  const handleExecuteAllPending = async () => {
    const pendingTasks = tasks.filter((task) => task.status === 'pending');
    if (pendingTasks.length === 0) {
      toast({
        title: 'No pending tasks.',
        description: 'There are no pending tasks to run.',
        status: 'info',
        duration: 4000,
        isClosable: true,
      });
      return;
    }

    const confirmed = window.confirm(`Run all ${pendingTasks.length} pending task(s)?`);
    if (!confirmed) {
      return;
    }

    try {
      const summary = await executeAllPendingTasks();
      toast({
        title: 'Batch execution requested.',
        description: `Completed: ${summary.completed ?? 0}, Failed: ${summary.failed ?? 0}, Skipped: ${summary.skipped ?? 0}`,
        status: summary.failed ? 'warning' : 'success',
        duration: 6000,
        isClosable: true,
      });
      loadTasks();
    } catch (err) {
      toast({
        title: 'Error executing pending tasks.',
        description: (err as Error).message,
        status: 'error',
        duration: 6000,
        isClosable: true,
      });
      console.error(err);
    }
  };


  if (loading) {
    return (
      <Box textAlign="center" mt={8}>
        <Spinner size="xl" />
        <Text>Loading tasks...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert status="error" mt={8}>
        <AlertIcon />
        {error}
      </Alert>
    );
  }

  return (
    <Box>
      <Flex justifyContent="space-between" alignItems="center" mb={4} gap={2} flexWrap="wrap">
        <Heading as="h2" size="xl">Tasks</Heading>
        <Flex gap={2}>
          <Button variant="outline" onClick={handleExecuteAllPending}>Run All Pending</Button>
          <Button colorScheme="blue" onClick={onOpen}>Create New Task</Button>
        </Flex>
      </Flex>

      <Table variant="simple">
        <Thead>
          <Tr>
            <Th>Title</Th>
            <Th>Agent</Th>
            <Th>Capability</Th>
            <Th>Status</Th>
            <Th>Task ID</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {tasks.map((task) => (
            <Tr key={task.relative_path}>
              <Td>{task.title}</Td>
              <Td>{task.agent}</Td>
              <Td>{task.required_capability || '—'}</Td>
              <Td>
                <Badge colorScheme={
                  task.status === 'pending' ? 'yellow' :
                  task.status === 'in progress' ? 'blue' :
                  task.status === 'completed' ? 'green' : 'red'
                }>
                  {task.status}
                </Badge>
              </Td>
              <Td>{task.task_id}</Td>
              <Td>
                {task.status === 'pending' && (
                  <Button size="sm" colorScheme="green" onClick={() => handleExecuteTask(task)}>
                    Execute
                  </Button>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>

      <Modal isOpen={isOpen} onClose={onClose}>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Create New Task</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4}>
              <FormControl isRequired>
                <FormLabel>Agent</FormLabel>
                <Select
                  placeholder="Select agent"
                  value={newTask.agent}
                  onChange={(e) => {
                    const selectedAgent = agents.find((agent) => agent.name === e.target.value);
                    setNewTask({
                      ...newTask,
                      agent: e.target.value,
                      required_capability: selectedAgent?.capabilities?.[0] || '',
                    });
                  }}
                >
                  {agents.map((agent) => (
                    <option key={agent.name} value={agent.name}>
                      {agent.name}
                    </option>
                  ))}
                </Select>
              </FormControl>
              <FormControl isRequired>
                <FormLabel>Required Capability</FormLabel>
                <Select
                  placeholder={availableCapabilities.length ? 'Select capability' : 'No capabilities available'}
                  value={newTask.required_capability || ''}
                  onChange={(e) => setNewTask({ ...newTask, required_capability: e.target.value })}
                  isDisabled={availableCapabilities.length === 0}
                >
                  {availableCapabilities.map((capability) => (
                    <option key={capability} value={capability}>
                      {capability}
                    </option>
                  ))}
                </Select>
              </FormControl>
              <FormControl isRequired>
                <FormLabel>Title</FormLabel>
                <Input
                  value={newTask.title}
                  onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
                />
              </FormControl>
              <FormControl>
                <FormLabel>Context</FormLabel>
                <Textarea
                  value={newTask.context}
                  onChange={(e) => setNewTask({ ...newTask, context: e.target.value })}
                />
              </FormControl>
              <FormControl>
                <FormLabel>Keywords (comma-separated)</FormLabel>
                <Input
                  value={newTask.keywords}
                  onChange={(e) => setNewTask({ ...newTask, keywords: e.target.value })}
                />
              </FormControl>
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button colorScheme="blue" mr={3} onClick={handleCreateTask}>
              Create
            </Button>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  );
};

export default Tasks;
