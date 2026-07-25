/**
 * Glass-sidebar layout for the Artemis City dashboard.
 *
 * Ported from the exo-homelab UI kit: dark navy gradient page background,
 * 240px glass sidebar with grouped nav, active-cyan glow on the current
 * route, and a "session" footer card showing the backend's live status
 * (polled from /health). Mobile collapses the sidebar into a drawer.
 *
 * @module Layout
 */

import {
  Box,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerOverlay,
  Flex,
  IconButton,
  Text,
  useBreakpointValue,
  useDisclosure,
  VStack,
} from '@chakra-ui/react';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { GiHamburgerMenu } from 'react-icons/gi';
import { themeTokens } from '../theme';

const { accents, fg, bg } = themeTokens;

/* -------------------------------------------------------------------------- */
/* Inline icons (mirroring the exo-homelab Lucide-style strokes)              */
/* -------------------------------------------------------------------------- */

const IconWrap = ({ children }: { children: ReactNode }) => (
  <Box
    as="svg"
    viewBox="0 0 24 24"
    width="16px"
    height="16px"
    sx={{ stroke: 'currentColor', fill: 'none', strokeWidth: 1.8 }}
  >
    {children}
  </Box>
);

const DashboardIcon = () => (
  <IconWrap>
    <circle cx="12" cy="12" r="3" />
    <circle cx="12" cy="12" r="9" />
  </IconWrap>
);
const TasksIcon = () => (
  <IconWrap>
    <rect x="3" y="4" width="18" height="4" rx="1" />
    <rect x="3" y="10" width="18" height="4" rx="1" />
    <rect x="3" y="16" width="18" height="4" rx="1" />
  </IconWrap>
);
const ReportsIcon = () => (
  <IconWrap>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="8" y1="13" x2="16" y2="13" />
    <line x1="8" y1="17" x2="13" y2="17" />
  </IconWrap>
);
const AgentsIcon = () => (
  <IconWrap>
    <circle cx="12" cy="8" r="3" />
    <circle cx="20" cy="16" r="3" />
    <circle cx="4" cy="16" r="3" />
    <path d="M9 9l-3 5m9-5l3 5M9 14l5 1" />
  </IconWrap>
);
const DatabaseIcon = () => (
  <IconWrap>
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M3 5v6c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    <path d="M3 11v6c0 1.66 4 3 9 3s9-1.34 9-3v-6" />
  </IconWrap>
);
const ExecutorIcon = () => (
  <IconWrap>
    <polyline points="4 17 10 11 4 5" />
    <line x1="12" y1="19" x2="20" y2="19" />
  </IconWrap>
);

/* -------------------------------------------------------------------------- */
/* NavItem + NavGroup                                                         */
/* -------------------------------------------------------------------------- */

type NavSpec = { to: string; label: string; icon: ReactNode };

const NavItem = ({ to, label, icon, onClick }: NavSpec & { onClick?: () => void }) => (
  <Box
    as={NavLink}
    to={to}
    end={to === '/'}
    onClick={onClick}
    sx={{
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      padding: '8px 10px',
      borderRadius: '8px',
      color: fg['2'],
      fontFamily: 'body',
      fontSize: '13px',
      fontWeight: 500,
      textDecoration: 'none',
      border: '1px solid transparent',
      transition: 'all 150ms',
      '&:hover': {
        background: 'rgba(255,255,255,0.04)',
        color: fg['0'],
      },
      '&.active': {
        background: 'rgba(34,211,238,0.10)',
        color: accents.kernelSoft,
        borderColor: 'rgba(34,211,238,0.30)',
        boxShadow: '0 0 18px -6px rgba(34,211,238,0.5)',
      },
    }}
  >
    {icon}
    {label}
  </Box>
);

const NavGroup = ({
  title,
  items,
  onClickItem,
}: {
  title: string;
  items: NavSpec[];
  onClickItem?: () => void;
}) => (
  <Box mb="18px" display="flex" flexDirection="column" gap="2px">
    <Text
      fontFamily="mono"
      fontSize="10px"
      letterSpacing="0.16em"
      textTransform="uppercase"
      color={fg['3']}
      px="10px"
      pb="6px"
    >
      {title}
    </Text>
    {items.map((it) => (
      <NavItem key={it.to} {...it} onClick={onClickItem} />
    ))}
  </Box>
);

/* -------------------------------------------------------------------------- */
/* Session footer (live backend status)                                       */
/* -------------------------------------------------------------------------- */

type HealthState = { service: string; orchestrator: string } | null;

const useHealth = (): HealthState => {
  const [state, setState] = useState<HealthState>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        // /health is unauthenticated by design (see app/api/main.py).
        const r = await fetch('/health');
        if (!r.ok) return;
        const data = await r.json();
        if (alive) setState({ service: data.service, orchestrator: data.orchestrator });
      } catch {
        /* leave previous state */
      }
    };
    tick();
    const id = setInterval(tick, 8000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return state;
};

const SessionCard = () => {
  const health = useHealth();
  const ok = health?.orchestrator === 'ready';
  const orchestratorLabel = health?.orchestrator ?? 'connecting';
  return (
    <Box
      p="12px"
      bg="rgba(34,211,238,0.06)"
      border="1px solid"
      borderColor={ok ? 'rgba(34,211,238,0.30)' : 'rgba(245,158,11,0.30)'}
      borderRadius="10px"
      display="flex"
      flexDirection="column"
      gap="4px"
    >
      <Flex justify="space-between" fontFamily="mono" fontSize="11px">
        <Text color={fg['3']}>SERVICE</Text>
        <Text color={accents.kernelSoft}>{health?.service ?? '—'}</Text>
      </Flex>
      <Flex justify="space-between" fontFamily="mono" fontSize="11px">
        <Text color={fg['3']}>ORCHESTRATOR</Text>
        <Text color={ok ? accents.okSoft : accents.attentionSoft}>{orchestratorLabel}</Text>
      </Flex>
      <Flex justify="space-between" fontFamily="mono" fontSize="11px">
        <Text color={fg['3']}>API</Text>
        <Text color={accents.kernelSoft}>:8000</Text>
      </Flex>
    </Box>
  );
};

/* -------------------------------------------------------------------------- */
/* Sidebar content (shared between desktop + mobile drawer)                   */
/* -------------------------------------------------------------------------- */

const SidebarContent = ({ onClickItem }: { onClickItem?: () => void }) => (
  <VStack align="stretch" spacing={0} h="100%">
    <Box>
      <Text
        fontFamily="mono"
        fontSize="22px"
        fontWeight={600}
        color={fg['0']}
        letterSpacing="-0.01em"
        lineHeight="1"
        mb="4px"
      >
        artemis
        <Box as="span" color={accents.kernel}>
          .
        </Box>
        city
      </Text>
      <Text
        fontFamily="mono"
        fontSize="10px"
        color={fg['3']}
        letterSpacing="0.16em"
        textTransform="uppercase"
        mb="26px"
      >
        Agentic orchestration
      </Text>
    </Box>

    <NavGroup
      title="Operate"
      onClickItem={onClickItem}
      items={[
        { to: '/', label: 'Dashboard', icon: <DashboardIcon /> },
        { to: '/tasks', label: 'Tasks', icon: <TasksIcon /> },
        { to: '/reports', label: 'Reports', icon: <ReportsIcon /> },
        { to: '/executor', label: 'CLI Executor', icon: <ExecutorIcon /> },
      ]}
    />

    <NavGroup
      title="Inspect"
      onClickItem={onClickItem}
      items={[
        { to: '/agents', label: 'Agents', icon: <AgentsIcon /> },
        { to: '/database', label: 'Database Viewer', icon: <DatabaseIcon /> },
      ]}
    />

    <Box mt="auto">
      <SessionCard />
    </Box>
  </VStack>
);

/* -------------------------------------------------------------------------- */
/* Layout shell                                                               */
/* -------------------------------------------------------------------------- */

const Layout = () => {
  const { isOpen, onOpen, onClose } = useDisclosure();
  const isDesktop = useBreakpointValue({ base: false, md: true });

  return (
    <Flex minH="100vh" color={fg['0']}>
      {isDesktop && (
        <Box
          as="aside"
          w="240px"
          flexShrink={0}
          bg={bg.sidebar}
          sx={{ backdropFilter: 'blur(18px)' }}
          borderRight="1px solid"
          borderColor="rgba(255,255,255,0.10)"
          p="24px 16px"
          position="sticky"
          top={0}
          h="100vh"
        >
          <SidebarContent />
        </Box>
      )}

      {!isDesktop && (
        <IconButton
          aria-label="Open Menu"
          icon={<GiHamburgerMenu />}
          onClick={onOpen}
          position="fixed"
          top="16px"
          left="16px"
          zIndex="overlay"
          bg="rgba(11,18,36,0.7)"
          color={fg['0']}
          borderRadius="8px"
          border="1px solid"
          borderColor={bg.panelBorder}
          _hover={{ bg: 'rgba(34,211,238,0.10)' }}
        />
      )}

      <Drawer isOpen={isOpen} placement="left" onClose={onClose}>
        <DrawerOverlay />
        <DrawerContent
          maxW="260px"
          bg={bg.sidebar}
          sx={{ backdropFilter: 'blur(18px)' }}
          color={fg['0']}
        >
          <DrawerCloseButton color={fg['1']} />
          <DrawerBody p="24px 16px">
            <SidebarContent onClickItem={onClose} />
          </DrawerBody>
        </DrawerContent>
      </Drawer>

      <Box as="main" flex={1} p={{ base: '64px 20px 32px', md: '28px 32px 48px' }} minW={0}>
        <Outlet />
      </Box>
    </Flex>
  );
};

export default Layout;
