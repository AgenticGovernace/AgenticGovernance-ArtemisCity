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
import { useEffect, useState } from 'react';
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
        {/* ModalContent picks up bg #0b1224 from theme. Force again here
            in case a future theme override defaults to white. */}
        <ModalContent bg="#0b1224" color="#e2e8f0">
          <ModalHeader color="#f8fafc">{selectedReportFilename}</ModalHeader>
          <ModalCloseButton color="#e2e8f0" />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              {selectedReportContent ? (
                <Box
                  p={4}
                  borderWidth="1px"
                  borderColor="rgba(255,255,255,0.10)"
                  borderRadius="lg"
                  bg="rgba(0,0,0,0.30)"
                  color="#e2e8f0"
                  // Style the raw HTML emitted by ReactMarkdown so the
                  // report body is legible on the dark theme. Without
                  // these overrides headings inherit dark grays and code
                  // blocks pick up browser-default white backgrounds.
                  sx={{
                    '& h1, & h2, & h3, & h4, & h5, & h6': {
                      color: '#f8fafc',
                      fontWeight: 600,
                      mt: 4,
                      mb: 2,
                    },
                    '& p, & li, & td, & th': { color: '#e2e8f0' },
                    '& strong': { color: '#f8fafc' },
                    '& a': { color: '#67e8f9', textDecoration: 'underline' },
                    '& code': {
                      bg: 'rgba(255,255,255,0.06)',
                      color: '#fcd34d',
                      px: 1.5,
                      py: 0.5,
                      borderRadius: '4px',
                      fontFamily: 'mono',
                      fontSize: '0.9em',
                    },
                    '& pre': {
                      bg: 'rgba(0,0,0,0.5)',
                      color: '#e2e8f0',
                      p: 3,
                      borderRadius: '8px',
                      overflowX: 'auto',
                      border: '1px solid rgba(255,255,255,0.10)',
                    },
                    '& pre code': { bg: 'transparent', color: 'inherit', p: 0 },
                    '& blockquote': {
                      borderLeft: '3px solid rgba(34,211,238,0.5)',
                      pl: 3,
                      color: '#cbd5e1',
                      fontStyle: 'italic',
                    },
                    '& hr': { borderColor: 'rgba(255,255,255,0.10)', my: 4 },
                    '& table': { borderCollapse: 'collapse', my: 2 },
                    '& th, & td': {
                      border: '1px solid rgba(255,255,255,0.10)',
                      px: 2,
                      py: 1,
                    },
                    '& ul, & ol': { pl: 5 },
                  }}
                >
                  <ReactMarkdown>{selectedReportContent}</ReactMarkdown>
                </Box>
              ) : (
                <Text color="#cbd5e1">Loading report content...</Text>
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
