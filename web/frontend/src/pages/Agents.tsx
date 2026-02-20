/**
 * Agents Page Component
 *
 * Displays a list of all registered agents in the Artemis City system.
 * Fetches agent data from the MCP API and renders them in a list view.
 *
 * @module Agents
 */

import { Box, Heading, Text, Spinner, Alert, AlertIcon, List, ListItem, ListIcon } from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { fetchAgents } from '../api';
import { FaStar } from 'react-icons/fa';

/**
 * Interface representing an agent entity.
 */
interface Agent {
  /** The unique name identifier of the agent */
  name: string;
}

/**
 * Agents list page component.
 *
 * Fetches and displays all registered agents from the MCP server.
 * Shows loading spinner while fetching, error alerts on failure,
 * and an empty state message when no agents are found.
 *
 * @returns The rendered agents page
 */
const Agents = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadAgents = async () => {
      try {
        setLoading(true);
        const data = await fetchAgents();
        setAgents(data);
      } catch (err) {
        setError('Failed to fetch agents.');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    loadAgents();
  }, []);

  if (loading) {
    return (
      <Box textAlign="center" mt={8}>
        <Spinner size="xl" />
        <Text>Loading agents...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert status="error" mt={8}>
        <AlertIcon />
        {error}
      </Alert>
    );
  }

  return (
    <Box>
      <Heading as="h2" size="xl" mb={4}>Agents</Heading>
      {agents.length === 0 ? (
        <Text>No agents found.</Text>
      ) : (
        <List spacing={3}>
          {agents.map((agent) => (
            <ListItem key={agent.name}>
              <ListIcon as={FaStar} color="green.500" />
              <Text as="span" fontWeight="bold">{agent.name}</Text>
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
};

export default Agents;
