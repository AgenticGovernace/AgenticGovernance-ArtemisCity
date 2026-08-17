/**
 * Agents page.
 *
 * Joins the two agent views the backend exposes:
 *
 *  - `/api/agents` — agents currently loaded in the orchestrator's in-memory
 *    registry. This is the authoritative "can actually run a task" list; rows
 *    persisted by past test runs whose Python classes no longer exist are
 *    deliberately excluded.
 *  - `/api/db/agents` — the persisted registry row, carrying the governance
 *    columns (trust tier, status, violations, learning state).
 *  - `/api/db/trust` — the decay-adjusted trust score from the trust engine.
 *
 * An agent present only in the persisted registry is shown as unloaded rather
 * than hidden, because "the database remembers it but the orchestrator cannot
 * dispatch to it" is exactly the state an operator needs to see.
 *
 * @module Agents
 */

import {
  Badge,
  Box,
  Button,
  Flex,
  Heading,
  HStack,
  Input,
  SimpleGrid,
  Stat,
  StatLabel,
  StatNumber,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  VStack,
} from '@chakra-ui/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchAgentScores,
  fetchAgents,
  fetchTrustScores,
  getUserFacingErrorMessage,
  isAbortError,
  type AgentScore,
  type AgentSummary,
  type TrustScoreRecord,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { themeTokens } from '../theme';

const { fg } = themeTokens;

const TRUST_TIER_COLORS: Record<string, string> = {
  full: 'green',
  trusted: 'green',
  monitored: 'blue',
  restricted: 'orange',
  untrusted: 'red',
};

const STATUS_COLORS: Record<string, string> = {
  active: 'green',
  quarantined: 'red',
  suspended: 'red',
  inactive: 'gray',
};

/** One row of the merged agent view. */
interface AgentRow {
  name: string;
  capabilities: string[];
  loaded: boolean;
  trustTier: string | null;
  status: string | null;
  violationCount: number;
  compositeScore: number | null;
  trustScore: number | null;
  executionCount: number;
  successfulExecutions: number;
  sentinelAlert: boolean;
}

const mergeAgents = (
  loaded: AgentSummary[],
  persisted: AgentScore[],
  trust: TrustScoreRecord[]
): AgentRow[] => {
  const persistedByName = new Map(persisted.map((row) => [row.name, row]));
  const trustByName = new Map(
    trust
      .filter((row) => row.entity_type === 'agent')
      .map((row) => [row.entity_id, row.score])
  );
  const names = new Set<string>([
    ...loaded.map((agent) => agent.name),
    ...persisted.map((agent) => agent.name),
  ]);

  return Array.from(names)
    .sort((a, b) => a.localeCompare(b))
    .map((name) => {
      const live = loaded.find((agent) => agent.name === name);
      const row = persistedByName.get(name);
      return {
        name,
        capabilities: live?.capabilities ?? row?.capabilities ?? [],
        loaded: Boolean(live),
        trustTier: row?.trust_tier ?? null,
        status: row?.status ?? null,
        violationCount: row?.violation_count ?? 0,
        compositeScore: row?.composite_score ?? null,
        // Prefer the trust engine's decay-adjusted value; the registry mirror
        // can lag it between synchronizations.
        trustScore: trustByName.get(name) ?? row?.trust_score ?? null,
        executionCount: row?.execution_count ?? 0,
        successfulExecutions: row?.successful_executions ?? 0,
        sentinelAlert: Boolean(row?.hebbian_sentinel_alert),
      };
    });
};

const Agents = () => {
  const [rows, setRows] = useState<AgentRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const createController = useRequestController();

  const load = useCallback(async () => {
    const controller = createController();
    setLoading(true);
    setError(null);
    try {
      // The loaded-agent list is required; the governance projections are
      // best-effort so a missing registry or trust store degrades the extra
      // columns rather than the page.
      const loaded = await fetchAgents({ signal: controller.signal });
      const [persisted, trust] = await Promise.all([
        fetchAgentScores({ signal: controller.signal }).catch(
          () => [] as AgentScore[]
        ),
        fetchTrustScores('agent', 500, { signal: controller.signal }).catch(
          () => [] as TrustScoreRecord[]
        ),
      ]);
      if (!controller.signal.aborted) {
        setRows(mergeAgents(loaded, persisted, trust));
      }
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err, 'Failed to fetch agents.'));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [createController]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return rows ?? [];
    return (rows ?? []).filter(
      (row) =>
        row.name.toLowerCase().includes(term) ||
        row.capabilities.some((cap) => cap.toLowerCase().includes(term))
    );
  }, [rows, search]);

  if (loading) return <RouteStatus status="loading" message="Loading agents…" />;

  if (error) {
    return <RouteStatus status="error" message={error} onRetry={() => void load()} />;
  }

  const all = rows ?? [];
  const loadedCount = all.filter((row) => row.loaded).length;
  const quarantined = all.filter(
    (row) => row.status === 'quarantined' || row.status === 'suspended'
  ).length;
  const withViolations = all.filter((row) => row.violationCount > 0).length;

  return (
    <Box>
      <Heading as="h2" size="xl" mb={2}>
        Agents
      </Heading>
      <Text fontSize="sm" color={fg['2']} mb={6}>
        Loaded agents joined with their persisted governance state. Only loaded
        agents can be dispatched to.
      </Text>

      <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4} mb={6}>
        <Stat>
          <StatLabel>Loaded</StatLabel>
          <StatNumber>{loadedCount}</StatNumber>
        </Stat>
        <Stat>
          <StatLabel>Known to registry</StatLabel>
          <StatNumber>{all.length}</StatNumber>
        </Stat>
        <Stat>
          <StatLabel>Quarantined</StatLabel>
          <StatNumber color={quarantined > 0 ? 'red.300' : undefined}>
            {quarantined}
          </StatNumber>
        </Stat>
        <Stat>
          <StatLabel>With violations</StatLabel>
          <StatNumber color={withViolations > 0 ? 'orange.300' : undefined}>
            {withViolations}
          </StatNumber>
        </Stat>
      </SimpleGrid>

      <HStack spacing={4} mb={4}>
        <Input
          placeholder="Search by name or capability…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          size="sm"
          maxW="360px"
        />
        <Button size="sm" onClick={() => void load()}>
          Refresh
        </Button>
      </HStack>

      {filtered.length === 0 ? (
        <RouteStatus status="empty" message="No agents found." compact />
      ) : (
        <Table size="sm" variant="simple">
          <Thead>
            <Tr>
              <Th>Agent</Th>
              <Th>Capabilities</Th>
              <Th>Tier</Th>
              <Th>Status</Th>
              <Th isNumeric>Trust</Th>
              <Th isNumeric>Composite</Th>
              <Th isNumeric>Executions</Th>
              <Th isNumeric>Violations</Th>
            </Tr>
          </Thead>
          <Tbody>
            {filtered.map((row) => (
              <Tr key={row.name} opacity={row.loaded ? 1 : 0.6}>
                <Td fontWeight="bold">
                  <VStack align="start" spacing={1}>
                    <Text>{row.name}</Text>
                    {!row.loaded && (
                      <Tooltip
                        hasArrow
                        placement="top"
                        label="Present in the persisted registry but not loaded in the orchestrator. Tasks cannot be dispatched to it."
                      >
                        <Badge colorScheme="gray" cursor="help">
                          not loaded
                        </Badge>
                      </Tooltip>
                    )}
                    {row.sentinelAlert && (
                      <Tooltip
                        hasArrow
                        placement="top"
                        label="The Hebbian Sentinel flagged unstable learning for this agent. Diagnostic only — it does not affect routing."
                      >
                        <Badge colorScheme="orange" cursor="help">
                          stability review
                        </Badge>
                      </Tooltip>
                    )}
                  </VStack>
                </Td>
                <Td>
                  <Flex gap={1} wrap="wrap">
                    {row.capabilities.length === 0 ? (
                      <Text fontSize="xs" color={fg['3']}>
                        —
                      </Text>
                    ) : (
                      row.capabilities.map((cap) => (
                        <Badge key={cap} colorScheme="blue" fontSize="xs">
                          {cap}
                        </Badge>
                      ))
                    )}
                  </Flex>
                </Td>
                <Td>
                  {row.trustTier ? (
                    <Badge colorScheme={TRUST_TIER_COLORS[row.trustTier] ?? 'gray'}>
                      {row.trustTier}
                    </Badge>
                  ) : (
                    '—'
                  )}
                </Td>
                <Td>
                  {row.status ? (
                    <Badge colorScheme={STATUS_COLORS[row.status] ?? 'gray'}>
                      {row.status}
                    </Badge>
                  ) : (
                    '—'
                  )}
                </Td>
                <Td isNumeric fontFamily="mono">
                  {row.trustScore !== null ? row.trustScore.toFixed(3) : '—'}
                </Td>
                <Td isNumeric fontFamily="mono">
                  {row.compositeScore !== null
                    ? row.compositeScore.toFixed(3)
                    : '—'}
                </Td>
                <Td isNumeric>
                  {row.executionCount > 0
                    ? `${row.successfulExecutions}/${row.executionCount}`
                    : '—'}
                </Td>
                <Td isNumeric color={row.violationCount > 0 ? 'orange.300' : undefined}>
                  {row.violationCount}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </Box>
  );
};

export default Agents;
