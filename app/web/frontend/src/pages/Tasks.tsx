import {
  Badge,
  Box,
  Button,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Table,
  Tbody,
  Td,
  Text,
  Textarea,
  Th,
  Thead,
  Tr,
  useDisclosure,
  useToast,
  VStack,
} from '@chakra-ui/react';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom';
import {
  createNewTask,
  executePendingTask,
  fetchAgents,
  fetchTasks,
  getUserFacingErrorMessage,
  isAbortError,
  type AgentSummary,
  type TaskRecord,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { routePaths } from '../router/paths';

interface NewTask {
  agent: string;
  title: string;
  context: string;
  keywords: string;
}

const STATUS_FILTERS = ['all', 'pending', 'in progress', 'completed', 'failed'] as const;

const Tasks = () => {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [executingTaskPath, setExecutingTaskPath] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const requestedStatus = (searchParams.get('status') || 'all').toLowerCase();
  const statusFilter = STATUS_FILTERS.includes(
    requestedStatus as (typeof STATUS_FILTERS)[number]
  )
    ? requestedStatus
    : 'all';

  const { isOpen, onOpen, onClose } = useDisclosure();
  const [newTask, setNewTask] = useState<NewTask>({
    agent: '',
    title: '',
    context: '',
    keywords: '',
  });

  const createTaskRequestController = useRequestController();
  const createAgentRequestController = useRequestController();
  const createTaskCreationController = useRequestController();
  const createTaskExecutionController = useRequestController();

  const loadTasks = useCallback(async () => {
    const controller = createTaskRequestController();
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTasks({ signal: controller.signal });
      setTasks(data);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err, 'Failed to fetch tasks.'));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [createTaskRequestController]);

  const loadAgents = useCallback(async () => {
    const controller = createAgentRequestController();
    try {
      const data = await fetchAgents({ signal: controller.signal });
      setAgents(data);
      if (data.length > 0) {
        setNewTask((prev) => ({ ...prev, agent: data[0].name }));
      }
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err, 'Failed to fetch agents.'));
    }
  }, [createAgentRequestController]);

  useEffect(() => {
    void loadTasks();
    void loadAgents();
  }, [loadAgents, loadTasks]);

  const handleCreateTask = async () => {
    if (creating) return;
    const controller = createTaskCreationController();
    setCreating(true);
    try {
      const created = await createNewTask(newTask, { signal: controller.signal });
      toast({
        title: 'Task created.',
        description: 'Your new task has been added to Obsidian.',
        status: 'success',
        duration: 5000,
        isClosable: true,
      });
      onClose();
      setNewTask({ agent: agents[0]?.name || '', title: '', context: '', keywords: '' });
      if (created.task_id) {
        navigate(routePaths.task(created.task_id));
      } else {
        await loadTasks();
      }
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      toast({
        title: 'Error creating task.',
        description: getUserFacingErrorMessage(err, 'The task could not be created.'),
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
    } finally {
      if (!controller.signal.aborted) setCreating(false);
    }
  };

  const handleStatusFilterChange = (value: string) => {
    const nextParams = new URLSearchParams(searchParams);
    if (value === 'all') {
      nextParams.delete('status');
    } else {
      nextParams.set('status', value);
    }
    setSearchParams(nextParams, { replace: true });
  };

  const visibleTasks =
    statusFilter === 'all'
      ? tasks
      : tasks.filter((task) => task.status.toLowerCase() === statusFilter);

  const handleExecuteTask = async (task: TaskRecord) => {
    if (executingTaskPath) return;
    const controller = createTaskExecutionController();
    setExecutingTaskPath(task.relative_path);
    try {
      await executePendingTask(task.relative_path, { signal: controller.signal });
      toast({
        title: 'Task execution initiated.',
        description: `Task "${task.title}" is being processed by ${task.agent}.`,
        status: 'info',
        duration: 5000,
        isClosable: true,
      });
      await loadTasks();
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      toast({
        title: 'Error executing task.',
        description: getUserFacingErrorMessage(err, 'The task could not be submitted.'),
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
    } finally {
      if (!controller.signal.aborted) setExecutingTaskPath(null);
    }
  };

  if (loading) return <RouteStatus status="loading" message="Loading tasks…" />;

  if (error) {
    return <RouteStatus status="error" message={error} onRetry={() => void loadTasks()} />;
  }

  return (
    <Box>
      <Flex
        justifyContent="space-between"
        alignItems={{ base: 'stretch', md: 'center' }}
        gap={3}
        mb={4}
        flexWrap="wrap"
      >
        <Heading as="h2" size="xl">
          Tasks
        </Heading>
        <Flex align="center" gap={3}>
          <Select
            aria-label="Filter tasks by status"
            value={statusFilter}
            onChange={(event) => handleStatusFilterChange(event.target.value)}
            maxW="190px"
          >
            {STATUS_FILTERS.map((status) => (
              <option key={status} value={status}>
                {status === 'all' ? 'All statuses' : status}
              </option>
            ))}
          </Select>
          <Button colorScheme="blue" onClick={onOpen}>
            Create New Task
          </Button>
        </Flex>
      </Flex>

      <Text color="gray.400" mb={4}>
        Showing {visibleTasks.length} of {tasks.length} tasks
      </Text>

      <Table variant="simple">
        <Thead>
          <Tr>
            <Th>Title</Th>
            <Th>Agent</Th>
            <Th>Status</Th>
            <Th>Task ID</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {visibleTasks.length === 0 ? (
            <Tr>
              <Td colSpan={5}>
                <Text color="gray.400">
                  {tasks.length === 0 ? 'No tasks found.' : 'No tasks match this status.'}
                </Text>
              </Td>
            </Tr>
          ) : (
            visibleTasks.map((task) => {
              const normalizedStatus = task.status.toLowerCase();
              return (
                <Tr key={task.relative_path}>
                  <Td>
                    <RouterLink to={routePaths.task(task.task_id)}>{task.title}</RouterLink>
                  </Td>
                  <Td>{task.agent}</Td>
                  <Td>
                    <Badge
                      colorScheme={
                        normalizedStatus === 'pending'
                          ? 'yellow'
                          : normalizedStatus === 'in progress'
                            ? 'blue'
                            : normalizedStatus === 'completed'
                              ? 'green'
                              : 'red'
                      }
                    >
                      {task.status}
                    </Badge>
                  </Td>
                  <Td>{task.task_id}</Td>
                  <Td>
                    <Flex gap={2}>
                      <Button as={RouterLink} to={routePaths.task(task.task_id)} size="sm">
                        View
                      </Button>
                      {normalizedStatus === 'pending' && (
                        <Button
                          size="sm"
                          colorScheme="green"
                          onClick={() => handleExecuteTask(task)}
                          isLoading={executingTaskPath === task.relative_path}
                          isDisabled={executingTaskPath !== null}
                        >
                          Execute
                        </Button>
                      )}
                    </Flex>
                  </Td>
                </Tr>
              );
            })
          )}
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
                  onChange={(e) => setNewTask({ ...newTask, agent: e.target.value })}
                >
                  {agents.map((agent) => (
                    <option key={agent.name} value={agent.name}>
                      {agent.name}
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
            <Button colorScheme="blue" mr={3} onClick={handleCreateTask} isLoading={creating}>
              Create
            </Button>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  );
};

export default Tasks;
