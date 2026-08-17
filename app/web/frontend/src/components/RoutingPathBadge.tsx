/**
 * Presentation for a routing decision's `routing_path` label.
 *
 * The backend reports which routing implementation actually served a task
 * (see `ROUTING_PATHS` in `src/integration/hebbian_router.py`). Every legacy
 * value is a measurable gap rather than a normal outcome, so the copy here is
 * deliberately explicit about what was skipped — an operator should be able to
 * tell an authorized kernel route from a compatibility route at a glance,
 * without opening server logs.
 *
 * Keeping the whole vocabulary in one component means a path retiring (for
 * example when `_REVIEWED_PAIRS` is widened under review) is a single-file
 * change on the client.
 *
 * @module RoutingPathBadge
 */

import { Badge, Tooltip } from '@chakra-ui/react';

type PathPresentation = {
  label: string;
  colorScheme: string;
  help: string;
};

const PATHS: Record<string, PathPresentation> = {
  kernel: {
    label: 'kernel',
    colorScheme: 'green',
    help: 'Served by the shared Routing Kernel: intent → authorization → eligibility → Hebbian ranking. Governance and trust ran before learned ranking.',
  },
  hebbian_router: {
    label: 'legacy router',
    colorScheme: 'orange',
    help: 'Served by the legacy Hebbian router directly, without kernel authorization.',
  },
  legacy_unreviewed_capability: {
    label: 'legacy · unreviewed capability',
    colorScheme: 'orange',
    help: 'This capability has no reviewed ATP execution domain, so the kernel declined it and the legacy compatibility path served the task without kernel authorization.',
  },
  legacy_kernel_unavailable: {
    label: 'legacy · kernel unavailable',
    colorScheme: 'red',
    help: 'The Routing Kernel was disabled or failed to build at boot, so the legacy router served the task without kernel authorization.',
  },
  pinned: {
    label: 'pinned',
    colorScheme: 'blue',
    help: 'No routing ran: the caller named the agent explicitly.',
  },
  registry_composite: {
    label: 'registry composite',
    colorScheme: 'purple',
    help: 'Hebbian routing is disabled; the registry ranked candidates on composite score alone.',
  },
};

/** True when this path skipped Routing Kernel authorization. */
export const isLegacyRoutingPath = (path: string | null | undefined): boolean =>
  typeof path === 'string' && path.startsWith('legacy');

/** Human-readable label for a routing path, falling back to the raw value. */
export const routingPathLabel = (path: string | null | undefined): string =>
  (path && PATHS[path]?.label) || path || 'unknown';

const RoutingPathBadge = ({
  path,
  ml,
}: {
  path: string | null | undefined;
  ml?: string | number;
}) => {
  if (!path) return null;
  const presentation = PATHS[path] ?? {
    label: path,
    colorScheme: 'gray',
    help: 'Unrecognised routing path reported by the backend.',
  };
  return (
    <Tooltip label={presentation.help} placement="top" hasArrow openDelay={200}>
      <Badge ml={ml} colorScheme={presentation.colorScheme} cursor="help">
        {presentation.label}
      </Badge>
    </Tooltip>
  );
};

export default RoutingPathBadge;
