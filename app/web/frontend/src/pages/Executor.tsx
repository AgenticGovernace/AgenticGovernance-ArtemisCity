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
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  executeInstruction,
  executeInstructionStream,
  fetchAgents,
  fetchRoutingConfig,
  getUserFacingErrorMessage,
  isAbortError,
  type AgentSummary,
  type RoutingConfig,
} from '../api.ts';
import RoutingPathBadge, {
  isLegacyRoutingPath,
} from '../components/RoutingPathBadge';
import { useRequestController } from '../hooks/useRequestController';
import { routePaths } from '../router/paths';
import { Link as RouterLink } from 'react-router-dom';

/**
 * Interface for agent data
 */
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
  /** Which routing implementation produced this decision. */
  routing_path?: string | null;
  candidates: RoutingCandidate[];
}

/**
 * Interface for execution response
 */
interface ExecutionResult {
  task_id: string;
  status: string;
  summary: string;
  note_path?: string | null;
  error?: string | null;
  agent_name?: string | null;
  routing?: RoutingDecision | null;
  routing_path?: string | null;
  atp?: Record<string, unknown> | null;
  provenance_id?: string | null;
  provider?: string | null;
  fallback_used?: boolean | null;
  model?: string | null;
  outcome_class?: string | null;
  learning_eligible?: boolean | null;
  exo_request?: Record<string, unknown> | null;
  compressed_context?: string | null;
  output_compression?: Record<string, unknown> | null;
}

/**
 * Executor Page Component
 *
 * Renders a form for executing CLI-style instructions through the
 * MCP executor with support for agent and capability selection.
 */
const Executor = () => {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [instruction, setInstruction] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [capability, setCapability] = useState('');
  const [title, setTitle] = useState('');
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [streamingMode, setStreamingMode] = useState(false);
  const [atpStrict, setAtpStrict] = useState(false);
  const [routingConfig, setRoutingConfig] = useState<RoutingConfig | null>(null);
  // Live token buffer for the streaming path. Kept separate from `result`
  // so the user sees text accumulate as Exo emits chunks; on the
  // ``complete`` SSE event we fold the final text into `result.summary`.
  const [streamBuffer, setStreamBuffer] = useState('');
  const streamAbortRef = useRef<AbortController | null>(null);
  const createAgentController = useRequestController();
  const createExecutionController = useRequestController();

  // Capabilities the deployment can actually route. The backend reports the
  // set advertised by loaded agents, each labelled by whether the Routing
  // Kernel's reviewed ATP domain authorizes it. This static list is only the
  // fallback for when /api/routing/config is unavailable — offering a
  // capability no agent advertises would produce an unroutable task.
  const FALLBACK_CAPABILITIES = [
    'llm_chat',
    'text_generation',
    'reasoning',
    'web_search',
    'text_summarization',
    'system_management',
    'agent_coordination',
    'document_analysis',
  ];

  const reviewedCapabilities =
    routingConfig?.capabilities.filter((c) => c.kernel_reviewed) ?? [];
  const legacyCapabilities =
    routingConfig?.capabilities.filter((c) => !c.kernel_reviewed) ?? [];
  const selectedCapabilityInfo = routingConfig?.capabilities.find(
    (c) => c.name === capability
  );

  // Load agents on mount
  const loadAgents = useCallback(async () => {
    const controller = createAgentController();
    setLoadingAgents(true);
    try {
      const data = await fetchAgents({ signal: controller.signal });
      setAgents(data);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err, 'Failed to load agents.'));
    } finally {
      if (!controller.signal.aborted) setLoadingAgents(false);
    }
  }, [createAgentController]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  // Routing config is a label, not a dependency: a failure here degrades the
  // capability picker to its static list rather than blocking execution.
  useEffect(() => {
    const controller = new AbortController();
    fetchRoutingConfig({ signal: controller.signal })
      .then((config) => {
        if (!controller.signal.aborted) setRoutingConfig(config);
      })
      .catch(() => {
        /* keep the static capability list */
      });
    return () => controller.abort();
  }, []);

  useEffect(
    () => () => {
      streamAbortRef.current?.abort();
    },
    []
  );

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
      atp_strict: atpStrict || undefined,
    };

    setExecuting(true);
    setError(null);
    setResult(null);
    setStreamBuffer('');

    if (!streamingMode) {
      const controller = createExecutionController();
      try {
        const response = await executeInstruction(payload, { signal: controller.signal });
        setResult(response as unknown as ExecutionResult);
        if (response.status === 'success') {
          setInstruction('');
          setSelectedAgent('');
          setCapability('');
          setTitle('');
        }
      } catch (err: unknown) {
        if (isAbortError(err)) return;
        setError(
          getUserFacingErrorMessage(err, 'Execution failed. Try again.')
        );
      } finally {
        if (!controller.signal.aborted) setExecuting(false);
      }
      return;
    }

    // Streaming mode: open SSE and accumulate tokens. The routing event
    // pre-populates `result` with the decision so the panel renders
    // immediately; tokens fill `streamBuffer`; the complete event
    // finalises `result.summary`.
    let accumulated = '';
    streamAbortRef.current = executeInstructionStream(payload, {
      onRouting: ({
        decision,
        agent_name,
        task_id,
        atp,
        provenance_id,
        routing_path,
      }) => {
        setResult({
          task_id,
          status: 'in_progress',
          summary: '',
          agent_name,
          routing: (decision as RoutingDecision) || null,
          routing_path,
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
          routing_path: data.routing_path ?? prev?.routing_path ?? null,
          atp: data.atp,
          provenance_id: data.provenance_id,
          provider: data.provider,
          fallback_used: data.fallback_used,
          model: data.model,
          outcome_class: data.outcome_class,
          learning_eligible: data.learning_eligible,
          exo_request: data.exo_request,
          compressed_context: data.compressed_context,
          output_compression: data.output_compression,
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
        setError(message);
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
                {routingConfig ? (
                  <>
                    {reviewedCapabilities.length > 0 && (
                      <optgroup label="Kernel-reviewed">
                        {reviewedCapabilities.map((cap) => (
                          <option key={cap.name} value={cap.name}>
                            {cap.name}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {legacyCapabilities.length > 0 && (
                      <optgroup label="Legacy compatibility path">
                        {legacyCapabilities.map((cap) => (
                          <option key={cap.name} value={cap.name}>
                            {cap.name}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </>
                ) : (
                  FALLBACK_CAPABILITIES.map((cap) => (
                    <option key={cap} value={cap}>
                      {cap}
                    </option>
                  ))
                )}
              </Select>
              <Text fontSize="xs" color="gray.500" mt={1}>
                {routingConfig
                  ? 'Only capabilities a loaded agent advertises are listed. Kernel-reviewed capabilities route through full authorization.'
                  : 'Capability determines which agent capabilities are used.'}
              </Text>
              {selectedCapabilityInfo && !selectedCapabilityInfo.kernel_reviewed && (
                <Alert status="warning" borderRadius="md" mt={2} fontSize="xs">
                  <AlertIcon />
                  <Box>
                    <AlertTitle fontSize="xs">
                      Outside the reviewed ATP domain
                    </AlertTitle>
                    <AlertDescription fontSize="xs">
                      {selectedCapabilityInfo.name} is served by the legacy
                      compatibility path, which skips Routing Kernel
                      authorization.
                    </AlertDescription>
                  </Box>
                </Alert>
              )}
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

            {/* ATP strict toggle — per-request override of ARTEMIS_ATP_STRICT */}
            <FormControl>
              <Checkbox
                isChecked={atpStrict}
                onChange={(e) => setAtpStrict(e.target.checked)}
                isDisabled={executing}
                colorScheme="orange"
              >
                <Text as="span" fontWeight="bold">
                  Strict ATP validation
                </Text>
                <Text as="span" fontSize="xs" color="gray.500" ml={2}>
                  (reject header validation errors instead of attaching them)
                </Text>
              </Checkbox>
              {routingConfig?.atp_strict && !atpStrict && (
                <Text fontSize="xs" color="orange.300" mt={1}>
                  This deployment already runs strict (ARTEMIS_ATP_STRICT=1).
                </Text>
              )}
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
                  {result.routing_path && (
                    <Stat>
                      <StatLabel fontSize="xs">Routing Path</StatLabel>
                      <StatNumber fontSize="sm">
                        <RoutingPathBadge path={result.routing_path} />
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
                  {result.provider && (
                    <Stat>
                      <StatLabel fontSize="xs">Provider</StatLabel>
                      <StatNumber fontSize="sm" wordBreak="break-all">
                        {result.provider}
                      </StatNumber>
                    </Stat>
                  )}
                  {result.fallback_used != null && (
                    <Stat>
                      <StatLabel fontSize="xs">Local fallback</StatLabel>
                      <StatNumber fontSize="sm">
                        {result.fallback_used ? 'Used' : 'Not used'}
                      </StatNumber>
                    </Stat>
                  )}
                  {result.model && (
                    <Stat>
                      <StatLabel fontSize="xs">Model</StatLabel>
                      <StatNumber fontSize="xs" wordBreak="break-all">
                        {result.model}
                      </StatNumber>
                    </Stat>
                  )}
                  {result.outcome_class && (
                    <Stat>
                      <StatLabel fontSize="xs">Outcome</StatLabel>
                      <StatNumber fontSize="xs" wordBreak="break-all">
                        {result.outcome_class}
                      </StatNumber>
                    </Stat>
                  )}
                  {result.learning_eligible != null && (
                    <Stat>
                      <StatLabel fontSize="xs">Learning</StatLabel>
                      <StatNumber fontSize="xs">
                        {result.learning_eligible ? 'Recorded' : 'Skipped'}
                      </StatNumber>
                    </Stat>
                  )}
                </SimpleGrid>

                {result.exo_request && (
                  <Box
                    mb={4}
                    p={3}
                    bg="rgba(20,184,166,0.08)"
                    borderRadius="md"
                    borderLeft="4px solid"
                    borderColor="rgba(20,184,166,0.5)"
                  >
                    <Text fontWeight="bold" fontSize="sm" mb={1}>
                      Verified Exo Request
                    </Text>
                    <Text fontSize="xs" fontFamily="mono" whiteSpace="pre-wrap">
                      {JSON.stringify(result.exo_request, null, 2)}
                    </Text>
                  </Box>
                )}

                {result.output_compression && (
                  <Box
                    mb={4}
                    p={3}
                    bg="rgba(168,85,247,0.08)"
                    borderRadius="md"
                    borderLeft="4px solid"
                    borderColor="rgba(168,85,247,0.5)"
                  >
                    <Text fontWeight="bold" fontSize="sm" mb={1}>
                      Hebbian-routed Context Compression
                    </Text>
                    <Text fontSize="xs" fontFamily="mono" whiteSpace="pre-wrap">
                      {JSON.stringify(result.output_compression, null, 2)}
                    </Text>
                  </Box>
                )}

                {/* Routing decision. The kernel runs intent → authorization →
                    eligibility before this ranking, so a strong Hebbian weight
                    cannot rescue a quarantined or below-floor agent. */}
                {result.routing && (
                  <Box mb={4}>
                    <Text fontWeight="bold" fontSize="sm" mb={2}>
                      Routing Decision
                      <RoutingPathBadge
                        path={result.routing.routing_path ?? result.routing_path}
                        ml={2}
                      />
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
                    <Text fontSize="xs" color="gray.500" mb={2}>
                      {isLegacyRoutingPath(
                        result.routing.routing_path ?? result.routing_path
                      )
                        ? 'Served without Routing Kernel authorization — governance and trust eligibility did not gate this ranking.'
                        : 'Ranked after intent resolution, authorization, and governance/trust eligibility.'}
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
                {result.task_id && (
                  <Button
                    as={RouterLink}
                    size="sm"
                    colorScheme="blue"
                    flex={1}
                    to={routePaths.taskActivity(result.task_id)}
                  >
                    View activity &amp; result
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
