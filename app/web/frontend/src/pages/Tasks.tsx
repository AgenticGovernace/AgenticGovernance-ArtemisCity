import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
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
import React, { useEffect, useState } from 'react';
import { createNewTask, executePendingTask, fetchAgents, fetchTasks } from '../api';

interface Task {
  relative_path: string;
  task_id: string;
  agent: string;
  status: string;
  title: string;
  context?: string;
  keywords?: string;
  target?: string;
  subtasks?: Array<{ text: string; completed: boolean }>;
}

interface Agent {
  name: string;
}

const Tasks = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

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
      await createNewTask(newTask);
      toast({
        title: 'Task created.',
        description: 'Your new task has been added to Obsidian.',
        status: 'success',
        duration: 5000,
        isClosable: true,
      });
      onClose();
      setNewTask({ agent: agents[0]?.name || '', title: '', context: '', keywords: '' });
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
      <Flex justifyContent="space-between" alignItems="center" mb={4}>
        <Heading as="h2" size="xl">
          Tasks
        </Heading>
        <Button colorScheme="blue" onClick={onOpen}>
          Create New Task
        </Button>
      </Flex>

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
          {tasks.map((task) => (
            <Tr key={task.relative_path}>
              <Td>{task.title}</Td>
              <Td>{task.agent}</Td>
              <Td>
                <Badge
                  colorScheme={
                    task.status === 'pending'
                      ? 'yellow'
                      : task.status === 'in progress'
                        ? 'blue'
                        : task.status === 'completed'
                          ? 'green'
                          : 'red'
                  }
                >
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
