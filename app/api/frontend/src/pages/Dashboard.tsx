/**
 * Dashboard Page Component
 *
 * Main landing page for the MCP Dashboard. Displays live statistics
 * and provides quick access to key features.
 *
 * @module Dashboard
 */

import {
  Box,
  Button,
  Flex,
  Heading,
  SimpleGrid,
  Spinner,
  Stat,
  StatLabel,
  StatNumber,
  Text,
  VStack,
  HStack,
  useToast,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  fetchAgentScores,
  fetchHebbianStats,
  fetchVectorStats,
  fetchRuns,
} from '../api';

/**
 * Dashboard home page component.
 *
 * Displays live system statistics with auto-refresh capability,
 * and provides quick action buttons for common tasks.
 *
 * @returns The rendered dashboard page
 */
const Dashboard = () => {
  const [stats, setStats] = useState({
    agentCount: 0,
    hebbianConnections: 0,
    vectorDocs: 0,
    recentRuns: 0,
  });
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const loadStats = async () => {
    try {
      const [agents, hebbian, vectors, runs] = await Promise.all([
        fetchAgentScores(),
        fetchHebbianStats(),
        fetchVectorStats(),
        fetchRuns(5),
      ]);

      setStats({
        agentCount: agents.length,
        hebbianConnections: hebbian.total_connections,
        vectorDocs: vectors.total_docs,
        recentRuns: runs.length,
      });
    } catch (error) {
      console.error('Failed to load dashboard stats:', error);
      toast({
        title: 'Failed to load statistics',
        description: 'Some dashboard stats may be unavailable',
        status: 'warning',
        duration: 3000,
        isClosable: true,
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();

    // Auto-refresh every 10 seconds
    const interval = setInterval(loadStats, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Box>
      <VStack spacing={8} align="stretch">
        {/* Welcome Section */}
        <Box>
          <Heading as="h2" size="xl" mb={2}>
            Dashboard
          </Heading>
          <Text fontSize="lg" color="gray.600">
            Welcome to the MCP Obsidian Dashboard
          </Text>
          <Text fontSize="sm" color="gray.500">
            Monitor your agents, tasks, and system performance in real-time.
          </Text>
        </Box>

        {/* Stats Cards */}
        <Box>
          <Flex justify="space-between" align="center" mb={4}>
            <Heading as="h3" size="md">
              System Statistics
            </Heading>
            <Button
              size="sm"
              variant="ghost"
              onClick={loadStats}
              isLoading={loading}
            >
              Refresh
            </Button>
          </Flex>

          {loading ? (
            <Flex justify="center" py={8}>
              <Spinner size="lg" />
            </Flex>
          ) : (
            <SimpleGrid
              columns={{ base: 1, md: 2, lg: 4 }}
              spacing={4}
            >
              <Box
                p={6}
                borderWidth={1}
                borderRadius="lg"
                borderColor="gray.200"
                bg="white"
                _hover={{ boxShadow: 'md', borderColor: 'blue.200' }}
                transition="all 0.2s"
              >
                <Stat>
                  <StatLabel color="gray.600" mb={2}>
                    Active Agents
                  </StatLabel>
                  <StatNumber fontSize="3xl" color="blue.600">
                    {stats.agentCount}
                  </StatNumber>
                </Stat>
              </Box>

              <Box
                p={6}
                borderWidth={1}
                borderRadius="lg"
                borderColor="gray.200"
                bg="white"
                _hover={{ boxShadow: 'md', borderColor: 'green.200' }}
                transition="all 0.2s"
              >
                <Stat>
                  <StatLabel color="gray.600" mb={2}>
                    Hebbian Connections
                  </StatLabel>
                  <StatNumber fontSize="3xl" color="green.600">
                    {stats.hebbianConnections}
                  </StatNumber>
                </Stat>
              </Box>

              <Box
                p={6}
                borderWidth={1}
                borderRadius="lg"
                borderColor="gray.200"
                bg="white"
                _hover={{ boxShadow: 'md', borderColor: 'purple.200' }}
                transition="all 0.2s"
              >
                <Stat>
                  <StatLabel color="gray.600" mb={2}>
                    Vector Documents
                  </StatLabel>
                  <StatNumber fontSize="3xl" color="purple.600">
                    {stats.vectorDocs}
                  </StatNumber>
                </Stat>
              </Box>

              <Box
                p={6}
                borderWidth={1}
                borderRadius="lg"
                borderColor="gray.200"
                bg="white"
                _hover={{ boxShadow: 'md', borderColor: 'orange.200' }}
                transition="all 0.2s"
              >
                <Stat>
                  <StatLabel color="gray.600" mb={2}>
                    Recent Runs
                  </StatLabel>
                  <StatNumber fontSize="3xl" color="orange.600">
                    {stats.recentRuns}
                  </StatNumber>
                </Stat>
              </Box>
            </SimpleGrid>
          )}
        </Box>

        {/* Quick Actions */}
        <Box>
          <Heading as="h3" size="md" mb={4}>
            Quick Actions
          </Heading>
          <HStack spacing={4} flexWrap="wrap">
            <Button
              as={RouterLink}
              to="/executor"
              colorScheme="blue"
              size="lg"
              px={8}
            >
              Execute Command
            </Button>
            <Button
              as={RouterLink}
              to="/database"
              colorScheme="green"
              size="lg"
              px={8}
              variant="outline"
            >
              View Database
            </Button>
            <Button
              as={RouterLink}
              to="/tasks"
              colorScheme="purple"
              size="lg"
              px={8}
              variant="outline"
            >
              Manage Tasks
            </Button>
            <Button
              as={RouterLink}
              to="/agents"
              colorScheme="orange"
              size="lg"
              px={8}
              variant="outline"
            >
              View Agents
            </Button>
          </HStack>
        </Box>

        {/* Info Box */}
        <Box
          p={6}
          borderRadius="lg"
          bg="blue.50"
          borderLeft="4px solid"
          borderColor="blue.400"
        >
          <Heading as="h4" size="sm" mb={2} color="blue.900">
            Getting Started
          </Heading>
          <VStack align="start" spacing={2} color="blue.800" fontSize="sm">
            <Text>
              • Use the <strong>CLI Executor</strong> to run instructions and create tasks
            </Text>
            <Text>
              • Monitor agent performance in the <strong>Database Viewer</strong>
            </Text>
            <Text>
              • Manage and track tasks in the <strong>Tasks</strong> section
            </Text>
            <Text>
              • View system agents and their capabilities in the <strong>Agents</strong> section
            </Text>
          </VStack>
        </Box>
      </VStack>
    </Box>
  );
};

export default Dashboard;
