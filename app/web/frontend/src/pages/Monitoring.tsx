/**
 * Governance monitoring page.
 *
 * Two data sources, deliberately independent:
 *  - `/api/monitoring/governance` — a durable snapshot read straight from
 *    the SQLite governance stores. Always available, even with the
 *    docker-compose monitoring stack down.
 *  - `/api/monitoring/prometheus` — alert-rule states and scrape-target
 *    health proxied from Prometheus, which also holds 30 days of metric
 *    history. Renders a hint instead of an error when the stack is off.
 *
 * Auto-refreshes every 30 seconds to match the Prometheus scrape interval.
 */

import {
  Badge,
  Box,
  Heading,
  SimpleGrid,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from '@chakra-ui/react';
import { useCallback, useEffect, useState } from 'react';
import {
  fetchGovernanceSnapshot,
  fetchPrometheusStatus,
  getUserFacingErrorMessage,
  isAbortError,
  type GovernanceSnapshot,
  type PrometheusStatus,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';

const REFRESH_INTERVAL_MS = 30_000;

const statusColor = (status: string): string => {
  if (status === 'quarantined') return 'red';
  if (status === 'suspended') return 'orange';
  return 'green';
};

const alertStateColor = (state: string): string => {
  if (state === 'firing') return 'red';
  if (state === 'pending') return 'orange';
  return 'green';
};

const trustColor = (score: number | null): string => {
  if (score === null) return 'gray';
  if (score < 0.3) return 'red';
  if (score < 0.7) return 'orange';
  return 'green';
};

const StatTile = ({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: 'good' | 'warn' | 'bad' | 'neutral';
}) => {
  const toneColor =
    tone === 'bad'
      ? 'red.300'
      : tone === 'warn'
        ? 'orange.300'
        : tone === 'good'
          ? 'green.300'
          : 'gray.300';
  return (
    <Box borderWidth="1px" borderRadius="md" p={4}>
      <Text fontSize="xs" textTransform="uppercase" letterSpacing="0.08em" mb={1}>
        {label}
      </Text>
      <Text fontSize="2xl" fontWeight={600} color={toneColor}>
        {value}
      </Text>
    </Box>
  );
};

const Monitoring = () => {
  const [snapshot, setSnapshot] = useState<GovernanceSnapshot | null>(null);
  const [prometheus, setPrometheus] = useState<PrometheusStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const createController = useRequestController();

  const load = useCallback(
    async (background = false) => {
      const controller = createController();
      if (!background) {
        setLoading(true);
        setError(null);
      }
      try {
        const [governance, prom] = await Promise.all([
          fetchGovernanceSnapshot({ signal: controller.signal }),
          fetchPrometheusStatus({ signal: controller.signal }),
        ]);
        setSnapshot(governance);
        setPrometheus(prom);
        setError(null);
      } catch (err: unknown) {
        if (isAbortError(err)) return;
        if (!background) {
          setError(getUserFacingErrorMessage(err, 'Failed to load monitoring data.'));
        }
      } finally {
        if (!controller.signal.aborted && !background) setLoading(false);
      }
    },
    [createController]
  );

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  if (loading) return <RouteStatus status="loading" message="Loading monitoring…" />;
  if (error) {
    return <RouteStatus status="error" message={error} onRetry={() => void load()} />;
  }
  if (!snapshot) {
    return <RouteStatus status="empty" message="No monitoring data available." compact />;
  }

  const quarantined = snapshot.status_counts.quarantined ?? 0;
  const suspended = snapshot.status_counts.suspended ?? 0;
  const activeSentinel = snapshot.sentinel.filter((s) => s.alert_active).length;
  const storesOk = Object.values(snapshot.stores).every(Boolean);
  const firingAlerts =
    prometheus?.alerts.filter((alert) => alert.state === 'firing') ?? [];

  return (
    <Box>
      <Heading as="h2" size="xl" mb={1}>
        Monitoring
      </Heading>
      <Text fontSize="sm" mb={5}>
        Governance state is read live from the durable SQLite stores; alerting and
        30-day history come from Prometheus when the monitoring stack is running.
      </Text>

      <SimpleGrid columns={{ base: 2, md: 5 }} spacing={3} mb={6}>
        <StatTile
          label="Quarantined"
          value={quarantined}
          tone={quarantined > 0 ? 'bad' : 'good'}
        />
        <StatTile
          label="Suspended"
          value={suspended}
          tone={suspended > 0 ? 'warn' : 'good'}
        />
        <StatTile
          label="Sentinel alerts"
          value={activeSentinel}
          tone={activeSentinel > 0 ? 'warn' : 'good'}
        />
        <StatTile
          label="Governance stores"
          value={storesOk ? 'readable' : 'degraded'}
          tone={storesOk ? 'good' : 'bad'}
        />
        <StatTile
          label="Prometheus"
          value={prometheus?.available ? 'connected' : 'offline'}
          tone={prometheus?.available ? 'good' : 'neutral'}
        />
      </SimpleGrid>

      {!prometheus?.available && (
        <Box borderWidth="1px" borderRadius="md" p={3} mb={6}>
          <Text fontSize="sm">
            Prometheus is unreachable — showing the durable SQLite snapshot only.
            Start the monitoring stack (<code>docker compose up prometheus grafana
            redis redis-exporter</code>) for alerting, Redis health, and metric
            history.
          </Text>
        </Box>
      )}

      {prometheus?.available && (
        <Box mb={6}>
          <Heading as="h3" size="md" mb={3}>
            Alerts{' '}
            {firingAlerts.length > 0 && (
              <Badge colorScheme="red" ml={2}>
                {firingAlerts.length} firing
              </Badge>
            )}
          </Heading>
          <TableContainer borderWidth="1px" borderRadius="md">
            <Table size="sm">
              <Thead>
                <Tr>
                  <Th>Alert</Th>
                  <Th>State</Th>
                  <Th>Severity</Th>
                  <Th>Scope</Th>
                </Tr>
              </Thead>
              <Tbody>
                {prometheus.alerts.map((alert) => (
                  <Tr key={alert.name}>
                    <Td>{alert.name}</Td>
                    <Td>
                      <Badge colorScheme={alertStateColor(alert.state)}>
                        {alert.state}
                      </Badge>
                    </Td>
                    <Td>{alert.severity ?? '—'}</Td>
                    <Td>
                      {alert.active.length > 0
                        ? alert.active
                            .map(
                              (instance) =>
                                instance.labels.agent ??
                                instance.labels.store ??
                                instance.labels.job ??
                                ''
                            )
                            .filter(Boolean)
                            .join(', ') || '—'
                        : '—'}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </TableContainer>

          <Heading as="h3" size="md" mt={5} mb={3}>
            Scrape targets
          </Heading>
          <TableContainer borderWidth="1px" borderRadius="md">
            <Table size="sm">
              <Thead>
                <Tr>
                  <Th>Job</Th>
                  <Th>Health</Th>
                  <Th>Endpoint</Th>
                </Tr>
              </Thead>
              <Tbody>
                {prometheus.targets.map((target) => (
                  <Tr key={`${target.job}-${target.scrape_url}`}>
                    <Td>{target.job ?? '—'}</Td>
                    <Td>
                      <Badge colorScheme={target.health === 'up' ? 'green' : 'red'}>
                        {target.health}
                      </Badge>
                    </Td>
                    <Td fontFamily="mono" fontSize="xs">
                      {target.scrape_url}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </TableContainer>
        </Box>
      )}

      <Heading as="h3" size="md" mb={3}>
        Agent governance
      </Heading>
      <TableContainer borderWidth="1px" borderRadius="md" mb={6}>
        <Table size="sm">
          <Thead>
            <Tr>
              <Th>Agent</Th>
              <Th>Status</Th>
              <Th>Trust tier</Th>
              <Th isNumeric>Trust score</Th>
              <Th isNumeric>Violations</Th>
            </Tr>
          </Thead>
          <Tbody>
            {snapshot.agents.map((agent) => (
              <Tr key={agent.name}>
                <Td>{agent.name}</Td>
                <Td>
                  <Badge colorScheme={statusColor(agent.status)}>{agent.status}</Badge>
                </Td>
                <Td>{agent.tier || '—'}</Td>
                <Td isNumeric>
                  <Text as="span" color={`${trustColor(agent.trust_score)}.300`}>
                    {agent.trust_score === null
                      ? 'unscored'
                      : agent.trust_score.toFixed(2)}
                  </Text>
                </Td>
                <Td isNumeric>{agent.violations}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </TableContainer>

      <Heading as="h3" size="md" mb={3}>
        Hebbian Sentinel
      </Heading>
      {snapshot.sentinel.length === 0 ? (
        <RouteStatus status="empty" message="No Sentinel scopes recorded yet." compact />
      ) : (
        <TableContainer borderWidth="1px" borderRadius="md">
          <Table size="sm">
            <Thead>
              <Tr>
                <Th>Agent</Th>
                <Th>Task type</Th>
                <Th>Alert</Th>
                <Th isNumeric>Oscillation</Th>
                <Th isNumeric>Threshold</Th>
                <Th isNumeric>Samples</Th>
              </Tr>
            </Thead>
            <Tbody>
              {snapshot.sentinel.map((scope) => (
                <Tr key={`${scope.agent}-${scope.task_type}`}>
                  <Td>{scope.agent}</Td>
                  <Td>{scope.task_type}</Td>
                  <Td>
                    <Badge colorScheme={scope.alert_active ? 'red' : 'green'}>
                      {scope.alert_active ? 'active' : 'stable'}
                    </Badge>
                  </Td>
                  <Td isNumeric>{scope.oscillation_rate.toFixed(2)}</Td>
                  <Td isNumeric>{scope.threshold.toFixed(2)}</Td>
                  <Td isNumeric>{scope.sample_count}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
};

export default Monitoring;
