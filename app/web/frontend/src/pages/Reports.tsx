import {
  Box,
  Button,
  Heading,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from '@chakra-ui/react';
import { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  fetchReports,
  getUserFacingErrorMessage,
  isAbortError,
  type ReportSummary,
} from '../api';
import RouteStatus from '../components/RouteStatus';
import { useRequestController } from '../hooks/useRequestController';
import { isSafeReportFilename, routePaths } from '../router/paths';

const Reports = () => {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const createController = useRequestController();

  const loadReports = useCallback(async () => {
    const controller = createController();
    setLoading(true);
    setError(null);
    try {
      const data = await fetchReports({ signal: controller.signal });
      setReports(data);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      setError(getUserFacingErrorMessage(err, 'Failed to fetch reports.'));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [createController]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  if (loading) return <RouteStatus status="loading" message="Loading reports…" />;

  if (error) {
    return <RouteStatus status="error" message={error} onRetry={() => void loadReports()} />;
  }

  return (
    <Box>
      <Heading as="h2" size="xl" mb={4}>
        Reports
      </Heading>

      {reports.length === 0 ? (
        <RouteStatus status="empty" message="No reports found." compact />
      ) : (
        <Table variant="simple">
          <Thead>
            <Tr>
              <Th>Filename</Th>
              <Th>Agent</Th>
              <Th>Task ID</Th>
              <Th>Actions</Th>
            </Tr>
          </Thead>
          <Tbody>
            {reports.map((report) => {
              const safeFilename = isSafeReportFilename(report.filename);
              return (
              <Tr key={report.filename}>
                <Td wordBreak="break-word">{report.filename}</Td>
                <Td>{report.agent}</Td>
                <Td>
                  {report.task_id && report.task_id !== 'unknown_task' ? (
                    <Button
                      as={RouterLink}
                      to={routePaths.taskActivity(report.task_id)}
                      variant="link"
                      size="sm"
                    >
                      {report.task_id}
                    </Button>
                  ) : (
                    report.task_id
                  )}
                </Td>
                  <Td>
                    {safeFilename ? (
                      <Button
                        as={RouterLink}
                        to={routePaths.report(report.filename)}
                        size="sm"
                      >
                        View report
                      </Button>
                    ) : (
                      <Text color="gray.400" fontSize="sm">
                        Unavailable
                      </Text>
                    )}
                  </Td>
                </Tr>
              );
            })}
          </Tbody>
        </Table>
      )}
    </Box>
  );
};

export default Reports;
