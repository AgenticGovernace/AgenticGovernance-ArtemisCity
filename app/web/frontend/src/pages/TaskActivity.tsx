import {
  Badge,
  Box,
  Button,
  Code,
  Divider,
  Heading,
  Link,
  SimpleGrid,
  Text,
  VStack,
} from '@chakra-ui/react';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import {
  ApiError,
  fetchTaskActivity,
  getUserFacingErrorMessage,
  isAbortError,
  type TaskActivity as TaskActivityData,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { isSafeReportFilename, routePaths } from '../router/paths';

const displayValue = (value: unknown, fallback = 'Not recorded'): string => {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;

const SummaryValue = ({ label, value }: { label: string; value: string }) => (
  <Box p={4} borderWidth="1px" borderRadius="md" bg="rgba(255,255,255,0.03)">
    <Text fontSize="xs" color="gray.400" textTransform="uppercase" letterSpacing="0.08em">
      {label}
    </Text>
    <Text mt={1} fontWeight="semibold" wordBreak="break-word">
      {value}
    </Text>
  </Box>
);

const TaskActivity = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [activity, setActivity] = useState<TaskActivityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const createController = useRequestController();

  const loadActivity = useCallback(async () => {
    const controller = createController();
    setLoading(true);
    setError(null);
    setActivity(null);

    if (!taskId) {
      setError('Task activity was not found.');
      setLoading(false);
      return;
    }

    try {
      const data = await fetchTaskActivity(taskId, 200, { signal: controller.signal });
      setActivity(data);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(
        err instanceof ApiError && err.status === 404
          ? 'Task activity was not found.'
          : getUserFacingErrorMessage(err, 'Failed to load task activity.')
      );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [createController, taskId]);

  useEffect(() => {
    void loadActivity();
  }, [loadActivity]);

  if (loading) return <RouteStatus status="loading" message="Loading task activity…" />;
  if (error || !activity) {
    return (
      <RouteStatus
        status="error"
        message={error ?? 'Task activity was not found.'}
        onRetry={() => void loadActivity()}
        backTo={taskId ? routePaths.task(taskId) : routePaths.tasks}
        backLabel="Back to task"
      />
    );
  }

  const routing = activity.routing;
  const candidates = Array.isArray(routing?.candidates)
    ? routing.candidates.map(asRecord).filter((candidate): candidate is Record<string, unknown> => candidate !== null)
    : [];

  return (
    <Box maxW="1200px">
      <Button as={RouterLink} to={routePaths.task(activity.task_id)} variant="link" mb={4}>
        ← Back to task
      </Button>

      <VStack align="stretch" spacing={6}>
        <Box>
          <Text fontSize="sm" color="gray.400" mb={1}>
            Governed task activity
          </Text>
          <Heading as="h1" size="xl" wordBreak="break-word">
            {activity.task?.title || activity.task_id}
          </Heading>
          <Text mt={2} fontFamily="mono" fontSize="sm" color="gray.400" wordBreak="break-all">
            {activity.task_id}
          </Text>
        </Box>

        <SimpleGrid columns={{ base: 1, sm: 2, lg: 4 }} spacing={3}>
          <SummaryValue label="Status" value={displayValue(activity.status)} />
          <SummaryValue label="Selected agent" value={displayValue(activity.agent_name)} />
          <SummaryValue label="Capability" value={displayValue(activity.capability)} />
          <SummaryValue label="Provider" value={displayValue(activity.provider)} />
          <SummaryValue label="Outcome" value={displayValue(activity.outcome_class)} />
          <SummaryValue
            label="Learning"
            value={
              activity.learning_eligible === null
                ? 'Not recorded'
                : activity.learning_eligible
                  ? 'Eligible / recorded'
                  : 'Skipped'
            }
          />
          <SummaryValue label="Provenance root" value={displayValue(activity.provenance_id)} />
          <SummaryValue label="Recorded events" value={String(activity.events.length)} />
        </SimpleGrid>

        {routing && (
          <Box borderWidth="1px" borderRadius="md" p={4}>
            <Heading as="h2" size="md" mb={3}>
              Routing decision
            </Heading>
            <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3} mb={4}>
              <SummaryValue label="Decision agent" value={displayValue(routing.agent_name)} />
              <SummaryValue label="Routing scope" value={displayValue(routing.routing_scope)} />
              <SummaryValue label="ATP action" value={displayValue(routing.atp_action_type)} />
            </SimpleGrid>
            {candidates.length > 0 && (
              <VStack align="stretch" spacing={2}>
                {candidates.map((candidate, index) => (
                  <Box
                    key={`${displayValue(candidate.name, 'candidate')}-${index}`}
                    p={3}
                    borderWidth="1px"
                    borderRadius="sm"
                    bg="rgba(168,85,247,0.08)"
                  >
                    <Text fontWeight="semibold">{displayValue(candidate.name, 'Unnamed agent')}</Text>
                    <Text fontSize="sm" color="gray.300" mt={1}>
                      blended {displayValue(candidate.blended)} · composite {displayValue(candidate.composite)} · Hebbian {displayValue(candidate.hebbian_weight)} · trust {displayValue(candidate.trust_score)}
                    </Text>
                  </Box>
                ))}
              </VStack>
            )}
          </Box>
        )}

        <Box borderWidth="1px" borderRadius="md" p={4}>
          <Heading as="h2" size="md" mb={3}>
            Persisted reports
          </Heading>
          {activity.reports.length === 0 ? (
            <Text color="gray.400">No report is linked to this task yet.</Text>
          ) : (
            <VStack align="stretch" spacing={2}>
              {activity.reports.map((report) => (
                <Box key={report.filename} display="flex" justifyContent="space-between" gap={3}>
                  <Box minW={0}>
                    <Text wordBreak="break-word">{report.filename}</Text>
                    <Text fontSize="xs" color="gray.400">
                      {report.agent} · {report.timestamp}
                    </Text>
                  </Box>
                  {isSafeReportFilename(report.filename) ? (
                    <Link as={RouterLink} to={routePaths.report(report.filename)} color="blue.300" flexShrink={0}>
                      View report
                    </Link>
                  ) : (
                    <Text color="gray.500" fontSize="sm" flexShrink={0}>
                      Unavailable
                    </Text>
                  )}
                </Box>
              ))}
            </VStack>
          )}
        </Box>

        <Box>
          <Heading as="h2" size="md" mb={3}>
            Provenance timeline
          </Heading>
          {activity.events.length === 0 ? (
            <Text color="gray.400">No activity events have been recorded yet.</Text>
          ) : (
            <VStack align="stretch" spacing={3}>
              {activity.events.map((event, index) => (
                <Box key={`${event.timestamp}-${event.event_type}-${index}`} borderWidth="1px" borderRadius="md" p={4}>
                  <Box display="flex" justifyContent="space-between" gap={3} flexWrap="wrap">
                    <Box>
                      <Badge colorScheme={event.event_type === 'task_completed' ? 'green' : 'blue'}>
                        {event.event_type}
                      </Badge>
                      <Text mt={2} fontWeight="semibold">
                        {event.message || 'Recorded activity'}
                      </Text>
                    </Box>
                    <Text fontSize="xs" color="gray.400">
                      {event.timestamp}
                    </Text>
                  </Box>
                  <Divider my={3} />
                  <Text fontSize="xs" color="gray.400">
                    {event.component} · run {displayValue(event.run_id)}
                  </Text>
                  <Text fontSize="xs" color="gray.400" wordBreak="break-all">
                    provenance {displayValue(event.prov_id)} · parent {displayValue(event.parent_prov_id)}
                  </Text>
                  <Code display="block" mt={3} p={2} whiteSpace="pre-wrap" fontSize="xs" overflowX="auto">
                    {JSON.stringify(event.metadata, null, 2)}
                  </Code>
                </Box>
              ))}
            </VStack>
          )}
        </Box>
      </VStack>
    </Box>
  );
};

export default TaskActivity;
