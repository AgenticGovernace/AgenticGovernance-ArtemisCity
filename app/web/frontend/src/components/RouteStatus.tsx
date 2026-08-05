import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Center,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react';
import { Link as RouterLink } from 'react-router-dom';

export type RouteStatusKind = 'loading' | 'error' | 'empty';

export interface RouteStatusProps {
  status: RouteStatusKind;
  message?: string;
  title?: string;
  onRetry?: () => void;
  backTo?: string;
  backLabel?: string;
  compact?: boolean;
}

/** Shared loading, retry, empty, and navigation states for routed pages. */
const RouteStatus = ({
  status,
  message,
  title,
  onRetry,
  backTo,
  backLabel = 'Back',
  compact = false,
}: RouteStatusProps) => {
  if (status === 'loading') {
    return (
      <Center py={compact ? 4 : 12} role="status" aria-live="polite">
        <VStack spacing={3}>
          <Spinner size={compact ? 'md' : 'xl'} />
          <Text color="gray.300">{message ?? 'Loading…'}</Text>
        </VStack>
      </Center>
    );
  }

  if (status === 'empty') {
    return (
      <Box py={compact ? 3 : 8} color="gray.400">
        <Text>{message ?? 'No data is available.'}</Text>
      </Box>
    );
  }

  return (
    <VStack align="stretch" spacing={4} py={compact ? 3 : 8}>
      <Alert status="error" role="alert">
        <AlertIcon />
        <Box>
          {title && <Text fontWeight="semibold">{title}</Text>}
          <Text>{message ?? 'The dashboard could not load this page.'}</Text>
        </Box>
      </Alert>
      <Box display="flex" gap={3} flexWrap="wrap">
        {onRetry && (
          <Button colorScheme="blue" onClick={onRetry}>
            Try again
          </Button>
        )}
        {backTo && (
          <Button as={RouterLink} to={backTo} variant="outline">
            {backLabel}
          </Button>
        )}
      </Box>
    </VStack>
  );
};

export default RouteStatus;
