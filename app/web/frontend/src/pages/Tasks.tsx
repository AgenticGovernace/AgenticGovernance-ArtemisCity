import {
  Alert,
  AlertIcon,
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
  Spinner,
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
import { useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom';
import { createNewTask, executePendingTask, fetchAgents, fetchTasks } from '../api';
import { routePaths } from '../router/paths';

interface Task {
  relative_path: string;
  task_id: string;
  agent: string;
  status: string;
  title: string;
  required_capability?: string;
  context?: string;
  keywords?: string;
  target?: string;
  subtasks?: Array<{ text: string; completed: boolean }>;
}

interface Agent {
  name: string;
}

const STATUS_FILTERS = ['all', 'pending', 'in progress', 'completed', 'failed'] as const;

const Tasks = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
  const [newTask, setNewTask] = useState<any>({
    agent: '',
    title: '',
    context: '',
    keywords: '',
  });

  const loadTasks = async () => {
    try {
      setLoading(true);
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
      const data = await fetchAgents();
      setAgents(data);
      if (data.length > 0) {
        setNewTask((prev: any) => ({ ...prev, agent: data[0].name }));
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
      const created = (await createNewTask(newTask)) as { task_id?: string };
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
            <Button colorScheme="blue" mr={3} onClick={handleCreateTask}>
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
