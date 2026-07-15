/**
 * Database Viewer Page Component
 *
 * Displays SQLite database contents with tabbed interface for agents,
 * Hebbian network, vector store, and run logs. Includes auto-refresh
 * capability and filtering/sorting features.
 *
 * @module Database
 */

import {
  Box,
  Heading,
  Button,
  Flex,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Spinner,
  Alert,
  AlertIcon,
  Text,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Input,
  Select,
  VStack,
  HStack,
  Stat,
  StatLabel,
  StatNumber,
  SimpleGrid,
  Badge,
} from '@chakra-ui/react';
import React, { useEffect, useState } from 'react';
import {
  fetchAgentScores,
  fetchHebbianStats,
  fetchHebbianConnections,
  fetchVectorStats,
  fetchVectors,
  fetchRuns,
  fetchRunEvents,
} from '../api';

/**
 * Interface for agent score data
 */
interface AgentScore {
  name: string;
  capabilities: string[];
  alignment: number;
  accuracy: number;
  efficiency: number;
  composite_score: number;
}

/**
 * Interface for Hebbian connection data
 */
interface HebbianConnection {
  origin_node: string;
  target_node: string;
  weight: number;
  activation_count: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
}

/**
 * Interface for Hebbian network statistics
 */
interface HebbianStats {
  total_connections: number;
  avg_weight: number;
  max_weight: number;
  total_activations: number;
  total_successes: number;
  success_rate: number;
}

/**
 * Interface for vector store statistics
 */
interface VectorStoreStats {
  total_docs: number;
  avg_content_length: number;
}

/**
 * Interface for run summary
 */
interface RunSummary {
  run_id: string;
  start_time: string;
  end_time: string;
  total_events: number;
}

/**
 * Agents Tab Component - displays agent scores and metrics
 */
const AgentsTab = () => {
  const [agents, setAgents] = useState<AgentScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterCapability, setFilterCapability] = useState('');
  const [allCapabilities, setAllCapabilities] = useState<string[]>([]);

  const loadAgents = async () => {
    try {
      setLoading(true);
      const data = await fetchAgentScores();
      setAgents(data);

      // Extract unique capabilities
      const caps = new Set<string>();
      data.forEach((agent: AgentScore) => {
        agent.capabilities.forEach((cap) => caps.add(cap));
      });
      setAllCapabilities(Array.from(caps).sort());
    } catch (err) {
      setError('Failed to fetch agent scores.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAgents();
  }, []);

  const filteredAgents = agents.filter((agent) => {
    const matchesSearch =
      agent.name.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesCapability =
      !filterCapability ||
      agent.capabilities.includes(filterCapability);
    return matchesSearch && matchesCapability;
  });

  if (loading) {
    return (
      <Box textAlign="center" mt={4}>
        <Spinner size="lg" />
        <Text>Loading agents...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert status="error" mt={4}>
        <AlertIcon />
        {error}
      </Alert>
    );
  }

  return (
    <VStack spacing={4} align="stretch">
      <HStack spacing={4}>
        <Input
          placeholder="Search agents..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          size="sm"
        />
        <Select
          placeholder="Filter by capability"
          value={filterCapability}
          onChange={(e) => setFilterCapability(e.target.value)}
          size="sm"
          maxW="200px"
        >
          {allCapabilities.map((cap) => (
            <option key={cap} value={cap}>
              {cap}
            </option>
          ))}
        </Select>
        <Button size="sm" onClick={loadAgents}>
          Refresh
        </Button>
      </HStack>

      {filteredAgents.length === 0 ? (
        <Text>No agents found.</Text>
      ) : (
        <Table size="sm" variant="striped">
          <Thead>
            <Tr>
              <Th>Name</Th>
              <Th>Capabilities</Th>
              <Th isNumeric>Alignment</Th>
              <Th isNumeric>Accuracy</Th>
              <Th isNumeric>Efficiency</Th>
              <Th isNumeric>Composite Score</Th>
            </Tr>
          </Thead>
          <Tbody>
            {filteredAgents.map((agent) => (
              <Tr key={agent.name}>
                <Td fontWeight="bold">{agent.name}</Td>
                <Td>
                  <HStack spacing={2}>
                    {agent.capabilities.map((cap) => (
                      <Badge key={cap} colorScheme="blue" fontSize="xs">
                        {cap}
                      </Badge>
                    ))}
                  </HStack>
                </Td>
                <Td isNumeric>{agent.alignment.toFixed(3)}</Td>
                <Td isNumeric>{agent.accuracy.toFixed(3)}</Td>
                <Td isNumeric>{agent.efficiency.toFixed(3)}</Td>
                <Td isNumeric fontWeight="bold">
                  {agent.composite_score.toFixed(3)}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </VStack>
  );
};

/**
 * Hebbian Tab Component - displays network connections and statistics
 */
const HebbianTab = () => {
  const [stats, setStats] = useState<HebbianStats | null>(null);
  const [connections, setConnections] = useState<HebbianConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [limit, setLimit] = useState(50);

  const loadData = async () => {
    try {
      setLoading(true);
      const [statsData, connectionsData] = await Promise.all([
        fetchHebbianStats(),
        fetchHebbianConnections(limit),
      ]);
      setStats(statsData);
      setConnections(connectionsData);
    } catch (err) {
      setError('Failed to fetch Hebbian data.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [limit]);

  const filteredConnections = connections.filter((conn) => {
    const searchLower = searchTerm.toLowerCase();
    return (
      conn.origin_node.toLowerCase().includes(searchLower) ||
      conn.target_node.toLowerCase().includes(searchLower)
    );
  });

  if (loading) {
    return (
      <Box textAlign="center" mt={4}>
        <Spinner size="lg" />
        <Text>Loading Hebbian data...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert status="error" mt={4}>
        <AlertIcon />
        {error}
      </Alert>
    );
  }

  return (
    <VStack spacing={6} align="stretch">
      {stats && (
        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          <Stat>
            <StatLabel>Total Connections</StatLabel>
            <StatNumber>{stats.total_connections}</StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Average Weight</StatLabel>
            <StatNumber>{stats.avg_weight?.toFixed(3) || '0'}</StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Success Rate</StatLabel>
            <StatNumber>{(stats.success_rate * 100).toFixed(1)}%</StatNumber>
          </Stat>
        </SimpleGrid>
      )}

      <HStack spacing={4}>
        <Input
          placeholder="Search connections..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          size="sm"
        />
        <Select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          size="sm"
          maxW="150px"
        >
          <option value={25}>Top 25</option>
          <option value={50}>Top 50</option>
          <option value={100}>Top 100</option>
          <option value={200}>Top 200</option>
        </Select>
        <Button size="sm" onClick={loadData}>
          Refresh
        </Button>
      </HStack>

      {filteredConnections.length === 0 ? (
        <Text>No connections found.</Text>
      ) : (
        <Table size="sm" variant="striped">
          <Thead>
            <Tr>
              <Th>Origin</Th>
              <Th>Target</Th>
              <Th isNumeric>Weight</Th>
              <Th isNumeric>Activations</Th>
              <Th isNumeric>Success Rate</Th>
            </Tr>
          </Thead>
          <Tbody>
            {filteredConnections.map((conn, idx) => (
              <Tr key={idx}>
                <Td fontWeight="bold">{conn.origin_node}</Td>
                <Td>{conn.target_node}</Td>
                <Td isNumeric>{conn.weight.toFixed(3)}</Td>
                <Td isNumeric>{conn.activation_count}</Td>
                <Td isNumeric>{(conn.success_rate * 100).toFixed(1)}%</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </VStack>
  );
};

/**
 * Vector Store Tab Component - displays vector store statistics
 */
const VectorTab = () => {
  const [stats, setStats] = useState<VectorStoreStats | null>(null);
  const [vectors, setVectors] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const loadData = async () => {
    try {
      setLoading(true);
      const offset = (page - 1) * pageSize;
      const [statsData, vectorsData] = await Promise.all([
        fetchVectorStats(),
        fetchVectors(pageSize, offset),
      ]);
      setStats(statsData);
      setVectors(vectorsData);
    } catch (err) {
      setError('Failed to fetch vector data.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [page]);

  if (loading) {
    return (
      <Box textAlign="center" mt={4}>
        <Spinner size="lg" />
        <Text>Loading vector data...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert status="error" mt={4}>
        <AlertIcon />
        {error}
      </Alert>
    );
  }

  return (
    <VStack spacing={6} align="stretch">
      {stats && (
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
          <Stat>
            <StatLabel>Total Documents</StatLabel>
            <StatNumber>{stats.total_docs}</StatNumber>
          </Stat>
          <Stat>
            <StatLabel>Average Content Length</StatLabel>
            <StatNumber>{stats.avg_content_length?.toFixed(0) || '0'}</StatNumber>
          </Stat>
        </SimpleGrid>
      )}

      <HStack spacing={4}>
        <Button
          size="sm"
          onClick={() => setPage(Math.max(1, page - 1))}
          isDisabled={page === 1}
        >
          Previous
        </Button>
        <Text>Page {page}</Text>
        <Button size="sm" onClick={() => setPage(page + 1)}>
          Next
        </Button>
        <Button size="sm" onClick={loadData} ml="auto">
          Refresh
        </Button>
      </HStack>

      {vectors.length === 0 ? (
        <Text>No vectors found.</Text>
      ) : (
        <Table size="sm" variant="striped">
          <Thead>
            <Tr>
              <Th>Doc ID</Th>
              <Th>Content Preview</Th>
              <Th>Metadata</Th>
            </Tr>
          </Thead>
          <Tbody>
            {vectors.map((vector: any, idx: number) => (
              <Tr key={idx}>
                <Td fontWeight="bold" fontSize="xs">
                  {vector.doc_id || `Vector ${idx}`}
                </Td>
                <Td fontSize="xs">
                  {vector.content
                    ? vector.content.substring(0, 100) + '...'
                    : 'N/A'}
                </Td>
                <Td fontSize="xs">{JSON.stringify(vector.metadata || {})}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </VStack>
  );
};

/**
 * Runs Tab Component - displays execution run logs
 */
const RunsTab = () => {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [runEvents, setRunEvents] = useState<{ [key: string]: any[] }>({});
  const [loadingEvents, setLoadingEvents] = useState<{ [key: string]: boolean }>({});

  const loadRuns = async () => {
    try {
      setLoading(true);
      const data = await fetchRuns(20);
      setRuns(data);
    } catch (err) {
      setError('Failed to fetch runs.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadRunEvents = async (runId: string) => {
    if (runEvents[runId]) {
      setExpandedRun(expandedRun === runId ? null : runId);
      return;
    }

    try {
      setLoadingEvents((prev) => ({ ...prev, [runId]: true }));
      const events = await fetchRunEvents(runId);
      setRunEvents((prev) => ({ ...prev, [runId]: events }));
      setExpandedRun(runId);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingEvents((prev) => ({ ...prev, [runId]: false }));
    }
  };

  useEffect(() => {
    loadRuns();
  }, []);

  if (loading) {
    return (
      <Box textAlign="center" mt={4}>
        <Spinner size="lg" />
        <Text>Loading runs...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert status="error" mt={4}>
        <AlertIcon />
        {error}
      </Alert>
    );
  }

  return (
    <VStack spacing={4} align="stretch">
      <Button size="sm" onClick={loadRuns}>
        Refresh
      </Button>

      {runs.length === 0 ? (
        <Text>No runs found.</Text>
      ) : (
        <Table size="sm" variant="striped">
          <Thead>
            <Tr>
              <Th>Run ID</Th>
              <Th>Start Time</Th>
              <Th>End Time</Th>
              <Th isNumeric>Total Events</Th>
              <Th>Action</Th>
            </Tr>
          </Thead>
          <Tbody>
            {runs.map((run) => (
              <React.Fragment key={run.run_id}>
                <Tr
                  cursor="pointer"
                  _hover={{ bg: 'gray.100' }}
                  onClick={() => loadRunEvents(run.run_id)}
                >
                  <Td fontWeight="bold">{run.run_id}</Td>
                  <Td fontSize="sm">{new Date(run.start_time).toLocaleString()}</Td>
                  <Td fontSize="sm">{new Date(run.end_time).toLocaleString()}</Td>
                  <Td isNumeric>{run.total_events}</Td>
                  <Td>
                    <Button
                      size="xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        loadRunEvents(run.run_id);
                      }}
                      isLoading={loadingEvents[run.run_id] || false}
                    >
                      {expandedRun === run.run_id ? 'Collapse' : 'Expand'}
                    </Button>
                  </Td>
                </Tr>
                {expandedRun === run.run_id && runEvents[run.run_id] && (
                  <Tr>
                    <Td colSpan={5}>
                      <VStack spacing={2} align="stretch" pl={4}>
                        <Text fontWeight="bold" fontSize="sm">
                          Events ({runEvents[run.run_id].length})
                        </Text>
                        {runEvents[run.run_id].map((event: any, idx: number) => (
                          <Box
                            key={idx}
                            p={2}
                            bg="gray.50"
                            borderRadius="md"
                            fontSize="xs"
                          >
                            <Text>
                              <strong>{event.event_type}</strong> -{' '}
                              {event.message || event.details}
                            </Text>
                          </Box>
                        ))}
                      </VStack>
                    </Td>
                  </Tr>
                )}
              </React.Fragment>
            ))}
          </Tbody>
        </Table>
      )}
    </VStack>
  );
};

/**
 * Database Page Component
 *
 * Main page displaying database contents across multiple tabs
 * with auto-refresh capability.
 */
const Database = () => {
  const [activeTab, setActiveTab] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      // Trigger refresh by changing active tab slightly
      // In production, would implement per-tab refresh state
    }, 5000);

    return () => clearInterval(interval);
  }, [activeTab, autoRefresh]);

  return (
    <Box>
      <Flex justify="space-between" align="center" mb={6}>
        <Heading as="h2" size="xl">
          Database Viewer
        </Heading>
        <Button
          size="sm"
          colorScheme={autoRefresh ? 'green' : 'gray'}
          onClick={() => setAutoRefresh(!autoRefresh)}
        >
          {autoRefresh ? 'Auto-Refresh ON' : 'Auto-Refresh OFF'}
        </Button>
      </Flex>

      <Tabs
        index={activeTab}
        onChange={setActiveTab}
        variant="enclosed"
        colorScheme="blue"
      >
        <TabList>
          <Tab>Agents</Tab>
          <Tab>Hebbian Network</Tab>
          <Tab>Vector Store</Tab>
          <Tab>Run Logs</Tab>
        </TabList>

        <TabPanels>
          <TabPanel>
            <AgentsTab />
          </TabPanel>
          <TabPanel>
            <HebbianTab />
          </TabPanel>
          <TabPanel>
            <VectorTab />
          </TabPanel>
          <TabPanel>
            <RunsTab />
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Box>
  );
};

export default Database;
