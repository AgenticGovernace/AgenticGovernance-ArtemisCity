import {
  Alert,
  AlertIcon,
  Box,
  Heading,
  List,
  ListIcon,
  ListItem,
  Spinner,
  Text,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { fetchAgents } from '../api';
import { FaStar } from 'react-icons/fa'; // Example icon

interface Agent {
  name: string;
}

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
      <Heading as="h2" size="xl" mb={4}>
        Agents
      </Heading>
      {agents.length === 0 ? (
        <Text>No agents found.</Text>
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
