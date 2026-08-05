import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Heading,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from '@chakra-ui/react';
import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { fetchReports } from '../api';
import { isSafeReportFilename, routePaths } from '../router/paths';

interface ReportSummary {
  filename: string;
  agent: string;
  task_id: string;
  timestamp: string;
}

const Reports = () => {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadReports = async () => {
      try {
        setLoading(true);
        const data = (await fetchReports()) as ReportSummary[];
        if (!cancelled) setReports(data);
      } catch {
        if (!cancelled) setError('Failed to fetch reports.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void loadReports();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <Box textAlign="center" mt={8}>
        <Spinner size="xl" />
        <Text>Loading reports...</Text>
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
        Reports
      </Heading>

      {reports.length === 0 ? (
        <Text>No reports found.</Text>
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
                  <Td>{report.task_id}</Td>
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
