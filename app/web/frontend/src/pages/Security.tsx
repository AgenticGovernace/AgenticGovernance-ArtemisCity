/**
 * Security page — mutual-TLS identity for the memory server.
 *
 * Two projections, both read straight from the files the memory server
 * enforces on:
 *
 *   - **Client registry** — the `.agent/clients/*.yaml` manifests: which agent
 *     certificates are pinned, what routes each may call, and which are
 *     revoked or about to expire.
 *   - **Handshake ledger** — the append-only `.agent/logs/handshakes-*.yaml`
 *     record of every accepted and refused connection.
 *
 * There is no write path here on purpose. Issuing and revoking certificates
 * lives in `scripts/mtls/artemis-mtls.sh`, alongside the private keys; a
 * dashboard button that could revoke an agent would be a second source of
 * truth for exactly the state that must have only one.
 *
 * @module Security
 */

import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Heading,
  HStack,
  Input,
  SimpleGrid,
  Stat,
  StatHelpText,
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
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchMtlsClients,
  fetchMtlsHandshakes,
  fetchMtlsStatus,
  getUserFacingErrorMessage,
  isAbortError,
  type MtlsClient,
  type MtlsClientStatus,
  type MtlsHandshake,
  type MtlsStatus,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { themeTokens } from '../theme';

const { fg, bg } = themeTokens;

/** How many ledger entries to pull per refresh. */
const HANDSHAKE_LIMIT = 200;

/** Certificate lifecycle states, mapped to badge colours. */
const STATUS_COLORS: Record<MtlsClientStatus, string> = {
  active: 'green',
  revoked: 'red',
  expired: 'orange',
  not_yet_valid: 'purple',
  invalid: 'red',
};

/**
 * Human phrasing for each denial reason the memory server emits.
 *
 * The raw values are stable identifiers written into the ledger; these strings
 * exist so an operator reading the page does not have to know them by heart.
 */
const REASON_LABELS: Record<string, string> = {
  no_client_certificate: 'No client certificate presented',
  unknown_fingerprint: 'Certificate not in the registry',
  revoked: 'Certificate revoked',
  not_yet_valid: 'Certificate not yet valid',
  expired: 'Certificate expired',
  route_not_allowed: 'Route outside the agent’s allow-list',
};

const describeReason = (reason: string | null): string => {
  if (!reason) return '—';
  if (REASON_LABELS[reason]) return REASON_LABELS[reason];
  if (reason.startsWith('tls_unauthorized:')) {
    return `TLS verification failed (${reason.slice('tls_unauthorized:'.length)})`;
  }
  return reason;
};

const formatTimestamp = (value: string | null | undefined): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
};

/**
 * Abbreviate a fingerprint for table display.
 *
 * Enough leading and trailing bytes to compare against `openssl x509
 * -fingerprint -sha256` by eye, without a 95-character column. The full value
 * stays available in the tooltip.
 */
const shortFingerprint = (fingerprint: string): string => {
  if (!fingerprint) return '—';
  const bytes = fingerprint.split(':');
  if (bytes.length <= 8) return fingerprint;
  return `${bytes.slice(0, 4).join(':')}…${bytes.slice(-4).join(':')}`;
};

/** Expiry copy that says how urgent rotation is, not just when it happens. */
const describeExpiry = (client: MtlsClient): string => {
  if (client.days_remaining === null) return 'No expiry recorded';
  if (client.days_remaining < 0) return `Expired ${Math.abs(client.days_remaining)}d ago`;
  if (client.days_remaining === 0) return 'Expires today';
  return `${client.days_remaining}d remaining`;
};

const panelProps = {
  bg: bg.panel,
  border: '1px solid',
  borderColor: bg.panelBorder,
  borderRadius: 'lg',
  p: 5,
} as const;

/**
 * Header strip: is mTLS actually on, and is the registry healthy.
 *
 * The disabled state is rendered as a warning rather than a neutral fact. A
 * memory server running plaintext with a shared bearer token is the condition
 * this whole subsystem exists to end, so the page says so plainly.
 */
const StatusHeader = ({ status }: { status: MtlsStatus }) => (
  <VStack align="stretch" spacing={4}>
    {status.enabled ? (
      <Alert status="success" variant="subtle" borderRadius="md">
        <AlertIcon />
        <Box>
          <AlertTitle fontSize="sm">Mutual TLS enforced</AlertTitle>
          <AlertDescription fontSize="xs" color={fg['2']}>
            Every request to the memory server must present a client certificate
            signed by the local Artemis CA and pinned in the registry below.
          </AlertDescription>
        </Box>
      </Alert>
    ) : (
      <Alert status="warning" variant="subtle" borderRadius="md">
        <AlertIcon />
        <Box>
          <AlertTitle fontSize="sm">Mutual TLS is not enabled</AlertTitle>
          <AlertDescription fontSize="xs" color={fg['2']}>
            The memory server is authenticating with a shared bearer token only,
            which any local process able to read <Code fontSize="xs">.env</Code>{' '}
            can replay. Set <Code fontSize="xs">ARTEMIS_MTLS_ENABLED=1</Code> and
            run <Code fontSize="xs">scripts/mtls/artemis-mtls.sh init-ca</Code>.
            The registry below is shown for reference and is not being enforced.
          </AlertDescription>
        </Box>
      </Alert>
    )}

    <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
      <Box {...panelProps}>
        <Stat>
          <StatLabel color={fg['2']} fontSize="xs">
            Registered agents
          </StatLabel>
          <StatNumber fontSize="2xl">{status.client_count}</StatNumber>
        </Stat>
      </Box>
      <Box {...panelProps}>
        <Stat>
          <StatLabel color={fg['2']} fontSize="xs">
            Active
          </StatLabel>
          <StatNumber fontSize="2xl" color="green.300">
            {status.active_count}
          </StatNumber>
        </Stat>
      </Box>
      <Box {...panelProps}>
        <Stat>
          <StatLabel color={fg['2']} fontSize="xs">
            Revoked
          </StatLabel>
          <StatNumber fontSize="2xl" color={status.revoked_count > 0 ? 'red.300' : fg['1']}>
            {status.revoked_count}
          </StatNumber>
        </Stat>
      </Box>
      <Box {...panelProps}>
        <Stat>
          <StatLabel color={fg['2']} fontSize="xs">
            Expiring soon
          </StatLabel>
          <StatNumber
            fontSize="2xl"
            color={status.expiring_soon_count > 0 ? 'orange.300' : fg['1']}
          >
            {status.expiring_soon_count}
          </StatNumber>
          <StatHelpText fontSize="xs" color={fg['3']}>
            Rotate before expiry
          </StatHelpText>
        </Stat>
      </Box>
    </SimpleGrid>

    {status.problems.length > 0 && (
      <Alert status="error" variant="subtle" borderRadius="md" alignItems="flex-start">
        <AlertIcon />
        <Box>
          <AlertTitle fontSize="sm">
            {status.problems.length} manifest
            {status.problems.length === 1 ? '' : 's'} could not be loaded
          </AlertTitle>
          <AlertDescription fontSize="xs" color={fg['2']}>
            <Text mb={2}>
              An unloadable manifest is treated as an unknown agent — the server
              denies it rather than guessing. Fix the file to restore access.
            </Text>
            <VStack align="stretch" spacing={1}>
              {status.problems.map((problem) => (
                <Text key={`${problem.file}:${problem.error}`} fontFamily="mono">
                  {problem.file}: {problem.error}
                </Text>
              ))}
            </VStack>
          </AlertDescription>
        </Box>
      </Alert>
    )}

    <Text fontSize="xs" color={fg['3']} fontFamily="mono">
      registry {status.clients_dir} · ledger {status.logs_dir}
    </Text>
  </VStack>
);

/** Table of pinned client certificates and their route allow-lists. */
const ClientTable = ({ clients }: { clients: MtlsClient[] }) => {
  if (clients.length === 0) {
    return (
      <RouteStatus
        status="empty"
        compact
        title="No agents registered"
        message="Issue one with: scripts/mtls/artemis-mtls.sh issue-client <agent-id>"
      />
    );
  }

  return (
    <Box overflowX="auto">
      <Table size="sm" variant="simple">
        <Thead>
          <Tr>
            <Th>Agent</Th>
            <Th>Status</Th>
            <Th>Fingerprint (SHA-256)</Th>
            <Th>Allowed routes</Th>
            <Th>Expiry</Th>
            <Th>Manifest</Th>
          </Tr>
        </Thead>
        <Tbody>
          {clients.map((client) => (
            <Tr key={client.agent_id}>
              <Td>
                <VStack align="start" spacing={0}>
                  <Text fontWeight="semibold">{client.display_name}</Text>
                  {client.display_name !== client.agent_id && (
                    <Text fontSize="xs" color={fg['3']} fontFamily="mono">
                      {client.agent_id}
                    </Text>
                  )}
                </VStack>
              </Td>
              <Td>
                <Badge colorScheme={STATUS_COLORS[client.status] ?? 'gray'}>
                  {client.status.replace(/_/g, ' ')}
                </Badge>
              </Td>
              <Td>
                <Tooltip label={client.fingerprint_sha256} placement="top" hasArrow>
                  <Text fontFamily="mono" fontSize="xs" cursor="help">
                    {shortFingerprint(client.fingerprint_sha256)}
                  </Text>
                </Tooltip>
              </Td>
              <Td>
                <HStack spacing={1} flexWrap="wrap">
                  {client.allowed_routes.length === 0 ? (
                    <Tooltip
                      label="No routes listed — this agent is denied everywhere."
                      hasArrow
                    >
                      <Badge colorScheme="red">none</Badge>
                    </Tooltip>
                  ) : (
                    client.allowed_routes.map((route) => (
                      <Badge
                        key={route}
                        colorScheme={route === '*' ? 'orange' : 'gray'}
                        fontFamily="mono"
                        textTransform="none"
                      >
                        {route === '*' ? 'all routes' : route}
                      </Badge>
                    ))
                  )}
                </HStack>
              </Td>
              <Td>
                <VStack align="start" spacing={0}>
                  <Text
                    fontSize="xs"
                    color={
                      client.days_remaining !== null && client.days_remaining <= 14
                        ? 'orange.300'
                        : fg['1']
                    }
                  >
                    {describeExpiry(client)}
                  </Text>
                  <Text fontSize="xs" color={fg['3']}>
                    {formatTimestamp(client.valid_to)}
                  </Text>
                </VStack>
              </Td>
              <Td>
                <Text fontSize="xs" color={fg['3']} fontFamily="mono">
                  {client.manifest_file}
                </Text>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Box>
  );
};

type LedgerFilter = 'all' | 'accepted' | 'rejected';

/** Append-only record of every handshake decision the server made. */
const HandshakeTable = ({
  handshakes,
  filter,
  onFilterChange,
  search,
  onSearchChange,
}: {
  handshakes: MtlsHandshake[];
  filter: LedgerFilter;
  onFilterChange: (next: LedgerFilter) => void;
  search: string;
  onSearchChange: (next: string) => void;
}) => {
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return handshakes;
    return handshakes.filter((entry) =>
      [entry.agent_id, entry.client_cn, entry.route, entry.reason ?? '']
        .join(' ')
        .toLowerCase()
        .includes(needle)
    );
  }, [handshakes, search]);

  return (
    <VStack align="stretch" spacing={4}>
      <Flex gap={3} flexWrap="wrap" align="center">
        <HStack spacing={1}>
          {(['all', 'accepted', 'rejected'] as const).map((option) => (
            <Button
              key={option}
              size="xs"
              variant={filter === option ? 'solid' : 'ghost'}
              colorScheme={
                option === 'rejected' ? 'red' : option === 'accepted' ? 'green' : 'gray'
              }
              onClick={() => onFilterChange(option)}
            >
              {option}
            </Button>
          ))}
        </HStack>
        <Input
          size="xs"
          maxW="280px"
          placeholder="Filter by agent, route, or reason…"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          aria-label="Filter handshake ledger"
        />
        <Text fontSize="xs" color={fg['3']}>
          {visible.length} of {handshakes.length} shown
        </Text>
      </Flex>

      {visible.length === 0 ? (
        <RouteStatus
          status="empty"
          compact
          title="No handshakes recorded"
          message={
            handshakes.length === 0
              ? 'The ledger is empty. It fills as agents connect to the memory server.'
              : 'No entries match the current filter.'
          }
        />
      ) : (
        <Box overflowX="auto">
          <Table size="sm" variant="simple">
            <Thead>
              <Tr>
                <Th>When</Th>
                <Th>Result</Th>
                <Th>Agent</Th>
                <Th>Route</Th>
                <Th>Reason</Th>
                <Th>Fingerprint</Th>
              </Tr>
            </Thead>
            <Tbody>
              {visible.map((entry, index) => (
                <Tr key={`${entry.ts}:${entry.route}:${index}`}>
                  <Td whiteSpace="nowrap" fontSize="xs" color={fg['2']}>
                    {formatTimestamp(entry.ts)}
                  </Td>
                  <Td>
                    <Badge colorScheme={entry.result === 'accepted' ? 'green' : 'red'}>
                      {entry.result}
                    </Badge>
                  </Td>
                  <Td fontSize="xs">
                    {entry.agent_id || entry.client_cn || (
                      <Text as="span" color={fg['3']}>
                        unidentified
                      </Text>
                    )}
                  </Td>
                  <Td fontFamily="mono" fontSize="xs">
                    {entry.method} {entry.route}
                  </Td>
                  <Td fontSize="xs" color={entry.reason ? 'orange.200' : fg['3']}>
                    {describeReason(entry.reason)}
                  </Td>
                  <Td>
                    <Tooltip
                      label={entry.client_fingerprint_sha256 || 'none presented'}
                      placement="top"
                      hasArrow
                    >
                      <Text fontFamily="mono" fontSize="xs" cursor="help">
                        {shortFingerprint(entry.client_fingerprint_sha256)}
                      </Text>
                    </Tooltip>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Box>
      )}
    </VStack>
  );
};

/**
 * Security page root: loads registry and ledger together, renders both tabs.
 */
const Security = () => {
  const [status, setStatus] = useState<MtlsStatus | null>(null);
  const [clients, setClients] = useState<MtlsClient[]>([]);
  const [handshakes, setHandshakes] = useState<MtlsHandshake[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<LedgerFilter>('all');
  const [search, setSearch] = useState('');
  const createController = useRequestController();

  const load = useCallback(async () => {
    const controller = createController();
    setLoading(true);
    setError(null);
    try {
      const [nextStatus, nextClients, nextHandshakes] = await Promise.all([
        fetchMtlsStatus({ signal: controller.signal }),
        fetchMtlsClients({ signal: controller.signal }),
        fetchMtlsHandshakes(HANDSHAKE_LIMIT, undefined, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setStatus(nextStatus);
      setClients(nextClients);
      setHandshakes(nextHandshakes);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [createController]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleHandshakes = useMemo(
    () => (filter === 'all' ? handshakes : handshakes.filter((h) => h.result === filter)),
    [handshakes, filter]
  );

  if (loading && !status) {
    return <RouteStatus status="loading" message="Loading certificate registry…" />;
  }
  if (error && !status) {
    return <RouteStatus status="error" message={error} onRetry={() => void load()} />;
  }

  return (
    <VStack align="stretch" spacing={6}>
      <Flex justify="space-between" align="center" gap={4} flexWrap="wrap">
        <Box>
          <Heading size="lg">Security</Heading>
          <Text color={fg['2']} fontSize="sm">
            Mutual-TLS identity for the memory server — who may connect, on which
            routes, and every handshake that was accepted or refused.
          </Text>
        </Box>
        <Button size="sm" onClick={() => void load()} isLoading={loading}>
          Refresh
        </Button>
      </Flex>

      {error && (
        <Alert status="warning" borderRadius="md">
          <AlertIcon />
          <AlertDescription fontSize="sm">{error}</AlertDescription>
        </Alert>
      )}

      {status && <StatusHeader status={status} />}

      <Box {...panelProps} p={0}>
        <Tabs colorScheme="cyan" isLazy>
          <TabList px={4} pt={2}>
            <Tab fontSize="sm">Client registry ({clients.length})</Tab>
            <Tab fontSize="sm">Handshake ledger ({handshakes.length})</Tab>
          </TabList>
          <TabPanels>
            <TabPanel px={4} py={4}>
              <ClientTable clients={clients} />
            </TabPanel>
            <TabPanel px={4} py={4}>
              <HandshakeTable
                handshakes={visibleHandshakes}
                filter={filter}
                onFilterChange={setFilter}
                search={search}
                onSearchChange={setSearch}
              />
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Box>
    </VStack>
  );
};

export default Security;
