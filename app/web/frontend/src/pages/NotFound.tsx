import { Box, Button, Heading, Text } from '@chakra-ui/react';
import { Link as RouterLink } from 'react-router-dom';
import { routePaths } from '../router/paths';

const NotFound = () => (
  <Box maxW="720px" py={8}>
    <Heading as="h1" size="xl" mb={3}>
      Page not found
    </Heading>
    <Text color="gray.300" mb={6}>
      This dashboard route does not exist or is no longer available.
    </Text>
    <Button as={RouterLink} to={routePaths.dashboard} colorScheme="blue">
      Return to dashboard
    </Button>
  </Box>
);

export default NotFound;
