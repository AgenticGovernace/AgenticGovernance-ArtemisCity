import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Code,
  Divider,
  Heading,
  List,
  ListItem,
  SimpleGrid,
  Spinner,
  Text,
  useToast,
  VStack,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { executePendingTask, fetchTask } from '../api';
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
  subtasks?: Array<{ text: string; completed: boolean }> | null;
}

const statusColor = (status: string): string => {
  switch (status.toLowerCase()) {
    case 'pending':
      return 'yellow';
    case 'in progress':
      return 'blue';
    case 'completed':
      return 'green';
    default:
      return 'red';
  }
};

const TaskDetails = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    let cancelled = false;

    const loadTask = async () => {
      setLoading(true);
      setError(null);
      setTask(null);

      if (!taskId) {
        setError('Task not found.');
        setLoading(false);
        return;
      }

      try {
        const found = (await fetchTask(taskId)) as Task;
        if (!cancelled) {
          if (found) {
            setTask(found);
          } else {
            setError('Task not found.');
          }
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : '';
          setError(message.includes('status: 404') ? 'Task not found.' : 'Failed to load this task.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void loadTask();
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const handleExecuteTask = async () => {
    if (!task || task.status.toLowerCase() !== 'pending' || executing) return;

    setExecuting(true);
    try {
      // Use the server-returned note path. The browser route parameter is
      // only an identifier used to select this task record.
      await executePendingTask(task.relative_path);
      setTask((current) => (current ? { ...current, status: 'in progress' } : current));
      toast({
        title: 'Task execution initiated.',
        description: `Task "${task.title}" is being processed by ${task.agent}.`,
        status: 'info',
        duration: 5000,
        isClosable: true,
      });
    } catch {
      toast({
        title: 'Unable to execute task.',
        description: 'The task could not be submitted to the dashboard API.',
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
    } finally {
      setExecuting(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" mt={8}>
        <Spinner size="xl" />
        <Text>Loading task...</Text>
      </Box>
    );
  }

  if (error || !task) {
    return (
      <VStack align="stretch" spacing={4} py={8}>
        <Alert status={error === 'Task not found.' ? 'warning' : 'error'}>
          <AlertIcon />
          {error ?? 'Task not found.'}
        </Alert>
        <Box>
          <Button as={RouterLink} to={routePaths.tasks} colorScheme="blue">
            Back to tasks
          </Button>
        </Box>
      </VStack>
    );
  }

  return (
    <Box maxW="1000px">
      <Button as={RouterLink} to={routePaths.tasks} variant="link" mb={4}>
        ← Back to tasks
      </Button>

      <VStack align="stretch" spacing={5}>
        <Box>
          <Heading as="h1" size="xl" mb={3}>
            {task.title}
          </Heading>
          <Badge colorScheme={statusColor(task.status)}>{task.status}</Badge>
        </Box>

        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          <Box>
            <Text fontSize="sm" color="gray.400">
              Task ID
            </Text>
            <Text fontWeight="semibold" wordBreak="break-word">
              {task.task_id}
            </Text>
          </Box>
          <Box>
            <Text fontSize="sm" color="gray.400">
              Agent
            </Text>
            <Text fontWeight="semibold">{task.agent || 'Unassigned'}</Text>
          </Box>
          <Box>
            <Text fontSize="sm" color="gray.400">
              Required capability
            </Text>
            <Text fontWeight="semibold">{task.required_capability || 'Not specified'}</Text>
          </Box>
        </SimpleGrid>

        {task.status.toLowerCase() === 'pending' && (
          <Box>
            <Button colorScheme="green" onClick={handleExecuteTask} isLoading={executing}>
              Execute pending task
            </Button>
          </Box>
        )}

        <Divider />

        <Box>
          <Heading as="h2" size="md" mb={2}>
            Context
          </Heading>
          <Text whiteSpace="pre-wrap" color="gray.200">
            {task.context || 'No context provided.'}
          </Text>
        </Box>

        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={5}>
          <Box>
            <Heading as="h2" size="md" mb={2}>
              Keywords
            </Heading>
            <Text color="gray.200">{task.keywords || 'No keywords provided.'}</Text>
          </Box>
          <Box>
            <Heading as="h2" size="md" mb={2}>
              Target
            </Heading>
            <Text color="gray.200">{task.target || 'No target provided.'}</Text>
          </Box>
        </SimpleGrid>

        <Box>
          <Heading as="h2" size="md" mb={2}>
            Subtasks
          </Heading>
          {task.subtasks && task.subtasks.length > 0 ? (
            <List spacing={2}>
              {task.subtasks.map((subtask, index) => (
                <ListItem key={`${subtask.text}-${index}`}>
                  <Text as="span" mr={2} color={subtask.completed ? 'green.300' : 'yellow.300'}>
                    {subtask.completed ? '✓' : '○'}
                  </Text>
                  {subtask.text}
                </ListItem>
              ))}
            </List>
          ) : (
            <Text color="gray.400">No subtasks recorded.</Text>
          )}
        </Box>

        <Box>
          <Text fontSize="sm" color="gray.400" mb={1}>
            Source note
          </Text>
          <Code>{task.relative_path}</Code>
        </Box>
      </VStack>
    </Box>
  );
};

export default TaskDetails;
