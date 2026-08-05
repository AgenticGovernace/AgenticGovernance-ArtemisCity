import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Heading,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { fetchReportContent } from '../api';
import ReportMarkdown from '../components/ReportMarkdown';
import { isSafeReportFilename, routePaths } from '../router/paths';

interface ReportContent {
  filename: string;
  content: string;
}

const ReportDetails = () => {
  const { filename = '' } = useParams<{ filename: string }>();
  const [report, setReport] = useState<ReportContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadReport = async () => {
      setLoading(true);
      setError(null);
      setReport(null);

      if (!isSafeReportFilename(filename)) {
        setError('Invalid report reference.');
        setLoading(false);
        return;
      }

      try {
        const data = (await fetchReportContent(filename)) as ReportContent;
        if (!cancelled) setReport(data);
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : '';
          setError(
            message.includes('status: 404') ? 'Report not found.' : 'Failed to load this report.'
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void loadReport();
    return () => {
      cancelled = true;
    };
  }, [filename]);

  if (loading) {
    return (
      <Box textAlign="center" mt={8}>
        <Spinner size="xl" />
        <Text>Loading report...</Text>
      </Box>
    );
  }

  if (error || !report) {
    return (
      <VStack align="stretch" spacing={4} py={8}>
        <Alert status="error">
          <AlertIcon />
          {error ?? 'Report not found.'}
        </Alert>
        <Box>
          <Button as={RouterLink} to={routePaths.reports} colorScheme="blue">
            Back to reports
          </Button>
        </Box>
      </VStack>
    );
  }

  return (
    <Box maxW="1200px">
      <Button as={RouterLink} to={routePaths.reports} variant="link" mb={4}>
        ← Back to reports
      </Button>
      <Heading as="h1" size="xl" mb={5} wordBreak="break-word">
        {report.filename}
      </Heading>
      <ReportMarkdown content={report.content} />
    </Box>
  );
};

export default ReportDetails;
