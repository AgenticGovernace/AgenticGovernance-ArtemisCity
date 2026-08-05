import {
  Box,
  Heading,
  List,
  ListIcon,
  ListItem,
  Text,
} from '@chakra-ui/react';
import { useCallback, useEffect, useState } from 'react';
import {
  fetchAgents,
  getUserFacingErrorMessage,
  isAbortError,
  type AgentSummary,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { FaStar } from 'react-icons/fa'; // Example icon

const Agents = () => {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const createController = useRequestController();

  const loadAgents = useCallback(async () => {
    const controller = createController();
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAgents({ signal: controller.signal });
      setAgents(data);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err, 'Failed to fetch agents.'));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [createController]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  if (loading) return <RouteStatus status="loading" message="Loading agents…" />;

  if (error) {
    return <RouteStatus status="error" message={error} onRetry={() => void loadAgents()} />;
  }

  return (
    <Box>
      <Heading as="h2" size="xl" mb={4}>
        Agents
      </Heading>
      {agents.length === 0 ? (
        <RouteStatus status="empty" message="No agents found." compact />
      ) : (
        <List spacing={3}>
          {agents.map((agent) => (
            <ListItem key={agent.name}>
              <ListIcon as={FaStar} color="green.500" />
              <Text as="span" fontWeight="bold">
                {agent.name}
              </Text>
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
};

export default Agents;
