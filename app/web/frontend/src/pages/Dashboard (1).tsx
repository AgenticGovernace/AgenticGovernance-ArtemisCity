/**
 * Dashboard Page Component
 *
 * Main landing page for the MCP Dashboard. Displays a welcome message
 * and provides navigation hints to users.
 *
 * @module Dashboard
 */

import { Box, Heading, Text } from '@chakra-ui/react';

/**
 * Dashboard home page component.
 *
 * Provides a welcoming entry point to the MCP Dashboard with
 * guidance on using the navigation.
 *
 * @returns The rendered dashboard page
 */
const Dashboard = () => {
  return (
    <Box>
      <Heading as="h2" size="xl" mb={4}>
        Dashboard
      </Heading>
      <Text fontSize="lg">Welcome to the MCP Obsidian Dashboard!</Text>
      <Text>Use the navigation to explore tasks, agents, and reports.</Text>
    </Box>
  );
};

export default Dashboard;
