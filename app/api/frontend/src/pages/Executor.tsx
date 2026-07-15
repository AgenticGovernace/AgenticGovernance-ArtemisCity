/**
 * CLI Executor Page Component
 *
 * Provides a form-based interface for executing CLI-style commands
 * with support for instruction, capability, and agent selection.
 *
 * @module Executor
 */

import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Select,
  Textarea,
  VStack,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Spinner,
  Text,
  Badge,
  Flex,
  SimpleGrid,
  Stat,
  StatLabel,
  StatNumber,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { executeInstruction, fetchAgents } from '../api';

/**
 * Interface for agent data
 */
interface Agent {
  name: string;
  capabilities?: string[];
}

/**
 * Interface for execution response
 */
interface ExecutionResult {
  task_id: string;
  status: string;
  summary: string;
  note_path?: string;
  error?: string;
}

/**
 * Executor Page Component
 *
 * Renders a form for executing CLI-style instructions through the
 * MCP executor with support for agent and capability selection.
 */
const Executor = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [instruction, setInstruction] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [capability, setCapability] = useState('');
  const [title, setTitle] = useState('');
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Predefined capabilities
  const capabilities = [
    'web_search',
    'text_summarization',
    'system_management',
    'agent_coordination',
    'document_analysis',
  ];

  // Load agents on mount
  useEffect(() => {
    const loadAgents = async () => {
      try {
        setLoadingAgents(true);
        const data = await fetchAgents();
        setAgents(data);
      } catch (err) {
        setError('Failed to load agents.');
        console.error(err);
      } finally {
        setLoadingAgents(false);
      }
    };
    loadAgents();
  }, []);

  const handleExecute = async () => {
    if (!instruction.trim()) {
      setError('Please enter an instruction.');
      return;
    }

    try {
      setExecuting(true);
      setError(null);
      setResult(null);

      const response = await executeInstruction({
        instruction,
        agent: selectedAgent || undefined,
        capability: capability || undefined,
        title: title || undefined,
      });

      setResult(response);

      // Clear form on success
      if (response.status === 'success') {
        setInstruction('');
        setSelectedAgent('');
        setCapability('');
        setTitle('');
      }
    } catch (err) {
      setError(`Execution failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
      console.error(err);
    } finally {
      setExecuting(false);
    }
  };

  const handleClear = () => {
    setInstruction('');
    setSelectedAgent('');
    setCapability('');
    setTitle('');
    setResult(null);
    setError(null);
  };

  return (
    <Box>
      <Heading as="h2" size="xl" mb={6}>
        CLI Executor
      </Heading>

      <Flex gap={8} flexDirection={{ base: 'column', lg: 'row' }}>
        {/* Form Section */}
        <Box flex={1} minW={{ lg: '400px' }}>
          <VStack spacing={4} align="stretch">
            {/* Instruction Input */}
            <FormControl isRequired>
              <FormLabel fontWeight="bold">Instruction</FormLabel>
              <Textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Enter your CLI instruction here...
Example: Search for recent advances in quantum computing
Or: Summarize the key findings from the reports folder"
                rows={6}
                isDisabled={executing}
                borderColor="blue.200"
                _focus={{ borderColor: 'blue.400' }}
              />
              <Text fontSize="xs" color="gray.500" mt={1}>
                Enter what you want the system to do. Be specific and clear.
              </Text>
            </FormControl>

            {/* Agent Selection */}
            <FormControl>
              <FormLabel fontWeight="bold">
                Agent (Optional: Auto-select by capability if not specified)
              </FormLabel>
              <Select
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
                placeholder="Select an agent..."
                isDisabled={executing || loadingAgents}
                borderColor="blue.200"
              >
                {agents.map((agent) => (
                  <option key={agent.name} value={agent.name}>
                    {agent.name}
                  </option>
                ))}
              </Select>
            </FormControl>

            {/* Capability Selection */}
            <FormControl>
              <FormLabel fontWeight="bold">Capability</FormLabel>
              <Select
                value={capability}
                onChange={(e) => setCapability(e.target.value)}
                placeholder="Select a capability..."
                isDisabled={executing}
                borderColor="blue.200"
              >
                <option value="">Default (auto-detect)</option>
                {capabilities.map((cap) => (
                  <option key={cap} value={cap}>
                    {cap}
                  </option>
                ))}
              </Select>
              <Text fontSize="xs" color="gray.500" mt={1}>
                Capability determines which agent capabilities are used.
              </Text>
            </FormControl>

            {/* Title Input */}
            <FormControl>
              <FormLabel fontWeight="bold">Title (Optional)</FormLabel>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Give this task a name (optional)"
                isDisabled={executing}
                borderColor="blue.200"
                _focus={{ borderColor: 'blue.400' }}
              />
            </FormControl>

            {/* Error Alert */}
            {error && (
              <Alert status="error" borderRadius="md">
                <AlertIcon />
                <Box>
                  <AlertTitle>Error</AlertTitle>
                  <AlertDescription fontSize="sm">{error}</AlertDescription>
                </Box>
              </Alert>
            )}

            {/* Execute and Clear Buttons */}
            <Flex gap={2}>
              <Button
                colorScheme="blue"
                onClick={handleExecute}
                isLoading={executing}
                loadingText="Executing..."
                isDisabled={!instruction.trim()}
                size="md"
                flex={1}
              >
                Execute Task
              </Button>
              <Button
                variant="outline"
                onClick={handleClear}
                isDisabled={executing}
                size="md"
              >
                Clear
              </Button>
            </Flex>

            {/* Help Text */}
            <Box
              p={3}
              bg="blue.50"
              borderRadius="md"
              borderLeft="4px solid"
              borderColor="blue.400"
            >
              <Text fontSize="xs" color="gray.700">
                <strong>Tips:</strong>
                <br />• Leave Agent blank to auto-select based on capability
                <br />• Leave Capability blank for automatic detection
                <br />• Add a Title to easily reference this task later
              </Text>
            </Box>
          </VStack>
        </Box>

        {/* Results Section */}
        <Box flex={1} minW={{ lg: '400px' }}>
          {executing && (
            <Box textAlign="center" py={8}>
              <Spinner size="lg" color="blue.500" mb={4} />
              <Text fontSize="lg" fontWeight="bold">
                Executing...
              </Text>
              <Text fontSize="sm" color="gray.600" mt={2}>
                Your instruction is being processed
              </Text>
            </Box>
          )}

          {result && !executing && (
            <VStack spacing={4} align="stretch">
              <Box borderWidth={1} borderRadius="md" p={4} borderColor="gray.200">
                {/* Status Badge */}
                <Flex justify="space-between" align="center" mb={4}>
                  <Text fontWeight="bold" fontSize="lg">
                    Execution Results
                  </Text>
                  <Badge
                    colorScheme={
                      result.status === 'success' ? 'green' : 'red'
                    }
                    fontSize="md"
                    px={3}
                    py={1}
                  >
                    {result.status.toUpperCase()}
                  </Badge>
                </Flex>

                {/* Task ID */}
                <SimpleGrid columns={2} spacing={3} mb={4}>
                  <Stat>
                    <StatLabel fontSize="xs">Task ID</StatLabel>
                    <StatNumber fontSize="sm" wordBreak="break-all">
                      {result.task_id}
                    </StatNumber>
                  </Stat>
                  {result.note_path && (
                    <Stat>
                      <StatLabel fontSize="xs">Note Path</StatLabel>
                      <StatNumber fontSize="sm" wordBreak="break-all">
                        {result.note_path}
                      </StatNumber>
                    </Stat>
                  )}
                </SimpleGrid>

                {/* Summary */}
                <Box mb={4}>
                  <Text fontWeight="bold" fontSize="sm" mb={2}>
                    Summary
                  </Text>
                  <Box
                    p={3}
                    bg="gray.50"
                    borderRadius="md"
                    fontSize="sm"
                    borderLeft="4px solid"
                    borderColor={
                      result.status === 'success' ? 'green.400' : 'red.400'
                    }
                  >
                    <Text>{result.summary}</Text>
                  </Box>
                </Box>

                {/* Error Details */}
                {result.error && (
                  <Alert status="error" borderRadius="md">
                    <AlertIcon />
                    <Box>
                      <AlertTitle fontSize="sm">Error Details</AlertTitle>
                      <AlertDescription fontSize="sm">
                        {result.error}
                      </AlertDescription>
                    </Box>
                  </Alert>
                )}

                {/* Success Message */}
                {result.status === 'success' && (
                  <Alert status="success" borderRadius="md">
                    <AlertIcon />
                    <Box>
                      <AlertTitle fontSize="sm">Task Completed</AlertTitle>
                      <AlertDescription fontSize="sm">
                        Your instruction was executed successfully.
                        {result.note_path && ` Check the output at ${result.note_path}`}
                      </AlertDescription>
                    </Box>
                  </Alert>
                )}
              </Box>

              {/* Action Buttons */}
              <Flex gap={2}>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleClear}
                  flex={1}
                >
                  New Task
                </Button>
                {result.note_path && (
                  <Button
                    size="sm"
                    colorScheme="blue"
                    flex={1}
                    onClick={() => {
                      // In production, could navigate to task or open in editor
                      console.log('Opening note:', result.note_path);
                    }}
                  >
                    View Result
                  </Button>
                )}
              </Flex>
            </VStack>
          )}

          {!executing && !result && (
            <Box textAlign="center" py={8} color="gray.500">
              <Text fontSize="lg" fontWeight="bold" mb={2}>
                Execute an Instruction
              </Text>
              <Text fontSize="sm">
                Fill out the form on the left and click "Execute Task"
                to run a command. Results will appear here.
              </Text>
            </Box>
          )}
        </Box>
      </Flex>
    </Box>
  );
};

export default Executor;
