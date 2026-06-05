import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Heading,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useDisclosure,
  VStack,
} from '@chakra-ui/react';
import React, { useEffect, useState } from 'react';
import { fetchReportContent, fetchReports } from '../api';
import ReactMarkdown from 'react-markdown'; // For rendering markdown content

// We'll need to install react-markdown: npm install react-markdown

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
  const { isOpen, onOpen, onClose } = useDisclosure();
  const [selectedReportContent, setSelectedReportContent] = useState<string | null>(null);
  const [selectedReportFilename, setSelectedReportFilename] = useState<string | null>(null);

  useEffect(() => {
    const loadReports = async () => {
      try {
        setLoading(true);
        const data = await fetchReports();
        setReports(data);
      } catch (err) {
        setError('Failed to fetch reports.');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    loadReports();
  }, []);

  const handleViewReport = async (filename: string) => {
    try {
      setSelectedReportFilename(filename);
      const data = await fetchReportContent(filename);
      setSelectedReportContent(data.content);
      onOpen();
    } catch (err) {
      setError(`Failed to fetch report content for ${filename}.`);
      console.error(err);
    }
  };

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
            {reports.map((report) => (
              <Tr key={report.filename}>
                <Td>{report.filename}</Td>
                <Td>{report.agent}</Td>
                <Td>{report.task_id}</Td>
                <Td>
                  <Button size="sm" onClick={() => handleViewReport(report.filename)}>
                    View
                  </Button>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}

      <Modal isOpen={isOpen} onClose={onClose} size="full">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>{selectedReportFilename}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              {selectedReportContent ? (
                <Box p={4} borderWidth="1px" borderRadius="lg">
                  <ReactMarkdown>{selectedReportContent}</ReactMarkdown>
                </Box>
              ) : (
                <Text>Loading report content...</Text>
              )}
            </VStack>
          </ModalBody>
          <ModalFooter>
            <Button onClick={onClose}>Close</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  );
};

export default Reports;
