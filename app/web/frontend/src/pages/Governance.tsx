/**
 * Governance page.
 *
 * Read-only operator view over the governance subsystems that previously had
 * no dashboard surface at all: the trust engine, the violation/quarantine
 * ledger, the observational Hebbian Sentinel, the delegation grant ledger, and
 * the live routing configuration.
 *
 * Everything here is a projection. The dashboard never mutates trust,
 * violations, quarantine, or delegation state — those remain owned by the
 * Python core and the authenticated Express boundary, so this page cannot
 * become a second write path.
 *
 * @module Governance
 */

import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Flex,
  Heading,
  HStack,
  SimpleGrid,
  Spinner,
  Stat,
  StatLabel,
  StatNumber,
  Tab,
  Table,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  VStack,
} from '@chakra-ui/react';
import { useCallback, useEffect, useState } from 'react';
import {
  fetchBudgetReservations,
  fetchDelegationGrants,
  fetchRoutingConfig,
  fetchSentinelAlerts,
  fetchSentinelSignals,
  fetchTrustScores,
  fetchViolations,
  getUserFacingErrorMessage,
  isAbortError,
  type BudgetReservation,
  type DelegationGrant,
  type RoutingConfig,
  type SentinelAlert,
  type SentinelSignal,
  type TrustScoreRecord,
  type ViolationRecord,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { themeTokens } from '../theme';

const { fg } = themeTokens;

/** Trust levels the governance engine assigns, mapped to badge colors. */
const TRUST_LEVEL_COLORS: Record<string, string> = {
  full: 'green',
  high: 'teal',
  medium: 'blue',
  low: 'orange',
  untrusted: 'red',
};

const formatTimestamp = (value: string | null | undefined): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
};

/**
 * Shared loader for every tab on this page.
 *
 * Each tab owns exactly one request, so a store that is missing on a given
 * deployment (for example an empty delegation ledger) degrades that tab alone
 * instead of blanking the page.
 */
const useGovernanceResource = <T,>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: unknown[]
) => {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const createController = useRequestController();

  const refresh = useCallback(async () => {
    const controller = createController();
    setLoading(true);
    setError(null);
    try {
      const result = await load(controller.signal);
      if (!controller.signal.aborted) setData(result);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
    // `load` is recreated per render by design; the caller's deps decide when
    // a refetch is warranted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createController, ...deps]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
};

const TabFrame = ({
  loading,
  error,
  onRetry,
  children,
}: {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  children: React.ReactNode;
}) => {
  if (loading) {
    return (
      <Box textAlign="center" mt={4}>
        <Spinner size="lg" />
        <Text mt={2}>Loading…</Text>
      </Box>
    );
  }
  if (error) {
    return <RouteStatus status="error" message={error} onRetry={onRetry} compact />;
  }
  return <>{children}</>;
};

/* -------------------------------------------------------------------------- */
/* Trust                                                                      */
/* -------------------------------------------------------------------------- */

const TrustTab = () => {
  const { data, loading, error, refresh } = useGovernanceResource<TrustScoreRecord[]>(
    (signal) => fetchTrustScores(undefined, 200, { signal }),
    []
  );
  const scores = data ?? [];

  const average =
    scores.length > 0
      ? scores.reduce((total, row) => total + row.score, 0) / scores.length
      : 0;
  const belowHalf = scores.filter((row) => row.score < 0.5).length;

  return (
    <TabFrame loading={loading} error={error} onRetry={refresh}>
      <VStack spacing={5} align="stretch">
        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          <Stat>
            <StatLabel>Scored entities</StatLabel>
            <StatNumber>{scores.length}</StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Average trust</StatLabel>
            <StatNumber>{average.toFixed(3)}</StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Below 0.50</StatLabel>
            <StatNumber>{belowHalf}</StatNumber>
          </Stat>
        </SimpleGrid>

        <Flex>
          <Button size="sm" onClick={refresh}>
            Refresh
          </Button>
        </Flex>

        {scores.length === 0 ? (
          <RouteStatus status="empty" message="No trust scores recorded yet." compact />
        ) : (
          <Table size="sm" variant="simple">
            <Thead>
              <Tr>
                <Th>Entity</Th>
                <Th>Type</Th>
                <Th isNumeric>Score</Th>
                <Th>Level</Th>
                <Th isNumeric>Reinforcements</Th>
                <Th isNumeric>Penalties</Th>
                <Th isNumeric>Decay</Th>
                <Th>Updated</Th>
              </Tr>
            </Thead>
            <Tbody>
              {scores.map((row) => (
                <Tr key={`${row.entity_type}:${row.entity_id}`}>
                  <Td fontWeight="bold">{row.entity_id}</Td>
                  <Td>{row.entity_type}</Td>
                  <Td isNumeric fontFamily="mono">
                    {row.score.toFixed(3)}
                  </Td>
                  <Td>
                    <Badge colorScheme={TRUST_LEVEL_COLORS[row.level] ?? 'gray'}>
                      {row.level}
                    </Badge>
                  </Td>
                  <Td isNumeric>{row.reinforcement_events}</Td>
                  <Td isNumeric>{row.penalty_events}</Td>
                  <Td isNumeric fontFamily="mono">
                    {row.decay_rate.toFixed(3)}
                  </Td>
                  <Td fontSize="xs">{formatTimestamp(row.last_updated)}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </VStack>
    </TabFrame>
  );
};

/* -------------------------------------------------------------------------- */
/* Violations                                                                 */
/* -------------------------------------------------------------------------- */

const ViolationsTab = () => {
  const [openOnly, setOpenOnly] = useState(true);
  const { data, loading, error, refresh } = useGovernanceResource<ViolationRecord[]>(
    (signal) => fetchViolations(openOnly, 200, { signal }),
    [openOnly]
  );
  const violations = data ?? [];

  return (
    <TabFrame loading={loading} error={error} onRetry={refresh}>
      <VStack spacing={5} align="stretch">
        <Text fontSize="sm" color={fg['2']}>
          Sandbox enforcement quarantines an agent on its third uncleared
          violation. Clearing a violation is a governance action and is not
          available from this read-only view.
        </Text>

        <HStack spacing={4}>
          <Checkbox
            isChecked={openOnly}
            onChange={(event) => setOpenOnly(event.target.checked)}
            colorScheme="orange"
          >
            Uncleared only
          </Checkbox>
          <Button size="sm" onClick={refresh}>
            Refresh
          </Button>
        </HStack>

        {violations.length === 0 ? (
          <RouteStatus
            status="empty"
            message={
              openOnly
                ? 'No uncleared violations recorded.'
                : 'No violations recorded.'
            }
            compact
          />
        ) : (
          <Table size="sm" variant="simple">
            <Thead>
              <Tr>
                <Th>Agent</Th>
                <Th>Type</Th>
                <Th>Action taken</Th>
                <Th>State</Th>
                <Th>Recorded</Th>
                <Th>Details</Th>
              </Tr>
            </Thead>
            <Tbody>
              {violations.map((row) => (
                <Tr key={row.violation_id}>
                  <Td fontWeight="bold">{row.agent_name}</Td>
                  <Td>{row.violation_type}</Td>
                  <Td>{row.action_taken}</Td>
                  <Td>
                    <Badge colorScheme={row.cleared ? 'gray' : 'red'}>
                      {row.cleared ? 'cleared' : 'open'}
                    </Badge>
                  </Td>
                  <Td fontSize="xs">{formatTimestamp(row.timestamp)}</Td>
                  <Td fontSize="xs" maxW="360px" whiteSpace="pre-wrap">
                    {row.details}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </VStack>
    </TabFrame>
  );
};

/* -------------------------------------------------------------------------- */
/* Hebbian Sentinel                                                           */
/* -------------------------------------------------------------------------- */

const SentinelTab = () => {
  const [openOnly, setOpenOnly] = useState(false);
  const { data, loading, error, refresh } = useGovernanceResource<{
    signals: SentinelSignal[];
    alerts: SentinelAlert[];
  }>(
    async (signal) => {
      const [signals, alerts] = await Promise.all([
        fetchSentinelSignals(200, { signal }),
        fetchSentinelAlerts(openOnly, 200, { signal }),
      ]);
      return { signals: signals.signals, alerts: alerts.alerts };
    },
    [openOnly]
  );

  const signals = data?.signals ?? [];
  const alerts = data?.alerts ?? [];
  const active = signals.filter((row) => row.alert_active).length;

  return (
    <TabFrame loading={loading} error={error} onRetry={refresh}>
      <VStack spacing={5} align="stretch">
        <Alert status="info" fontSize="sm">
          <AlertIcon />
          Sentinel signals are diagnostic only. They never change routing rank,
          Hebbian weights, trust, or quarantine state on their own — a high
          oscillation rate is a prompt for review, not an enforcement action.
        </Alert>

        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          <Stat>
            <StatLabel>Tracked pairs</StatLabel>
            <StatNumber>{signals.length}</StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Active alerts</StatLabel>
            <StatNumber color={active > 0 ? 'orange.300' : undefined}>
              {active}
            </StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Alert transitions</StatLabel>
            <StatNumber>{alerts.length}</StatNumber>
          </Stat>
        </SimpleGrid>

        <Box>
          <Heading as="h3" size="sm" mb={3}>
            Stability signals
          </Heading>
          {signals.length === 0 ? (
            <RouteStatus
              status="empty"
              message="No stability signals recorded yet. Signals appear once learning outcomes accumulate."
              compact
            />
          ) : (
            <Table size="sm" variant="simple">
              <Thead>
                <Tr>
                  <Th>Agent</Th>
                  <Th>Task type</Th>
                  <Th isNumeric>Samples</Th>
                  <Th isNumeric>Sign changes</Th>
                  <Th isNumeric>Oscillation</Th>
                  <Th isNumeric>Threshold</Th>
                  <Th isNumeric>Window</Th>
                  <Th>State</Th>
                  <Th>Updated</Th>
                </Tr>
              </Thead>
              <Tbody>
                {signals.map((row) => (
                  <Tr key={`${row.agent_name}:${row.task_type}`}>
                    <Td fontWeight="bold">{row.agent_name}</Td>
                    <Td>{row.task_type}</Td>
                    <Td isNumeric>{row.sample_count}</Td>
                    <Td isNumeric>{row.sign_changes}</Td>
                    <Td isNumeric fontFamily="mono">
                      {row.oscillation_rate.toFixed(3)}
                    </Td>
                    <Td isNumeric fontFamily="mono">
                      {row.threshold.toFixed(2)}
                    </Td>
                    <Td isNumeric>{row.window_size}</Td>
                    <Td>
                      <Badge colorScheme={row.alert_active ? 'orange' : 'green'}>
                        {row.alert_active ? 'review' : 'stable'}
                      </Badge>
                    </Td>
                    <Td fontSize="xs">{formatTimestamp(row.updated_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Box>

        <Box>
          <Flex align="center" justify="space-between" mb={3} gap={4} flexWrap="wrap">
            <Heading as="h3" size="sm">
              Alert transitions
            </Heading>
            <HStack spacing={4}>
              <Checkbox
                isChecked={openOnly}
                onChange={(event) => setOpenOnly(event.target.checked)}
                colorScheme="orange"
              >
                Open only
              </Checkbox>
              <Button size="sm" onClick={refresh}>
                Refresh
              </Button>
            </HStack>
          </Flex>
          {alerts.length === 0 ? (
            <RouteStatus
              status="empty"
              message={
                openOnly ? 'No open alerts.' : 'No alert transitions recorded.'
              }
              compact
            />
          ) : (
            <Table size="sm" variant="simple">
              <Thead>
                <Tr>
                  <Th>Agent</Th>
                  <Th>Task type</Th>
                  <Th isNumeric>Oscillation</Th>
                  <Th isNumeric>Samples</Th>
                  <Th>Status</Th>
                  <Th>Raised</Th>
                  <Th>Resolved</Th>
                </Tr>
              </Thead>
              <Tbody>
                {alerts.map((row) => (
                  <Tr key={row.id}>
                    <Td fontWeight="bold">{row.agent_name}</Td>
                    <Td>{row.task_type}</Td>
                    <Td isNumeric fontFamily="mono">
                      {row.oscillation_rate.toFixed(3)}
                    </Td>
                    <Td isNumeric>{row.sample_count}</Td>
                    <Td>
                      <Badge colorScheme={row.status === 'open' ? 'orange' : 'gray'}>
                        {row.status}
                      </Badge>
                    </Td>
                    <Td fontSize="xs">{formatTimestamp(row.created_at)}</Td>
                    <Td fontSize="xs">{formatTimestamp(row.resolved_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Box>
      </VStack>
    </TabFrame>
  );
};

/* -------------------------------------------------------------------------- */
/* Delegation                                                                 */
/* -------------------------------------------------------------------------- */

const DelegationTab = () => {
  const { data, loading, error, refresh } = useGovernanceResource<{
    grants: DelegationGrant[];
    reservations: BudgetReservation[];
  }>(
    async (signal) => {
      const [grants, reservations] = await Promise.all([
        fetchDelegationGrants(100, { signal }),
        fetchBudgetReservations(100, { signal }),
      ]);
      return { grants, reservations };
    },
    []
  );

  const grants = data?.grants ?? [];
  const reservations = data?.reservations ?? [];
  const now = Date.now();

  return (
    <TabFrame loading={loading} error={error} onRetry={refresh}>
      <VStack spacing={5} align="stretch">
        <Text fontSize="sm" color={fg['2']}>
          Delegation grants authorize a child route on behalf of a parent task,
          backed by a budget reservation. Grants re-validate their canonical
          SHA-256 on read, so a tampered row cannot load — the signed payload
          itself is deliberately not exposed to the dashboard.
        </Text>

        <Flex>
          <Button size="sm" onClick={refresh}>
            Refresh
          </Button>
        </Flex>

        <Box>
          <Heading as="h3" size="sm" mb={3}>
            Grants
          </Heading>
          {grants.length === 0 ? (
            <RouteStatus status="empty" message="No delegation grants issued." compact />
          ) : (
            <Table size="sm" variant="simple">
              <Thead>
                <Tr>
                  <Th>Grant</Th>
                  <Th>Root task</Th>
                  <Th>Parent task</Th>
                  <Th>Reservation</Th>
                  <Th>Expires</Th>
                  <Th>Created</Th>
                </Tr>
              </Thead>
              <Tbody>
                {grants.map((row) => {
                  const expiry = new Date(row.expires_at).getTime();
                  const expired = !Number.isNaN(expiry) && expiry < now;
                  return (
                    <Tr key={row.grant_id}>
                      <Td fontFamily="mono" fontSize="xs" wordBreak="break-all">
                        {row.grant_id}
                      </Td>
                      <Td fontSize="xs">{row.root_task_id}</Td>
                      <Td fontSize="xs">{row.parent_task_id}</Td>
                      <Td fontFamily="mono" fontSize="xs" wordBreak="break-all">
                        {row.budget_reservation_id}
                      </Td>
                      <Td fontSize="xs">
                        {formatTimestamp(row.expires_at)}
                        {expired && (
                          <Badge ml={2} colorScheme="gray">
                            expired
                          </Badge>
                        )}
                      </Td>
                      <Td fontSize="xs">{formatTimestamp(row.created_at)}</Td>
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>
          )}
        </Box>

        <Box>
          <Heading as="h3" size="sm" mb={3}>
            Budget reservations
          </Heading>
          {reservations.length === 0 ? (
            <RouteStatus status="empty" message="No budget reservations held." compact />
          ) : (
            <Table size="sm" variant="simple">
              <Thead>
                <Tr>
                  <Th>Reservation</Th>
                  <Th>State</Th>
                  <Th isNumeric>Remaining units</Th>
                  <Th>Expires</Th>
                  <Th>Updated</Th>
                </Tr>
              </Thead>
              <Tbody>
                {reservations.map((row) => (
                  <Tr key={row.reservation_id}>
                    <Td fontFamily="mono" fontSize="xs" wordBreak="break-all">
                      {row.reservation_id}
                    </Td>
                    <Td>
                      <Badge
                        colorScheme={row.state === 'active' ? 'green' : 'gray'}
                      >
                        {row.state}
                      </Badge>
                    </Td>
                    <Td isNumeric>{row.remaining_units ?? '—'}</Td>
                    <Td fontSize="xs">{formatTimestamp(row.expires_at)}</Td>
                    <Td fontSize="xs">{formatTimestamp(row.updated_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Box>
      </VStack>
    </TabFrame>
  );
};

/* -------------------------------------------------------------------------- */
/* Routing kernel configuration                                               */
/* -------------------------------------------------------------------------- */

const RoutingTab = () => {
  const { data, loading, error, refresh } = useGovernanceResource<RoutingConfig>(
    (signal) => fetchRoutingConfig({ signal }),
    []
  );

  return (
    <TabFrame loading={loading} error={error} onRetry={refresh}>
      {data && (
        <VStack spacing={5} align="stretch">
          {data.source === 'environment' && (
            <Alert status="warning" fontSize="sm">
              <AlertIcon />
              The orchestrator is not initialized, so these values come from
              configuration rather than live state. Capability labels are
              unavailable in this mode.
            </Alert>
          )}

          <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
            <Stat>
              <StatLabel>Routing kernel</StatLabel>
              <StatNumber fontSize="md">
                <Badge colorScheme={data.kernel_active ? 'green' : 'red'}>
                  {data.kernel_active
                    ? 'active'
                    : data.kernel_enabled
                      ? 'failed to build'
                      : 'disabled'}
                </Badge>
              </StatNumber>
            </Stat>
            <Stat>
              <StatLabel>Hebbian routing</StatLabel>
              <StatNumber fontSize="md">
                <Badge colorScheme={data.hebbian_enabled ? 'green' : 'gray'}>
                  {data.hebbian_enabled ? 'on' : 'off'}
                </Badge>
              </StatNumber>
            </Stat>
            <Stat>
              <StatLabel>Trust signal</StatLabel>
              <StatNumber fontSize="md">
                <Badge colorScheme={data.trust_signal_active ? 'green' : 'gray'}>
                  {data.trust_signal_active ? 'persisting' : 'unavailable'}
                </Badge>
              </StatNumber>
            </Stat>
            <Stat>
              <StatLabel>ATP strict</StatLabel>
              <StatNumber fontSize="md">
                <Badge colorScheme={data.atp_strict ? 'orange' : 'gray'}>
                  {data.atp_strict ? 'reject' : 'attach'}
                </Badge>
              </StatNumber>
            </Stat>
          </SimpleGrid>

          <Box>
            <Heading as="h3" size="sm" mb={2}>
              Ranking blend
            </Heading>
            <Text fontFamily="mono" fontSize="sm" color={fg['1']}>
              score = {(1 - data.alpha - data.beta).toFixed(2)}·composite +{' '}
              {data.alpha.toFixed(2)}·hebbian + {data.beta.toFixed(2)}·trust
            </Text>
            <Text fontSize="xs" color={fg['3']} mt={1}>
              Trust floor {data.trust_floor.toFixed(2)}
              {data.trust_floor === 0 && ' (floor exclusion disabled)'} · fallback
              capability {data.fallback_capability ?? 'disabled'} · Sentinel
              window {data.sentinel.window}, threshold{' '}
              {data.sentinel.threshold.toFixed(2)}, warmup {data.sentinel.warmup}
            </Text>
          </Box>

          <Box>
            <Heading as="h3" size="sm" mb={2}>
              Capabilities
            </Heading>
            <Text fontSize="xs" color={fg['3']} mb={3}>
              A capability outside the reviewed ATP execution domain is served
              by the legacy compatibility path without kernel authorization.
              Widening the domain is a reviewed change to `_REVIEWED_PAIRS`.
            </Text>
            {data.capabilities.length === 0 ? (
              <RouteStatus
                status="empty"
                message="No capabilities reported. The orchestrator has no loaded agents."
                compact
              />
            ) : (
              <Table size="sm" variant="simple">
                <Thead>
                  <Tr>
                    <Th>Capability</Th>
                    <Th>Routing path</Th>
                    <Th>Advertised by</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {data.capabilities.map((capability) => (
                    <Tr key={capability.name}>
                      <Td fontWeight="bold" fontFamily="mono">
                        {capability.name}
                      </Td>
                      <Td>
                        <Tooltip
                          hasArrow
                          placement="top"
                          label={
                            capability.kernel_reviewed
                              ? 'Inside the reviewed ATP execution domain: routed through the kernel with full authorization.'
                              : 'Outside the reviewed ATP execution domain: routed by the legacy compatibility path, skipping kernel authorization.'
                          }
                        >
                          <Badge
                            colorScheme={
                              capability.kernel_reviewed ? 'green' : 'orange'
                            }
                            cursor="help"
                          >
                            {capability.kernel_reviewed
                              ? 'kernel reviewed'
                              : 'legacy compatibility'}
                          </Badge>
                        </Tooltip>
                      </Td>
                      <Td fontSize="xs">{capability.agents.join(', ') || '—'}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </Box>

          <Flex>
            <Button size="sm" onClick={refresh}>
              Refresh
            </Button>
          </Flex>
        </VStack>
      )}
    </TabFrame>
  );
};

/* -------------------------------------------------------------------------- */

const Governance = () => (
  <Box>
    <Heading as="h2" size="xl" mb={2}>
      Governance
    </Heading>
    <Text fontSize="sm" color={fg['2']} mb={6}>
      Read-only view over trust, enforcement, learning stability, delegation,
      and the live routing configuration.
    </Text>

    <Tabs variant="enclosed" colorScheme="blue" isLazy>
      <TabList>
        <Tab>Trust</Tab>
        <Tab>Violations</Tab>
        <Tab>Stability</Tab>
        <Tab>Delegation</Tab>
        <Tab>Routing Kernel</Tab>
      </TabList>
      <TabPanels>
        <TabPanel>
          <TrustTab />
        </TabPanel>
        <TabPanel>
          <ViolationsTab />
        </TabPanel>
        <TabPanel>
          <SentinelTab />
        </TabPanel>
        <TabPanel>
          <DelegationTab />
        </TabPanel>
        <TabPanel>
          <RoutingTab />
        </TabPanel>
      </TabPanels>
    </Tabs>
  </Box>
);

export default Governance;
