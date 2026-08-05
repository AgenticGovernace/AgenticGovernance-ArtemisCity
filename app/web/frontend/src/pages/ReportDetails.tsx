import {
  Box,
  Button,
  Heading,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import {
  ApiError,
  fetchReportContent,
  getUserFacingErrorMessage,
  isAbortError,
  type ReportContent,
} from '../api';
import ReportMarkdown from '../components/ReportMarkdown';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { isSafeReportFilename, routePaths } from '../router/paths';

const ReportDetails = () => {
  const { filename = '' } = useParams<{ filename: string }>();
  const [report, setReport] = useState<ReportContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const createController = useRequestController();

  useEffect(() => {
    const loadReport = async () => {
      const controller = createController();
      setLoading(true);
      setError(null);
      setReport(null);

      if (!isSafeReportFilename(filename)) {
        setError('Invalid report reference.');
        setLoading(false);
        return;
      }

      try {
        const data = await fetchReportContent(filename, { signal: controller.signal });
        setReport(data);
      } catch (err: unknown) {
        if (isAbortError(err)) return;
        setError(
          err instanceof ApiError && err.status === 404
            ? 'Report not found.'
            : getUserFacingErrorMessage(err, 'Failed to load this report.')
        );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    void loadReport();
  }, [createController, filename]);

  if (loading) return <RouteStatus status="loading" message="Loading report…" />;

  if (error || !report) {
    return (
      <RouteStatus
        status="error"
        message={error ?? 'Report not found.'}
        onRetry={() => window.location.reload()}
        backTo={routePaths.reports}
        backLabel="Back to reports"
      />
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
