import { Box, Heading, Text } from '@chakra-ui/react';

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
