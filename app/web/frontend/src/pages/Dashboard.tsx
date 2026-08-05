/**
 * Cluster-style overview page.
 *
 * Mirrors the exo-homelab "Cluster Overview" surface: eyebrow + display
 * heading, KPI tile grid with kernel/memory/attention accents, and a
 * topology panel that lists the orchestrator's registered agents.
 * Counts are pulled from the existing dashboard API so the page reflects
 * whatever the backend actually has.
 */

import {
  Box,
  Flex,
  Grid,
  Heading,
  Spinner,
  Text,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import {
  fetchAgentScores,
  fetchHebbianStats,
  fetchReports,
  fetchVectorStats,
  getUserFacingErrorMessage,
} from '../api';
import { useRequestController } from '../hooks/useRequestController';
import { themeTokens } from '../theme';

const { accents, fg, bg } = themeTokens;

type Accent = 'kernel' | 'memory' | 'attention' | 'neutral';

const accentColor = (a: Accent): string => {
  switch (a) {
    case 'kernel':
      return accents.kernel;
    case 'memory':
      return accents.memory;
    case 'attention':
      return accents.attention;
    default:
      return 'rgba(255,255,255,0.10)';
  }
};

const Tile = ({
  label,
  value,
  sub,
  accent = 'neutral',
  loading,
}: {
  label: string;
  value: string | number | null;
  sub?: string;
  accent?: Accent;
  loading?: boolean;
}) => {
  const c = accentColor(accent);
  const shadow =
    accent === 'neutral' ? 'none' : `0 0 32px -10px ${c}66`;
  return (
    <Box
      p="16px 18px"
      bg={bg.panel}
      border="1px solid"
      borderColor={accent === 'neutral' ? bg.panelBorder : `${c}4D`}
      borderRadius="14px"
      sx={{ backdropFilter: 'blur(12px)', boxShadow: shadow }}
    >
      <Text
        fontFamily="mono"
        fontSize="10px"
        letterSpacing="0.12em"
        textTransform="uppercase"
        color={fg['3']}
        mb="6px"
      >
        {label}
      </Text>
      <Text fontFamily="mono" fontSize="26px" fontWeight={600} color={fg['0']} lineHeight="1">
        {loading ? <Spinner size="sm" color={c} /> : value ?? '—'}
      </Text>
      {sub && (
        <Text fontFamily="mono" fontSize="11px" color={fg['3']} mt="6px">
          {sub}
        </Text>
      )}
    </Box>
  );
};

/* -------------------------------------------------------------------------- */

const Panel = ({ title, tag, children }: { title: string; tag?: string; children: React.ReactNode }) => (
  <Box
    bg={bg.panel}
    border="1px solid"
    borderColor={bg.panelBorder}
    borderRadius="14px"
    sx={{ backdropFilter: 'blur(12px)' }}
    overflow="hidden"
  >
    <Flex justify="space-between" align="center" px="18px" py="14px" borderBottom="1px solid" borderColor="rgba(255,255,255,0.08)">
      <Heading as="h3" fontSize="16px" fontWeight={600} color={fg['0']} fontFamily="heading">
        {title}
      </Heading>
      {tag && (
        <Text fontFamily="mono" fontSize="10px" letterSpacing="0.12em" textTransform="uppercase" color={fg['3']}>
          {tag}
        </Text>
      )}
    </Flex>
    <Box>{children}</Box>
  </Box>
);

/* -------------------------------------------------------------------------- */

type AgentRow = {
  name: string;
  capabilities: string[];
  composite_score?: number;
};

const AgentTopology = ({ agents }: { agents: AgentRow[] | null }) => {
  if (agents === null) {
    return (
      <Box p="24px" color={fg['3']} fontFamily="mono" fontSize="12px">
        loading…
      </Box>
    );
  }
  if (agents.length === 0) {
    return (
      <Box p="24px" color={fg['3']} fontFamily="mono" fontSize="12px">
        no agents registered
      </Box>
    );
  }
  return (
    <Grid templateColumns={{ base: '1fr', md: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' }} gap="14px" p="24px">
      {agents.map((a, i) => {
        const isMaster = i === 0;
        const composite = a.composite_score ?? 0;
        const pct = Math.min(100, Math.max(0, composite * 100));
        return (
          <Box
            key={a.name}
            p="14px"
            bg={bg.inset}
            border="1px solid"
            borderColor={isMaster ? `${accents.kernel}80` : bg.panelBorder}
            borderRadius="12px"
            sx={{
              transition: 'all 200ms',
              boxShadow: isMaster ? `0 0 24px -8px ${accents.kernel}99` : 'none',
              '&:hover': { transform: 'translateY(-2px)', borderColor: `${accents.kernel}66` },
            }}
            display="flex"
            flexDirection="column"
            gap="4px"
          >
            <Flex align="center" gap="6px" fontFamily="mono" fontSize="13px" fontWeight={600} color={fg['0']}>
              {a.name}
              {isMaster && <Text as="span" color="#fbbf24" fontSize="11px">★</Text>}
            </Flex>
            <Text fontFamily="mono" fontSize="10px" letterSpacing="0.10em" textTransform="uppercase" color={fg['3']}>
              {a.capabilities.slice(0, 2).join(' · ') || 'no capabilities'}
            </Text>
            <Box mt="6px" fontFamily="mono" fontSize="10px" color={fg['2']}>
              score {composite.toFixed(2)}
            </Box>
            <Box h="4px" bg="rgba(255,255,255,0.08)" borderRadius="2px" overflow="hidden" mt="8px">
              <Box
                h="100%"
                w={`${pct}%`}
                bgGradient={`linear(to-r, ${accents.kernel}, ${accents.memory})`}
              />
            </Box>
          </Box>
        );
      })}
    </Grid>
  );
};

/* -------------------------------------------------------------------------- */

const Dashboard = () => {
  const [agents, setAgents] = useState<AgentRow[] | null>(null);
  const [hebbian, setHebbian] = useState<{ total_connections: number; total_activations: number; avg_weight: number } | null>(null);
  const [vectors, setVectors] = useState<{ total_docs: number } | null>(null);
  const [reportsCount, setReportsCount] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const createController = useRequestController();

  useEffect(() => {
    const controller = createController();
    Promise.allSettled([
      fetchAgentScores({ signal: controller.signal }),
      fetchHebbianStats({ signal: controller.signal }),
      fetchVectorStats({ signal: controller.signal }),
      fetchReports({ signal: controller.signal }),
    ]).then((results) => {
      if (controller.signal.aborted) return;
      const [a, h, v, r] = results;
      if (a.status === 'fulfilled') setAgents(a.value as AgentRow[]);
      if (h.status === 'fulfilled') setHebbian(h.value);
      if (v.status === 'fulfilled') setVectors(v.value);
      if (r.status === 'fulfilled' && Array.isArray(r.value)) setReportsCount(r.value.length);

      const fails = results.filter((x) => x.status === 'rejected');
      if (fails.length === results.length) {
        const firstFailure = fails[0];
        setErr(
          getUserFacingErrorMessage(
            firstFailure.status === 'rejected' ? firstFailure.reason : undefined,
            'The dashboard service is unavailable. Try again shortly.'
          )
        );
      }
    });
    return () => controller.abort();
  }, [createController]);

  const loading = agents === null && hebbian === null && vectors === null;

  return (
    <Box>
      {/* page head */}
      <Flex justify="space-between" align="flex-end" mb="26px" flexWrap="wrap" gap="12px">
        <Box>
          <Text
            fontFamily="mono"
            fontSize="11px"
            letterSpacing="0.16em"
            textTransform="uppercase"
            color={fg['3']}
            mb="8px"
          >
            artemis · v0.1.0 · :8000
          </Text>
          <Heading as="h1" fontSize="30px" fontWeight={600} color={fg['0']} letterSpacing="-0.02em" lineHeight="1.1">
            Cluster Overview
          </Heading>
        </Box>
        <Flex align="center" gap="12px" fontFamily="mono" fontSize="12px" color={fg['3']}>
          <Box
            w="8px"
            h="8px"
            borderRadius="50%"
            bg={err ? accents.err : '#22c55e'}
            sx={{
              boxShadow: err ? `0 0 12px ${accents.err}` : '0 0 12px #22c55e',
              animation: 'pulse 2s infinite',
              '@keyframes pulse': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.5 } },
            }}
          />
          <Text>{err ? 'backend offline' : `healthy · ${agents?.length ?? '…'} agent(s)`}</Text>
        </Flex>
      </Flex>

      {err && (
        <Box
          mb="18px"
          p="12px 16px"
          bg="rgba(245,158,11,0.10)"
          border="1px solid"
          borderColor="rgba(245,158,11,0.30)"
          borderRadius="10px"
          color={accents.attentionSoft}
          fontFamily="mono"
          fontSize="12px"
        >
          {err}
        </Box>
      )}

      {/* KPI tiles */}
      <Grid templateColumns={{ base: '1fr 1fr', lg: 'repeat(4, 1fr)' }} gap="14px" mb="22px">
        <Tile
          label="Agents registered"
          value={agents?.length ?? null}
          sub={agents ? `${agents.flatMap((a) => a.capabilities).length} capabilities` : undefined}
          accent="kernel"
          loading={loading}
        />
        <Tile
          label="Hebbian connections"
          value={hebbian?.total_connections ?? null}
          sub={hebbian ? `${hebbian.total_activations} activations · avg w ${hebbian.avg_weight.toFixed(2)}` : undefined}
          accent="memory"
          loading={loading}
        />
        <Tile
          label="Vector docs"
          value={vectors?.total_docs ?? null}
          sub={vectors ? 'indexed in semantic store' : undefined}
          accent="attention"
          loading={loading}
        />
        <Tile
          label="Reports archived"
          value={reportsCount}
          sub={reportsCount !== null ? 'in obsidian vault' : undefined}
          loading={loading}
        />
      </Grid>

      {/* topology */}
      <Panel title="Agent Topology" tag="orchestrator">
        <AgentTopology agents={agents} />
      </Panel>
    </Box>
  );
};

export default Dashboard;
