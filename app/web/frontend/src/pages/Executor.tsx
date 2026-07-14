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
  Checkbox,
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
import { useEffect, useRef, useState } from 'react';
import { executeInstruction, executeInstructionStream, fetchAgents } from '../api.ts';

/**
 * Interface for agent data
 */
interface Agent {
  name: string;
  capabilities?: string[];
}

/**
 * Per-candidate routing breakdown returned by the Hebbian router.
 */
interface RoutingCandidate {
  name: string;
  composite: number;
  hebbian_weight: number;
  hebbian_norm: number;
  trust_score: number;
  blended: number;
  pair_bonus: number;
  timing_score: number | null;
  hebbian_effective: number;
  oscillation_rate: number;
  sentinel_alert: boolean;
  sentinel_samples: number;
}

interface RoutingDecision {
  agent_name: string;
  alpha: number;
  beta: number;
  trust_floor: number;
  fallback_from: string | null;
  capability: string | null;
  routing_scope: string | null;
  atp_action_type: string | null;
  candidates: RoutingCandidate[];
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
  agent_name?: string | null;
  routing?: RoutingDecision | null;
  atp?: Record<string, unknown> | null;
  provenance_id?: string | null;
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
  const [streamingMode, setStreamingMode] = useState(false);
  // Live token buffer for the streaming path. Kept separate from `result`
  // so the user sees text accumulate as Exo emits chunks; on the
  // ``complete`` SSE event we fold the final text into `result.summary`.
  const [streamBuffer, setStreamBuffer] = useState('');
  const streamAbortRef = useRef<AbortController | null>(null);

  // Predefined capabilities
  const capabilities = [
    'llm_chat',
    'text_generation',
    'reasoning',
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

    const payload = {
      instruction,
      agent: selectedAgent || undefined,
      capability: capability || undefined,
      title: title || undefined,
    };

    setExecuting(true);
    setError(null);
    setResult(null);
    setStreamBuffer('');

    if (!streamingMode) {
      try {
        const response = await executeInstruction(payload);
        setResult(response);
        if (response.status === 'success') {
          setInstruction('');
          setSelectedAgent('');
          setCapability('');
          setTitle('');
        }
      } catch (err) {
        setError(
          `Execution failed: ${err instanceof Error ? err.message : 'Unknown error'}`
        );
        console.error(err);
      } finally {
        setExecuting(false);
      }
      return;
    }

    // Streaming mode: open SSE and accumulate tokens. The routing event
    // pre-populates `result` with the decision so the panel renders
    // immediately; tokens fill `streamBuffer`; the complete event
    // finalises `result.summary`.
    let accumulated = '';
    streamAbortRef.current = executeInstructionStream(payload, {
      onRouting: ({ decision, agent_name, task_id, atp, provenance_id }) => {
        setResult({
          task_id,
          status: 'in_progress',
          summary: '',
          agent_name,
          routing: (decision as RoutingDecision) || null,
          atp,
          provenance_id,
        });
      },
      onToken: (text) => {
        accumulated += text;
        setStreamBuffer(accumulated);
      },
      onComplete: (data) => {
        setResult((prev) => ({
          ...(prev || ({} as ExecutionResult)),
          task_id: data.task_id,
          status: data.status,
          summary: data.summary || accumulated,
          note_path: data.note_path || undefined,
          error: data.error || undefined,
          agent_name: data.agent_name,
          atp: data.atp,
          provenance_id: data.provenance_id,
        }));
        setExecuting(false);
        if (data.status === 'success') {
          setInstruction('');
          setSelectedAgent('');
          setCapability('');
          setTitle('');
        }
      },
      onError: (message) => {
        setError(`Stream failed: ${message}`);
        setExecuting(false);
      },
    });
  };

  const handleClear = () => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setInstruction('');
    setSelectedAgent('');
    setCapability('');
    setTitle('');
    setResult(null);
    setError(null);
    setStreamBuffer('');
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

            {/* Streaming toggle */}
            <FormControl>
              <Checkbox
                isChecked={streamingMode}
                onChange={(e) => setStreamingMode(e.target.checked)}
                isDisabled={executing}
                colorScheme="teal"
              >
                <Text as="span" fontWeight="bold">
                  Stream response
                </Text>
                <Text as="span" fontSize="xs" color="gray.500" ml={2}>
                  (renders tokens as they arrive from the LLM agent)
                </Text>
              </Checkbox>
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
              bg="rgba(34,211,238,0.08)"
              borderRadius="md"
              borderLeft="4px solid"
              borderColor="rgba(34,211,238,0.5)"
            >
              <Text fontSize="xs" color="#cbd5e1">
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
          {executing && !streamBuffer && (
            <Box textAlign="center" py={8}>
              <Spinner size="lg" color="blue.500" mb={4} />
              <Text fontSize="lg" fontWeight="bold">
                Executing...
              </Text>
              <Text fontSize="sm" color="gray.600" mt={2}>
                {streamingMode
                  ? 'Waiting for the first token...'
                  : 'Your instruction is being processed'}
              </Text>
            </Box>
          )}

          {/* Live token stream — visible while tokens are arriving but
              before the complete event finalises `result.summary`. */}
          {streamBuffer && executing && (
            <Box mb={4}>
              <Flex align="center" mb={2}>
                <Spinner size="xs" color="teal.500" mr={2} />
                <Text fontWeight="bold" fontSize="sm">
                  Streaming…
                  {result?.agent_name && (
                    <Badge ml={2} colorScheme="teal">{result.agent_name}</Badge>
                  )}
                </Text>
              </Flex>
              <Box
                p={3}
                bg="rgba(20,184,166,0.08)"
                borderRadius="md"
                fontSize="sm"
                borderLeft="4px solid"
                borderColor="rgba(20,184,166,0.5)"
                color="#5eead4"
                whiteSpace="pre-wrap"
                fontFamily="mono"
              >
                {streamBuffer}
              </Box>
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
                  {result.agent_name && (
                    <Stat>
                      <StatLabel fontSize="xs">Routed To</StatLabel>
                      <StatNumber fontSize="sm" wordBreak="break-all">
                        {result.agent_name}
                      </StatNumber>
                    </Stat>
                  )}
                  {result.note_path && (
                    <Stat>
                      <StatLabel fontSize="xs">Note Path</StatLabel>
                      <StatNumber fontSize="sm" wordBreak="break-all">
                        {result.note_path}
                      </StatNumber>
                    </Stat>
                  )}
                  {result.provenance_id && (
                    <Stat>
                      <StatLabel fontSize="xs">Provenance</StatLabel>
                      <StatNumber fontSize="xs" wordBreak="break-all">
                        {result.provenance_id}
                      </StatNumber>
                    </Stat>
                  )}
                </SimpleGrid>

                {/* Hebbian routing decision */}
                {result.routing && (
                  <Box mb={4}>
                    <Text fontWeight="bold" fontSize="sm" mb={2}>
                      Hebbian Routing Decision
                      <Badge ml={2} colorScheme="purple">
                        α = {result.routing.alpha.toFixed(2)}
                      </Badge>
                      <Badge ml={2} colorScheme="teal">
                        β = {result.routing.beta.toFixed(2)}
                      </Badge>
                      {result.routing.trust_floor > 0 && (
                        <Badge ml={2} colorScheme="red">
                          trust ≥ {result.routing.trust_floor.toFixed(2)}
                        </Badge>
                      )}
                      {result.routing.fallback_from && (
                        <Badge ml={2} colorScheme="orange">
                          fallback from: {result.routing.fallback_from}
                        </Badge>
                      )}
                      {result.routing.routing_scope && (
                        <Badge ml={2} colorScheme="blue">
                          {result.routing.routing_scope}
                        </Badge>
                      )}
                    </Text>
                    <Box
                      p={3}
                      bg="rgba(168,85,247,0.08)"
                      borderRadius="md"
                      fontSize="xs"
                      borderLeft="4px solid"
                      borderColor="rgba(168,85,247,0.5)"
                    >
                      {result.routing.candidates.map((c) => {
                        const isWinner = c.name === result.routing!.agent_name;
                        return (
                          <Flex
                            key={c.name}
                            justify="space-between"
                            py={1}
                            fontWeight={isWinner ? 'bold' : 'normal'}
                            color={isWinner ? '#d8b4fe' : '#cbd5e1'}
                          >
                            <Text color="inherit">
                              {isWinner ? '★ ' : '  '}
                              {c.name}
                            </Text>
                            <Text fontFamily="mono" color="inherit">
                              blended={c.blended.toFixed(3)} · composite=
                              {c.composite.toFixed(3)} · heb=
                              {c.hebbian_weight.toFixed(2)} · trust=
                              {c.trust_score.toFixed(2)}
                              {c.sentinel_alert && (
                                <Badge ml={2} colorScheme="orange">
                                  stability review ({c.oscillation_rate.toFixed(2)})
                                </Badge>
                              )}
                            </Text>
                          </Flex>
                        );
                      })}
                    </Box>
                  </Box>
                )}

                {/* Summary */}
                <Box mb={4}>
                  <Text fontWeight="bold" fontSize="sm" mb={2}>
                    Summary
                  </Text>
                  <Box
                    p={3}
                    bg="rgba(255,255,255,0.04)"
                    borderRadius="md"
                    fontSize="sm"
                    borderLeft="4px solid"
                    borderColor={
                      result.status === 'success'
                        ? 'rgba(34,197,94,0.6)'
                        : 'rgba(239,68,68,0.6)'
                    }
                    whiteSpace="pre-wrap"
                  >
                    <Text color="#e2e8f0">{result.summary}</Text>
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
